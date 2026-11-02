"""Core data model shared by every rule module, the engine, and the renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal, Optional

WorkloadKind = Literal["service", "batch", "inference", "training", "agent"]

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


# ---------------------------------------------------------------------------
# Phase 1: carbon-aware workload telemetry (additive, see
# docs/phase1-workload-carbon-telemetry.md). None of the types below change
# the existing snapshot report; they add a time dimension and a per-workload
# view that the routing (Phase 2) and marketplace (Phase 3) work build on.
# ---------------------------------------------------------------------------


@dataclass
class Workload:
    """A unit of work that runs over time.

    Deliberately NOT an AWS ``Resource``: a workload may map to one resource,
    several, or (later) to an AI agent. ``deferrable``/``movable`` are the
    scheduling levers Phase 2's carbon-aware routing will pull.
    """

    workload_id: str
    name: str
    kind: WorkloadKind
    region: str
    resource_ids: list[str] = field(default_factory=list)
    deferrable: bool = False  # can it be time-shifted within its deadline?
    movable: bool = False  # can it be run in a different region?
    deadline_hours: Optional[float] = None
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class GridIntensityPoint:
    """Grid carbon intensity for one region in one hour-of-day bucket.

    ``hour_of_day`` is 0-23 in the grid's local time. This is the single
    change that lets the engine see the intra-day swing the annual-average
    ``REGION_GRID_INTENSITY_G_PER_KWH`` table in carbon.py cannot.
    """

    region: str
    hour_of_day: int
    g_co2e_per_kwh: float

    def __post_init__(self) -> None:
        if not 0 <= self.hour_of_day <= 23:
            raise ValueError(
                f"hour_of_day must be 0-23, got {self.hour_of_day} "
                f"for region {self.region!r}"
            )
        if self.g_co2e_per_kwh < 0:
            raise ValueError(
                f"g_co2e_per_kwh must be non-negative, got "
                f"{self.g_co2e_per_kwh} for region {self.region!r}"
            )


@dataclass
class GridIntensitySeries:
    """A lookup of hourly grid intensity, with a safe fallback.

    When no hourly point exists for a (region, hour), ``intensity`` falls
    back to ``annual_average_by_region`` and finally to ``default``. That
    fallback is what keeps the existing snapshot path producing identical
    numbers when no hourly data is supplied.
    """

    points: list[GridIntensityPoint] = field(default_factory=list)
    annual_average_by_region: dict[str, float] = field(default_factory=dict)
    default: float = 400.0

    def __post_init__(self) -> None:
        # Index (region, hour) -> gCO2e/kWh for O(1) lookups. Later points
        # for the same key win, which makes overriding a curve predictable.
        self._index: dict[tuple[str, int], float] = {}
        for p in self.points:
            self._index[(p.region, p.hour_of_day)] = p.g_co2e_per_kwh

    def intensity(self, region: str, hour_of_day: int) -> float:
        """gCO2e/kWh for a region at a given hour, with graceful fallback."""
        hourly = self._index.get((region, hour_of_day))
        if hourly is not None:
            return hourly
        return self.annual_average_by_region.get(region, self.default)


@dataclass
class WorkloadCarbonSample:
    """One append-only telemetry row: the carbon of a workload over a window.

    This is the record the data flywheel accumulates. It is meant to be
    written once and never mutated, so a sequence of samples forms the audit
    trail Phase 3's CSRD/marketplace record is built on.
    """

    workload_id: str
    window_start: datetime
    window_end: datetime
    region: str
    kwh: float
    g_co2e_per_kwh: float  # effective (window-averaged) intensity used
    co2e_kg: float
    monthly_cost_eur: float
