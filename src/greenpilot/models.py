"""Core data model shared by every rule module, the engine, and the renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

Service = Literal["EC2", "RDS", "EBS", "S3", "ACCOUNT"]
Effort = Literal["low", "medium", "high"]
Category = Literal["cost", "carbon", "governance"]
Regulation = Literal["GDPR", "NIS2", "CSRD"]


@dataclass
class Resource:
    """A single AWS resource plus the usage/config attributes the rules need.

    This mirrors what a real GreenPilot collector would read from a
    read-only AWS API call (Cost Explorer + describe-instances/volumes/
    db-instances/buckets), flattened here into one record per resource so
    sample data stays easy to read and edit.
    """

    resource_id: str
    service: Service
    resource_type: str
    region: str
    monthly_cost: float
    tags: dict[str, str] = field(default_factory=dict)

    # EC2-specific
    avg_cpu_utilization_pct: Optional[float] = None
    hours_running_per_month: Optional[float] = None
    schedulable: bool = False

    # EBS-specific
    attached: Optional[bool] = None
    storage_gb: Optional[float] = None

    # RDS-specific
    multi_az: Optional[bool] = None
    is_redundant_replica: Optional[bool] = None

    # S3-specific
    storage_class: Optional[str] = None
    access_frequency: Optional[str] = None  # "frequent" | "infrequent" | "rare"
    versioning_enabled: Optional[bool] = None

    # Governance-relevant flags
    publicly_accessible: Optional[bool] = None
    encrypted: Optional[bool] = None
    contains_personal_data: Optional[bool] = None


@dataclass
class IamUser:
    """One row of an AWS IAM credential report (`iam:GetCredentialReport`),
    parsed down to the fields the NIS2 credential-hygiene rule needs.

    Field names deliberately mirror the credential report's own column
    names (see credential_report.py) rather than being renamed, so the
    mapping from raw AWS output stays traceable.
    """

    user: str
    is_root: bool
    mfa_active: bool
    has_console_access: bool
    days_since_password_used: Optional[int] = None
    key1_active: bool = False
    key1_age_days: Optional[int] = None
    key2_active: bool = False
    key2_age_days: Optional[int] = None


@dataclass
class Finding:
    """One flagged issue: a waste finding, a carbon note, or a governance note."""

    resource_id: str
    service: Service
    category: Category
    title: str
    description: str
    monthly_savings: float = 0.0
    optimized_monthly_cost: Optional[float] = None
    effort: Effort = "low"
    rollback: Optional[str] = None
    regulation: Optional[Regulation] = None


@dataclass
class CarbonEstimate:
    current_tonnes_co2e_per_year: float
    reduction_tonnes_co2e_per_year: float
    methodology_note: str = (
        "Indicative only: instance specs and annual grid averages are used "
        "as proxies for metered energy use. See docs/carbon-methodology.md."
    )


@dataclass
class Report:
    company_name: str
    generated_on: date
    resources_analyzed: int
    findings: list[Finding]
    carbon: CarbonEstimate

    @property
    def cost_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.category == "cost"]

    @property
    def governance_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.category == "governance"]

    @property
    def monthly_savings_total(self) -> float:
        return round(sum(f.monthly_savings for f in self.cost_findings), 2)

    @property
    def annual_savings_total(self) -> float:
        return round(self.monthly_savings_total * 12, 2)

    @property
    def action_plan(self) -> list[Finding]:
        """Cost findings ranked by savings desc, then effort asc. Mirrors the
        live product's "ranked by savings potential and effort" description."""
        effort_rank = {"low": 0, "medium": 1, "high": 2}
        return sorted(
            self.cost_findings,
            key=lambda f: (-f.monthly_savings, effort_rank[f.effort]),
        )
