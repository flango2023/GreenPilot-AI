"""Live AWS collector: reads EC2, EBS, RDS, S3, and IAM credential-report
data via boto3 and maps it into the exact same `Resource`/`IamUser` records
the sample-data path produces, so `engine.analyze_resources` runs identical
rules against either source.

Needs only the permissions in ../../iam/read-only-collector-policy.json.
Never calls a mutating API. If a service call fails (missing permission,
region has nothing deployed, throttling), that one collector degrades to
an empty result plus a warning rather than aborting the whole run: a
partial assessment is more useful than none.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from ..credential_report import parse_credential_report
from ..models import IamUser, Resource

LOOKBACK_DAYS = 14
HOURS_PER_MONTH = 730.0
RDS_IDLE_REPLICA_CONNECTION_THRESHOLD = 1.0
_SCHEDULABLE_TAG_VALUES = {"dev", "development", "staging", "test", "testing", "sandbox"}

# Approximate on-demand hourly USD pricing. Real production use would read
# actual spend from Cost Explorer resource-level billing (a paid CE feature)
# or a Cost and Usage Report export instead of a static table; see
# docs/architecture.md for that limitation. Figures are illustrative, not
# pulled from a live pricing API; check the AWS Pricing Calculator for
# current, region-accurate rates.
EC2_HOURLY_USD = {
    "t3.micro": 0.0114, "t3.small": 0.0228, "t3.medium": 0.0456,
    "t3.large": 0.0912, "t3.xlarge": 0.1824, "t3.2xlarge": 0.3648,
    "m5.large": 0.1070, "m5.xlarge": 0.2140, "m5.2xlarge": 0.4280,
    "c5.large": 0.0960, "c5.xlarge": 0.1920, "c5.2xlarge": 0.3840,
    "r5.large": 0.1400, "r5.xlarge": 0.2800, "r5.2xlarge": 0.5600,
}
RDS_HOURLY_USD = {
    "db.t3.micro": 0.018, "db.t3.small": 0.036, "db.t3.medium": 0.072,
    "db.m5.large": 0.171, "db.m5.xlarge": 0.342,
    "db.r5.large": 0.240, "db.r5.xlarge": 0.480,
}
DEFAULT_EC2_HOURLY_USD = 0.10
DEFAULT_RDS_HOURLY_USD = 0.20
EBS_GB_MONTH_USD = {"gp2": 0.119, "gp3": 0.096, "io1": 0.149, "io2": 0.149, "st1": 0.054, "sc1": 0.030}
DEFAULT_EBS_GB_MONTH_USD = 0.10
S3_STANDARD_GB_MONTH_USD = 0.023


@dataclass
class ServiceCheck:
    ok: bool
    detail: str


@dataclass
class ConnectivityCheck:
    account_id: str
    arn: str
    ready: bool
    services: dict[str, ServiceCheck] = field(default_factory=dict)


@dataclass
class CollectionResult:
    resources: list[Resource] = field(default_factory=list)
    iam_users: list[IamUser] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_connectivity(session: boto3.Session) -> ConnectivityCheck:
    """Verify read access to every service the collector needs, one call
    each, before running a full collection. Mirrors what a real onboarding
    flow would show a customer before their first assessment."""
    sts = session.client("sts")
    identity = sts.get_caller_identity()

    checks = {
        "EC2": lambda: session.client("ec2").describe_instances(MaxResults=5),
        "EBS": lambda: session.client("ec2").describe_volumes(MaxResults=5),
        "RDS": lambda: session.client("rds").describe_db_instances(MaxRecords=20),
        "S3": lambda: session.client("s3").list_buckets(),
        "CloudWatch": lambda: session.client("cloudwatch").list_metrics(
            Namespace="AWS/EC2", MetricName="CPUUtilization"
        ),
        "Cost Explorer": lambda: session.client("ce", region_name="us-east-1").get_cost_and_usage(
            TimePeriod={
                "Start": (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d"),
                "End": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            },
            Granularity="MONTHLY",
            Metrics=["BlendedCost"],
        ),
        "IAM": lambda: session.client("iam").generate_credential_report(),
    }

    results = {}
    for name, call in checks.items():
        try:
            call()
            results[name] = ServiceCheck(True, "reachable")
        except (ClientError, BotoCoreError) as exc:
            results[name] = ServiceCheck(False, str(exc)[:120])

    return ConnectivityCheck(
        account_id=identity["Account"],
        arn=identity["Arn"],
        ready=all(c.ok for c in results.values()),
        services=results,
    )


def _tag(tags: list[dict] | None, key: str) -> str | None:
    for t in tags or []:
        if t.get("Key", "").lower() == key.lower():
            return t.get("Value")
    return None


def _is_schedulable(tags: list[dict] | None) -> bool:
    for key in ("Environment", "env", "Env", "environment"):
        value = _tag(tags, key)
        if value and value.lower() in _SCHEDULABLE_TAG_VALUES:
            return True
    return False


def _avg_metric(
    cw, namespace: str, metric: str, dimensions: list[dict], days: int = LOOKBACK_DAYS
) -> float | None:
    try:
        end = datetime.now(timezone.utc)
        response = cw.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric,
            Dimensions=dimensions,
            StartTime=end - timedelta(days=days),
            EndTime=end,
            Period=86400,
            Statistics=["Average"],
        )
        points = response.get("Datapoints", [])
        if not points:
            return None
        return round(sum(p["Average"] for p in points) / len(points), 2)
    except (ClientError, BotoCoreError):
        return None


def collect_ec2(ec2, cw, region: str) -> list[Resource]:
    """`ec2` and `cw` are already-constructed boto3 clients, not a Session:
    that makes this a pure mapping function you can hand a real client or a
    `botocore.stub.Stubber`-wrapped one in tests. See collect_all() for how
    the real clients get built."""
    response = ec2.describe_instances(
        Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
    )
    resources = []
    for reservation in response.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            instance_type = inst["InstanceType"]
            tags = inst.get("Tags", [])
            avg_cpu = _avg_metric(
                cw, "AWS/EC2", "CPUUtilization",
                [{"Name": "InstanceId", "Value": inst["InstanceId"]}],
            )
            resources.append(
                Resource(
                    resource_id=inst["InstanceId"],
                    service="EC2",
                    resource_type=instance_type,
                    region=region,
                    monthly_cost=round(
                        EC2_HOURLY_USD.get(instance_type, DEFAULT_EC2_HOURLY_USD) * HOURS_PER_MONTH,
                        2,
                    ),
                    tags={t["Key"]: t["Value"] for t in tags},
                    avg_cpu_utilization_pct=avg_cpu,
                    hours_running_per_month=HOURS_PER_MONTH,
                    schedulable=_is_schedulable(tags),
                    publicly_accessible=inst.get("PublicIpAddress") is not None,
                )
            )
    return resources


def collect_ebs(ec2, region: str) -> list[Resource]:
    response = ec2.describe_volumes(Filters=[{"Name": "status", "Values": ["available"]}])
    resources = []
    for vol in response.get("Volumes", []):
        volume_type = vol["VolumeType"]
        size_gb = vol["Size"]
        resources.append(
            Resource(
                resource_id=vol["VolumeId"],
                service="EBS",
                resource_type=volume_type,
                region=region,
                monthly_cost=round(size_gb * EBS_GB_MONTH_USD.get(volume_type, DEFAULT_EBS_GB_MONTH_USD), 2),
                tags={t["Key"]: t["Value"] for t in vol.get("Tags", [])},
                attached=False,  # the status=available filter guarantees this
                storage_gb=float(size_gb),
            )
        )
    return resources


def collect_rds(rds, cw, region: str) -> list[Resource]:
    response = rds.describe_db_instances()
    resources = []
    for db in response.get("DBInstances", []):
        instance_class = db["DBInstanceClass"]
        is_replica = bool(db.get("ReadReplicaSourceDBInstanceIdentifier"))
        is_redundant = False
        if is_replica:
            avg_connections = _avg_metric(
                cw, "AWS/RDS", "DatabaseConnections",
                [{"Name": "DBInstanceIdentifier", "Value": db["DBInstanceIdentifier"]}],
            )
            is_redundant = (
                avg_connections is not None
                and avg_connections < RDS_IDLE_REPLICA_CONNECTION_THRESHOLD
            )
        resources.append(
            Resource(
                resource_id=db["DBInstanceIdentifier"],
                service="RDS",
                resource_type=instance_class,
                region=region,
                monthly_cost=round(
                    RDS_HOURLY_USD.get(instance_class, DEFAULT_RDS_HOURLY_USD) * HOURS_PER_MONTH, 2
                ),
                tags={t["Key"]: t["Value"] for t in db.get("TagList", [])},
                multi_az=db.get("MultiAZ", False),
                is_redundant_replica=is_redundant,
                encrypted=db.get("StorageEncrypted"),
                publicly_accessible=db.get("PubliclyAccessible"),
            )
        )
    return resources


def collect_s3(s3, cw) -> list[Resource]:
    resources = []
    for bucket in s3.list_buckets().get("Buckets", []):
        name = bucket["Name"]
        try:
            location = s3.get_bucket_location(Bucket=name).get("LocationConstraint")
        except (ClientError, BotoCoreError):
            location = None
        region = location or "us-east-1"

        size_gb = 0.0
        avg_bytes = _avg_metric(
            cw, "AWS/S3", "BucketSizeBytes",
            [
                {"Name": "BucketName", "Value": name},
                {"Name": "StorageType", "Value": "StandardStorage"},
            ],
            days=2,
        )
        if avg_bytes:
            size_gb = round(avg_bytes / (1024**3), 2)

        has_lifecycle = True
        try:
            s3.get_bucket_lifecycle_configuration(Bucket=name)
        except ClientError as exc:
            if "NoSuchLifecycleConfiguration" in str(exc):
                has_lifecycle = False

        public = None
        try:
            cfg = s3.get_public_access_block(Bucket=name)["PublicAccessBlockConfiguration"]
            public = not all(cfg.values())
        except ClientError as exc:
            if "NoSuchPublicAccessBlockConfiguration" in str(exc):
                public = True

        encrypted = True
        try:
            s3.get_bucket_encryption(Bucket=name)
        except ClientError as exc:
            if "ServerSideEncryptionConfigurationNotFoundError" in str(exc):
                encrypted = False

        versioning_status = s3.get_bucket_versioning(Bucket=name).get("Status")

        resources.append(
            Resource(
                resource_id=name,
                service="S3",
                resource_type="bucket",
                region=region,
                monthly_cost=round(size_gb * S3_STANDARD_GB_MONTH_USD, 2),
                storage_class="STANDARD",
                # AWS doesn't expose real access-frequency without S3 Storage
                # Lens or Intelligent-Tiering activity metrics enabled. The
                # absence of a lifecycle policy is used as a proxy signal
                # here, same heuristic as the sample-data path documents.
                access_frequency="infrequent" if not has_lifecycle else "frequent",
                storage_gb=size_gb,
                publicly_accessible=public,
                encrypted=encrypted,
                versioning_enabled=versioning_status == "Enabled",
            )
        )
    return resources


def fetch_credential_report(iam, max_attempts: int = 10) -> str:
    """Generate and download the account's IAM credential report. Report
    generation is asynchronous on AWS's side; poll briefly for it to be
    ready rather than assuming the first response is complete."""
    import time

    for _ in range(max_attempts):
        state = iam.generate_credential_report().get("State")
        if state == "COMPLETE":
            break
        time.sleep(1)
    return iam.get_credential_report()["Content"].decode("utf-8")


def collect_all(regions: list[str], session: boto3.Session | None = None) -> CollectionResult:
    """Build real boto3 clients and run every collector across every
    requested region, degrading gracefully (a warning, not a crash) if any
    single call fails, for example a region with no deployment or a missing
    permission."""
    session = session or boto3.Session()
    result = CollectionResult()

    for region in regions:
        ec2 = session.client("ec2", region_name=region)
        cw = session.client("cloudwatch", region_name=region)
        rds = session.client("rds", region_name=region)

        for name, fn in (
            ("EC2", lambda: collect_ec2(ec2, cw, region)),
            ("EBS", lambda: collect_ebs(ec2, region)),
            ("RDS", lambda: collect_rds(rds, cw, region)),
        ):
            try:
                result.resources.extend(fn())
            except (ClientError, BotoCoreError) as exc:
                result.warnings.append(f"{name} in {region}: {exc}")

    try:
        s3 = session.client("s3")
        cw_global = session.client("cloudwatch", region_name="us-east-1")
        result.resources.extend(collect_s3(s3, cw_global))
    except (ClientError, BotoCoreError) as exc:
        result.warnings.append(f"S3: {exc}")

    try:
        iam = session.client("iam")
        result.iam_users = parse_credential_report(fetch_credential_report(iam))
    except (ClientError, BotoCoreError) as exc:
        result.warnings.append(f"IAM credential report: {exc}")

    return result
