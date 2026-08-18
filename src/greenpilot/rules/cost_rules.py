"""Cost-waste detection rules.

Each rule maps directly to one of the waste categories GreenPilot AI
advertises on https://greenpilotai.com/platform.html: idle/underutilized
EC2, unattached EBS volumes, oversized/redundant RDS, misclassified S3
storage tiers, and schedulable (business-hours-only) workloads.

Every rule is a pure function: `list[Resource] -> list[Finding]`. The
engine (see engine.py) just calls all of them and merges the results, so
adding a new rule never requires touching anything else.
"""

from __future__ import annotations

from ..models import Finding, Resource

# Thresholds are deliberately simple and documented. This is a rule-based
# v1 engine, matching the live product's current architecture; ML-based
# scoring is explicitly a roadmap item, not something to fake here.
IDLE_CPU_THRESHOLD_PCT = 5.0
UNDERUTILIZED_CPU_THRESHOLD_PCT = 20.0
IDLE_TERMINATION_SAVINGS_RATIO = 0.70  # assumes downsizing to a small instance
UNDERUTILIZED_DOWNSIZE_SAVINGS_RATIO = 0.40

REDUNDANT_RDS_SAVINGS_RATIO = 0.50

S3_TIER_SAVINGS_RATIO = {
    "infrequent": 0.40,  # STANDARD -> STANDARD_IA
    "rare": 0.70,  # STANDARD -> GLACIER
}

HOURS_PER_MONTH_ALWAYS_ON = 730.0
HOURS_PER_MONTH_BUSINESS_ONLY = 260.0  # ~12h/day, 5 days/week


def rule_idle_or_underutilized_ec2(resources: list[Resource]) -> list[Finding]:
    findings = []
    for r in resources:
        if r.service != "EC2" or r.avg_cpu_utilization_pct is None:
            continue
        if r.avg_cpu_utilization_pct < IDLE_CPU_THRESHOLD_PCT:
            savings = round(r.monthly_cost * IDLE_TERMINATION_SAVINGS_RATIO, 2)
            findings.append(
                Finding(
                    resource_id=r.resource_id,
                    service="EC2",
                    category="cost",
                    title=f"Idle EC2 instance ({r.resource_type})",
                    description=(
                        f"Average CPU utilization is {r.avg_cpu_utilization_pct:.1f}%, "
                        "below the idle threshold. Likely safe to stop or terminate."
                    ),
                    monthly_savings=savings,
                    optimized_monthly_cost=round(r.monthly_cost - savings, 2),
                    effort="low",
                    rollback="Instance can be re-launched from its AMI/snapshot if needed.",
                )
            )
        elif r.avg_cpu_utilization_pct < UNDERUTILIZED_CPU_THRESHOLD_PCT:
            savings = round(r.monthly_cost * UNDERUTILIZED_DOWNSIZE_SAVINGS_RATIO, 2)
            findings.append(
                Finding(
                    resource_id=r.resource_id,
                    service="EC2",
                    category="cost",
                    title=f"Underutilized/oversized EC2 instance ({r.resource_type})",
                    description=(
                        f"Average CPU utilization is {r.avg_cpu_utilization_pct:.1f}%. "
                        "Instance class is likely larger than the workload needs."
                    ),
                    monthly_savings=savings,
                    optimized_monthly_cost=round(r.monthly_cost - savings, 2),
                    effort="medium",
                    rollback="Resize back up in one change if performance regresses.",
                )
            )
    return findings


def rule_unattached_ebs(resources: list[Resource]) -> list[Finding]:
    findings = []
    for r in resources:
        if r.service != "EBS" or r.attached is not False:
            continue
        findings.append(
            Finding(
                resource_id=r.resource_id,
                service="EBS",
                category="cost",
                title=f"Unattached EBS volume ({r.storage_gb:.0f} GB)"
                if r.storage_gb
                else "Unattached EBS volume",
                description="Volume is not attached to any running instance.",
                monthly_savings=round(r.monthly_cost, 2),
                optimized_monthly_cost=0.0,
                effort="low",
                rollback="Snapshot before deletion to allow full recovery.",
            )
        )
    return findings


def rule_redundant_rds(resources: list[Resource]) -> list[Finding]:
    findings = []
    for r in resources:
        if r.service != "RDS" or not r.is_redundant_replica:
            continue
        savings = round(r.monthly_cost * REDUNDANT_RDS_SAVINGS_RATIO, 2)
        findings.append(
            Finding(
                resource_id=r.resource_id,
                service="RDS",
                category="cost",
                title=f"Redundantly configured RDS instance ({r.resource_type})",
                description=(
                    "Configuration overlaps with another instance serving the same "
                    "workload (e.g. an unused read replica or duplicated Multi-AZ)."
                ),
                monthly_savings=savings,
                optimized_monthly_cost=round(r.monthly_cost - savings, 2),
                effort="medium",
                rollback="Re-provision the replica from a snapshot if load increases.",
            )
        )
    return findings


def rule_misclassified_s3(resources: list[Resource]) -> list[Finding]:
    findings = []
    for r in resources:
        if r.service != "S3" or r.storage_class != "STANDARD":
            continue
        ratio = S3_TIER_SAVINGS_RATIO.get(r.access_frequency or "", 0.0)
        if ratio <= 0:
            continue
        savings = round(r.monthly_cost * ratio, 2)
        target_tier = "STANDARD_IA" if r.access_frequency == "infrequent" else "GLACIER"
        findings.append(
            Finding(
                resource_id=r.resource_id,
                service="S3",
                category="cost",
                title="Misclassified S3 storage tier",
                description=(
                    f"Bucket has '{r.access_frequency}' access patterns but is stored "
                    f"in STANDARD. Moving to {target_tier} matches access to cost."
                ),
                monthly_savings=savings,
                optimized_monthly_cost=round(r.monthly_cost - savings, 2),
                effort="low",
                rollback="Lifecycle transitions are reversible by changing the storage class back.",
            )
        )
    return findings


def rule_schedulable_ec2(resources: list[Resource]) -> list[Finding]:
    findings = []
    for r in resources:
        if r.service != "EC2" or not r.schedulable:
            continue
        hours = r.hours_running_per_month or HOURS_PER_MONTH_ALWAYS_ON
        if hours <= 0:
            continue  # nothing running, nothing to schedule/save
        ratio = max(0.0, (hours - HOURS_PER_MONTH_BUSINESS_ONLY) / hours)
        savings = round(r.monthly_cost * ratio, 2)
        findings.append(
            Finding(
                resource_id=r.resource_id,
                service="EC2",
                category="cost",
                title=f"Schedulable workload running 24/7 ({r.resource_type})",
                description=(
                    "Tagged as a non-production workload but running continuously. "
                    "A start/stop schedule matching business hours removes most of the cost."
                ),
                monthly_savings=savings,
                optimized_monthly_cost=round(r.monthly_cost - savings, 2),
                effort="low",
                rollback="Schedule can be paused instantly to return to always-on.",
            )
        )
    return findings


ALL_COST_RULES = [
    rule_idle_or_underutilized_ec2,
    rule_unattached_ebs,
    rule_redundant_rds,
    rule_misclassified_s3,
    rule_schedulable_ec2,
]
