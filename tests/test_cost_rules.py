from greenpilot.models import Resource
from greenpilot.rules.cost_rules import (
    rule_idle_or_underutilized_ec2,
    rule_misclassified_s3,
    rule_redundant_rds,
    rule_schedulable_ec2,
    rule_unattached_ebs,
)


def test_idle_ec2_is_flagged_with_high_savings_ratio():
    r = Resource(
        resource_id="ec2-idle",
        service="EC2",
        resource_type="m5.large",
        region="eu-west-1",
        monthly_cost=100.0,
        avg_cpu_utilization_pct=2.0,
    )
    findings = rule_idle_or_underutilized_ec2([r])
    assert len(findings) == 1
    assert findings[0].monthly_savings == 70.0
    assert "Idle" in findings[0].title


def test_underutilized_ec2_uses_lower_savings_ratio():
    r = Resource(
        resource_id="ec2-under",
        service="EC2",
        resource_type="c5.xlarge",
        region="eu-west-1",
        monthly_cost=200.0,
        avg_cpu_utilization_pct=15.0,
    )
    findings = rule_idle_or_underutilized_ec2([r])
    assert len(findings) == 1
    assert findings[0].monthly_savings == 80.0


def test_healthy_ec2_is_not_flagged():
    r = Resource(
        resource_id="ec2-healthy",
        service="EC2",
        resource_type="m5.large",
        region="eu-west-1",
        monthly_cost=100.0,
        avg_cpu_utilization_pct=55.0,
    )
    assert rule_idle_or_underutilized_ec2([r]) == []


def test_unattached_ebs_recovers_full_cost():
    r = Resource(
        resource_id="ebs-orphan",
        service="EBS",
        resource_type="gp3",
        region="eu-west-1",
        monthly_cost=38.0,
        attached=False,
        storage_gb=250,
    )
    findings = rule_unattached_ebs([r])
    assert len(findings) == 1
    assert findings[0].monthly_savings == 38.0
    assert findings[0].optimized_monthly_cost == 0.0


def test_attached_ebs_is_not_flagged():
    r = Resource(
        resource_id="ebs-inuse",
        service="EBS",
        resource_type="gp3",
        region="eu-west-1",
        monthly_cost=12.0,
        attached=True,
        storage_gb=100,
    )
    assert rule_unattached_ebs([r]) == []


def test_redundant_rds_is_flagged():
    r = Resource(
        resource_id="rds-replica",
        service="RDS",
        resource_type="db.m5.large",
        region="eu-west-1",
        monthly_cost=310.0,
        is_redundant_replica=True,
    )
    findings = rule_redundant_rds([r])
    assert len(findings) == 1
    assert findings[0].monthly_savings == 155.0


def test_misclassified_s3_rare_access_targets_glacier():
    r = Resource(
        resource_id="s3-archive",
        service="S3",
        resource_type="STANDARD bucket",
        region="eu-west-1",
        monthly_cost=95.0,
        storage_class="STANDARD",
        access_frequency="rare",
        storage_gb=3000,
    )
    findings = rule_misclassified_s3([r])
    assert len(findings) == 1
    assert findings[0].monthly_savings == 66.5
    assert "GLACIER" in findings[0].description


def test_frequently_accessed_s3_is_not_flagged():
    r = Resource(
        resource_id="s3-active",
        service="S3",
        resource_type="STANDARD bucket",
        region="eu-west-1",
        monthly_cost=140.0,
        storage_class="STANDARD",
        access_frequency="frequent",
        storage_gb=500,
    )
    assert rule_misclassified_s3([r]) == []


def test_schedulable_ec2_with_negative_hours_is_skipped_not_miscalculated():
    # rule_schedulable_ec2 is a pure function callable directly by anyone,
    # not just through engine.load_resources (which separately rejects
    # negative hours before rules ever run). Called standalone with bad
    # data, it must not turn a negative denominator into a wildly inflated
    # bogus savings figure -- it should just skip the resource.
    r = Resource(
        resource_id="ec2-bad-data",
        service="EC2",
        resource_type="t3.large",
        region="eu-west-1",
        monthly_cost=180.0,
        hours_running_per_month=-5,
        schedulable=True,
    )
    assert rule_schedulable_ec2([r]) == []


def test_schedulable_ec2_savings_matches_business_hours_ratio():
    r = Resource(
        resource_id="ec2-dev",
        service="EC2",
        resource_type="t3.large",
        region="eu-west-1",
        monthly_cost=180.0,
        hours_running_per_month=730,
        schedulable=True,
    )
    findings = rule_schedulable_ec2([r])
    assert len(findings) == 1
    expected_ratio = (730 - 260) / 730
    assert findings[0].monthly_savings == round(180.0 * expected_ratio, 2)
