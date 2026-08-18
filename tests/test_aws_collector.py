"""Tests for the live AWS collector.

No real AWS account, credentials, or network access required: every boto3
client is wrapped in `botocore.stub.Stubber`, which intercepts the call
before it would ever be signed or sent, and validates the canned response
against AWS's own service model. That's what makes this safe to run in CI
on every push (see .github/workflows/ci.yml) with zero secrets involved.

Skipped entirely if boto3 isn't installed (it's the optional `aws` extra,
kept out of the base install so the sample-data demo path stays
dependency-free).
"""

from datetime import datetime, timezone

import pytest

boto3 = pytest.importorskip("boto3")
from botocore.exceptions import ClientError  # noqa: E402
from botocore.stub import Stubber  # noqa: E402

from greenpilot.aws.collector import (  # noqa: E402
    collect_ebs,
    collect_ec2,
    collect_rds,
    collect_s3,
    fetch_credential_report,
)

NOW = datetime(2026, 8, 18, tzinfo=timezone.utc)


def _client(service: str, region: str = "eu-west-1"):
    return boto3.client(service, region_name=region, aws_access_key_id="test", aws_secret_access_key="test")


def _cpu_response(avg: float):
    return {"Label": "CPUUtilization", "Datapoints": [{"Timestamp": NOW, "Average": avg, "Unit": "Percent"}]}


def _empty_metric_response():
    return {"Label": "", "Datapoints": []}


# ── EC2 ──────────────────────────────────────────────────────────────────────

def test_collect_ec2_maps_instance_fields_and_pricing():
    ec2 = _client("ec2")
    cw = _client("cloudwatch")
    ec2_stub, cw_stub = Stubber(ec2), Stubber(cw)

    ec2_stub.add_response(
        "describe_instances",
        {
            "Reservations": [
                {
                    "ReservationId": "r-1",
                    "OwnerId": "123456789012",
                    "Groups": [],
                    "Instances": [
                        {
                            "InstanceId": "i-idle01",
                            "InstanceType": "m5.large",
                            "State": {"Code": 16, "Name": "running"},
                            "Tags": [{"Key": "Name", "Value": "web-01"}],
                            "LaunchTime": NOW,
                        }
                    ],
                }
            ]
        },
    )
    cw_stub.add_response("get_metric_statistics", _cpu_response(3.2))

    ec2_stub.activate()
    cw_stub.activate()

    resources = collect_ec2(ec2, cw, "eu-west-1")

    assert len(resources) == 1
    r = resources[0]
    assert r.resource_id == "i-idle01"
    assert r.service == "EC2"
    assert r.region == "eu-west-1"
    assert r.avg_cpu_utilization_pct == 3.2
    assert r.tags == {"Name": "web-01"}
    assert r.publicly_accessible is False  # no PublicIpAddress on this instance
    assert r.monthly_cost == round(0.1070 * 730, 2)  # m5.large from EC2_HOURLY_USD

    ec2_stub.assert_no_pending_responses()
    cw_stub.assert_no_pending_responses()


def test_collect_ec2_detects_public_ip_and_schedulable_tag():
    ec2 = _client("ec2")
    cw = _client("cloudwatch")
    ec2_stub, cw_stub = Stubber(ec2), Stubber(cw)

    ec2_stub.add_response(
        "describe_instances",
        {
            "Reservations": [
                {
                    "ReservationId": "r-1",
                    "OwnerId": "123456789012",
                    "Groups": [],
                    "Instances": [
                        {
                            "InstanceId": "i-dev01",
                            "InstanceType": "t3.large",
                            "State": {"Code": 16, "Name": "running"},
                            "Tags": [{"Key": "Environment", "Value": "dev"}],
                            "PublicIpAddress": "203.0.113.10",
                            "LaunchTime": NOW,
                        }
                    ],
                }
            ]
        },
    )
    cw_stub.add_response("get_metric_statistics", _empty_metric_response())
    ec2_stub.activate()
    cw_stub.activate()

    resources = collect_ec2(ec2, cw, "eu-west-1")

    assert resources[0].publicly_accessible is True
    assert resources[0].schedulable is True
    assert resources[0].avg_cpu_utilization_pct is None  # no CloudWatch datapoints yet


# ── EBS ──────────────────────────────────────────────────────────────────────

def test_collect_ebs_maps_unattached_volume():
    ec2 = _client("ec2")
    stub = Stubber(ec2)
    stub.add_response(
        "describe_volumes",
        {
            "Volumes": [
                {
                    "VolumeId": "vol-orphan01",
                    "VolumeType": "gp3",
                    "Size": 250,
                    "State": "available",
                    "CreateTime": NOW,
                    "Tags": [],
                }
            ]
        },
        expected_params={"Filters": [{"Name": "status", "Values": ["available"]}]},
    )
    stub.activate()

    resources = collect_ebs(ec2, "eu-west-1")

    assert len(resources) == 1
    assert resources[0].attached is False
    assert resources[0].storage_gb == 250.0
    assert resources[0].monthly_cost == round(250 * 0.096, 2)


# ── RDS ──────────────────────────────────────────────────────────────────────

def test_collect_rds_flags_idle_replica_by_connection_count():
    rds = _client("rds")
    cw = _client("cloudwatch")
    rds_stub, cw_stub = Stubber(rds), Stubber(cw)

    rds_stub.add_response(
        "describe_db_instances",
        {
            "DBInstances": [
                {
                    "DBInstanceIdentifier": "rds-replica-idle",
                    "DBInstanceClass": "db.m5.large",
                    "Engine": "postgres",
                    "DBInstanceStatus": "available",
                    "MultiAZ": False,
                    "StorageEncrypted": True,
                    "PubliclyAccessible": False,
                    "ReadReplicaSourceDBInstanceIdentifier": "rds-primary",
                    "TagList": [],
                }
            ]
        },
    )
    cw_stub.add_response("get_metric_statistics", _cpu_response(0.0))
    rds_stub.activate()
    cw_stub.activate()

    resources = collect_rds(rds, cw, "eu-west-1")

    assert len(resources) == 1
    assert resources[0].is_redundant_replica is True
    assert resources[0].encrypted is True
    assert resources[0].publicly_accessible is False


def test_collect_rds_does_not_flag_a_busy_replica():
    rds = _client("rds")
    cw = _client("cloudwatch")
    rds_stub, cw_stub = Stubber(rds), Stubber(cw)

    rds_stub.add_response(
        "describe_db_instances",
        {
            "DBInstances": [
                {
                    "DBInstanceIdentifier": "rds-replica-busy",
                    "DBInstanceClass": "db.r5.large",
                    "Engine": "postgres",
                    "DBInstanceStatus": "available",
                    "MultiAZ": False,
                    "StorageEncrypted": True,
                    "PubliclyAccessible": False,
                    "ReadReplicaSourceDBInstanceIdentifier": "rds-primary",
                    "TagList": [],
                }
            ]
        },
    )
    cw_stub.add_response("get_metric_statistics", _cpu_response(42.0))
    rds_stub.activate()
    cw_stub.activate()

    resources = collect_rds(rds, cw, "eu-west-1")
    assert resources[0].is_redundant_replica is False


def test_collect_rds_primary_is_not_a_replica():
    rds = _client("rds")
    cw = _client("cloudwatch")
    rds_stub = Stubber(rds)

    rds_stub.add_response(
        "describe_db_instances",
        {
            "DBInstances": [
                {
                    "DBInstanceIdentifier": "rds-primary",
                    "DBInstanceClass": "db.m5.large",
                    "Engine": "postgres",
                    "DBInstanceStatus": "available",
                    "MultiAZ": True,
                    "StorageEncrypted": True,
                    "PubliclyAccessible": False,
                    "TagList": [],
                }
            ]
        },
    )
    rds_stub.activate()  # no CloudWatch stub needed: primary skips the connections check

    resources = collect_rds(rds, cw, "eu-west-1")
    assert resources[0].is_redundant_replica is False
    assert resources[0].multi_az is True


# ── S3 ───────────────────────────────────────────────────────────────────────

def test_collect_s3_flags_missing_public_access_block_and_no_lifecycle():
    s3 = _client("s3")
    cw = _client("cloudwatch")
    s3_stub, cw_stub = Stubber(s3), Stubber(cw)

    s3_stub.add_response("list_buckets", {"Buckets": [{"Name": "exposed-bucket", "CreationDate": NOW}], "Owner": {}})
    s3_stub.add_response("get_bucket_location", {"LocationConstraint": "eu-west-1"})
    cw_stub.add_response("get_metric_statistics", _empty_metric_response())
    s3_stub.add_client_error(
        "get_bucket_lifecycle_configuration", service_error_code="NoSuchLifecycleConfiguration"
    )
    s3_stub.add_client_error(
        "get_public_access_block", service_error_code="NoSuchPublicAccessBlockConfiguration"
    )
    s3_stub.add_response(
        "get_bucket_encryption",
        {"ServerSideEncryptionConfiguration": {"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}},
    )
    s3_stub.add_response("get_bucket_versioning", {"Status": "Enabled"})
    s3_stub.activate()
    cw_stub.activate()

    resources = collect_s3(s3, cw)

    assert len(resources) == 1
    r = resources[0]
    assert r.publicly_accessible is True  # no public access block configured at all
    assert r.access_frequency == "infrequent"  # no lifecycle policy
    assert r.encrypted is True
    assert r.versioning_enabled is True


def test_collect_s3_reports_unencrypted_bucket():
    s3 = _client("s3")
    cw = _client("cloudwatch")
    s3_stub, cw_stub = Stubber(s3), Stubber(cw)

    s3_stub.add_response("list_buckets", {"Buckets": [{"Name": "plain-bucket", "CreationDate": NOW}], "Owner": {}})
    s3_stub.add_response("get_bucket_location", {"LocationConstraint": "eu-central-1"})
    cw_stub.add_response("get_metric_statistics", _empty_metric_response())
    s3_stub.add_response(
        "get_bucket_lifecycle_configuration",
        {"Rules": [{"ID": "archive", "Status": "Enabled", "Filter": {}}]},
    )
    s3_stub.add_response(
        "get_public_access_block",
        {"PublicAccessBlockConfiguration": {
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        }},
    )
    s3_stub.add_client_error(
        "get_bucket_encryption", service_error_code="ServerSideEncryptionConfigurationNotFoundError"
    )
    s3_stub.add_response("get_bucket_versioning", {})
    s3_stub.activate()
    cw_stub.activate()

    resources = collect_s3(s3, cw)

    r = resources[0]
    assert r.publicly_accessible is False
    assert r.access_frequency == "frequent"  # has a lifecycle policy
    assert r.encrypted is False
    assert r.versioning_enabled is False


# ── IAM credential report ────────────────────────────────────────────────────

def test_fetch_credential_report_polls_until_complete(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)  # keep the test fast
    iam = _client("iam", region="us-east-1")
    stub = Stubber(iam)

    stub.add_response("generate_credential_report", {"State": "STARTED", "Description": "generating"})
    stub.add_response("generate_credential_report", {"State": "COMPLETE", "Description": "ready"})
    stub.add_response(
        "get_credential_report",
        {"Content": b"user,arn\nalice,arn:aws:iam::123456789012:user/alice\n", "ReportFormat": "text/csv", "GeneratedTime": NOW},
    )
    stub.activate()

    content = fetch_credential_report(iam, max_attempts=5)

    assert content.startswith("user,arn")
    stub.assert_no_pending_responses()


def test_fetch_credential_report_gives_up_after_max_attempts_and_still_fetches(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    iam = _client("iam", region="us-east-1")
    stub = Stubber(iam)

    for _ in range(3):
        stub.add_response("generate_credential_report", {"State": "STARTED", "Description": "generating"})
    stub.add_response(
        "get_credential_report",
        {"Content": b"user,arn\n", "ReportFormat": "text/csv", "GeneratedTime": NOW},
    )
    stub.activate()

    content = fetch_credential_report(iam, max_attempts=3)
    assert content == "user,arn\n"
