"""Carbon estimation. Implements the formula published at
https://greenpilotai.com/carbon-methodology.html:

    Estimated CO2e = Resource Usage (kWh equivalent) x Regional Grid Intensity (gCO2e/kWh)

Like the live methodology page, this is explicitly an illustrative model.
AWS doesn't expose metered per-resource power draw, so instance-type power
figures and annual-average regional grid intensities are used as proxies,
the same simplifying assumptions the live site documents. Do not use these
numbers for regulatory or CSRD reporting. See docs/carbon-methodology.md
for the full write-up and sources (IEA World Energy Outlook, EMBER European
Electricity Review, European Environment Agency).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..models import (
    CarbonEstimate,
    Finding,
    GridIntensitySeries,
    Resource,
    Workload,
    WorkloadCarbonSample,
)

HOURS_PER_MONTH_ALWAYS_ON = 730.0

# Rough average power draw per EC2/RDS instance family, in watts. Deliberately
# coarse: a handful of buckets, not a per-instance-type lookup table.
INSTANCE_FAMILY_AVG_WATTS: dict[str, float] = {
    "t3": 15.0,
    "t3a": 15.0,
    "m5": 35.0,
    "m6i": 33.0,
    "c5": 40.0,
    "c6i": 38.0,
    "r5": 45.0,
    "r6i": 42.0,
    "db.t3": 15.0,
    "db.m5": 35.0,
    "db.r5": 45.0,
}
DEFAULT_INSTANCE_WATTS = 30.0

# Illustrative watts drawn per TB of always-on block/object storage.
STORAGE_WATTS_PER_TB = 1.2

# Illustrative annual-average grid carbon intensity by AWS region, gCO2e/kWh.
# Ballpark figures only, in the spirit of IEA/EMBER/EEA public reporting.
# See docs/carbon-methodology.md for the caveat.
REGION_GRID_INTENSITY_G_PER_KWH: dict[str, float] = {
    "eu-west-1": 316,  # Ireland
    "eu-west-2": 231,  # London
    "eu-west-3": 58,  # Paris, nuclear-heavy grid
    "eu-central-1": 380,  # Frankfurt
    "eu-north-1": 21,  # Stockholm, hydro/nuclear
    "us-east-1": 367,  # N. Virginia
    "us-west-2": 92,  # Oregon
}
DEFAULT_GRID_INTENSITY_G_PER_KWH = 400.0


def _instance_power_watts(resource_type: str) -> float:
    family = resource_type.split(".")[0] if "." in resource_type else resource_type
    return INSTANCE_FAMILY_AVG_WATTS.get(family, DEFAULT_INSTANCE_WATTS)


def _region_intensity(region: str) -> float:
    return REGION_GRID_INTENSITY_G_PER_KWH.get(region, DEFAULT_GRID_INTENSITY_G_PER_KWH)


def resource_kwh_per_month(r: Resource) -> float:
    """Resource Usage in kWh-equivalent for one month."""
    if r.service in ("EC2", "RDS"):
        watts = _instance_power_watts(r.resource_type)
        if r.service == "RDS" and r.multi_az:
            watts *= 2  # standby replica draws roughly the same power
        hours = (
            r.hours_running_per_month
            if r.hours_running_per_month is not None
            else HOURS_PER_MONTH_ALWAYS_ON
        )
        return (watts * hours) / 1000.0
    if r.service in ("EBS", "S3"):
        tb = (r.storage_gb or 0.0) / 1000.0
        return (tb * STORAGE_WATTS_PER_TB * HOURS_PER_MONTH_ALWAYS_ON) / 1000.0
    return 0.0


def resource_co2e_kg_per_month(r: Resource) -> float:
    """Estimated CO2e = kWh x regional grid intensity, converted to kg."""
    kwh = resource_kwh_per_month(r)
    grams = kwh * _region_intensity(r.region)
    return grams / 1000.0


def estimate_current_co2e_tonnes_per_year(resources: list[Resource]) -> float:
    kg_per_month_total = sum(resource_co2e_kg_per_month(r) for r in resources)
    return round((kg_per_month_total * 12) / 1000.0, 2)


def estimate_reduction_potential_tonnes_per_year(
    resources: list[Resource], findings: list[Finding]
) -> float:
    """Assumes carbon scales with the cost-savings ratio per flagged
    resource. That's a reasonable proxy, since removing, downsizing, or
    rescheduling compute reduces energy draw roughly in proportion to the
    compute (and therefore cost) it removes."""
    resource_by_id = {r.resource_id: r for r in resources}
    reduction_kg_per_month = 0.0
    for f in findings:
        if f.category != "cost":
            continue
        r = resource_by_id.get(f.resource_id)
        if r is None or r.monthly_cost <= 0:
            continue
        savings_ratio = min(f.monthly_savings / r.monthly_cost, 1.0)
        reduction_kg_per_month += resource_co2e_kg_per_month(r) * savings_ratio
    return round((reduction_kg_per_month * 12) / 1000.0, 2)


def build_carbon_estimate(
    resources: list[Resource], findings: list[Finding]
) -> CarbonEstimate:
    return CarbonEstimate(
        current_tonnes_co2e_per_year=estimate_current_co2e_tonnes_per_year(resources),
        reduction_tonnes_co2e_per_year=estimate_reduction_potential_tonnes_per_year(
            resources, findings
        ),
    )


# ---------------------------------------------------------------------------
# Phase 1: time-aware carbon math (additive). Everything above is unchanged;
# the functions below reuse the SAME power model (_instance_power_watts, the
# RDS multi-AZ doubling, STORAGE_WATTS_PER_TB) but compute energy over an
# arbitrary window and multiply each hour by THAT hour's grid intensity from
# a GridIntensitySeries, instead of a single annual-average scalar.
# See docs/phase1-workload-carbon-telemetry.md.
# ---------------------------------------------------------------------------


def _resource_power_watts(r: Resource) -> float:
    """Average power draw of a resource in watts, using the same assumptions
    as resource_kwh_per_month (instance family lookup, RDS multi-AZ doubling,
    storage watts-per-TB). Returns 0 for services with no modeled draw."""
    if r.service in ("EC2", "RDS"):
        watts = _instance_power_watts(r.resource_type)
        if r.service == "RDS" and r.multi_az:
            watts *= 2
        return watts
    if r.service in ("EBS", "S3"):
        tb = (r.storage_gb or 0.0) / 1000.0
        return tb * STORAGE_WATTS_PER_TB
    return 0.0


def resource_kwh_for_window(r: Resource, hours: float) -> float:
    """kWh-equivalent for a resource over an arbitrary number of hours.

    This is the window-scoped sibling of resource_kwh_per_month: the latter
    is exactly this with hours = the resource's monthly running hours (or
    HOURS_PER_MONTH_ALWAYS_ON for storage)."""
    if hours < 0:
        raise ValueError(f"hours must be non-negative, got {hours}")
    return (_resource_power_watts(r) * hours) / 1000.0


def _iter_hours(window_start: datetime, window_end: datetime):
    """Yield (hour_of_day, fraction_of_that_hour_in_window) across a window.

    Handles partial first/last hours so a 90-minute window is split as
    1.0 h + 0.5 h rather than rounded. Grid intensity is looked up per
    hour_of_day, so this is what lets a window straddle a dirty-to-clean
    transition and get a blended result."""
    if window_end < window_start:
        raise ValueError("window_end must not be before window_start")
    cursor = window_start
    while cursor < window_end:
        next_hour_boundary = (cursor.replace(minute=0, second=0, microsecond=0)
                              + timedelta(hours=1))
        slice_end = min(next_hour_boundary, window_end)
        fraction = (slice_end - cursor).total_seconds() / 3600.0
        yield cursor.hour, fraction
        cursor = slice_end


def workload_co2e_kg_for_window(
    workload: Workload,
    resources: dict[str, Resource],
    series: GridIntensitySeries,
    window_start: datetime,
    window_end: datetime,
) -> WorkloadCarbonSample:
    """Carbon of one workload over a window, hour by hour.

    For each resource the workload maps to, energy is spread evenly across
    the window and each hour's slice is multiplied by that hour's grid
    intensity for the workload's region. The returned sample reports total
    kWh, total CO2e, and the effective (energy-weighted) intensity actually
    used, so a later audit can see the blended figure, not just an average.
    """
    total_hours = (window_end - window_start).total_seconds() / 3600.0
    if total_hours < 0:
        raise ValueError("window_end must not be before window_start")

    total_kwh = 0.0
    total_grams = 0.0
    for rid in workload.resource_ids:
        r = resources.get(rid)
        if r is None:
            continue
        kwh_full_window = resource_kwh_for_window(r, total_hours)
        if total_hours == 0:
            continue
        kwh_per_hour = kwh_full_window / total_hours
        for hour_of_day, fraction in _iter_hours(window_start, window_end):
            slice_kwh = kwh_per_hour * fraction
            intensity = series.intensity(workload.region, hour_of_day)
            total_kwh += slice_kwh
            total_grams += slice_kwh * intensity

    effective_intensity = (total_grams / total_kwh) if total_kwh > 0 else 0.0

    monthly_cost = sum(
        resources[rid].monthly_cost
        for rid in workload.resource_ids
        if rid in resources
    )

    return WorkloadCarbonSample(
        workload_id=workload.workload_id,
        window_start=window_start,
        window_end=window_end,
        region=workload.region,
        kwh=round(total_kwh, 6),
        g_co2e_per_kwh=round(effective_intensity, 3),
        co2e_kg=round(total_grams / 1000.0, 6),
        monthly_cost_eur=round(monthly_cost, 2),
    )


def greenest_start_hour(
    region: str,
    series: GridIntensitySeries,
    duration_hours: int,
    candidate_start_hours: range = range(24),
) -> tuple[int, float]:
    """For a deferrable job of a given whole-hour duration, return the
    (start_hour, average_intensity) with the lowest average grid intensity
    over the run. This is the arithmetic core the Phase 2 routing CLI and,
    later, the marketplace's "when to run" recommendation stand on.

    Hours wrap past midnight (a 6h job can start at 22:00 and run into the
    next day). Ties resolve to the earliest start hour."""
    if duration_hours <= 0:
        raise ValueError(f"duration_hours must be positive, got {duration_hours}")

    best_hour = None
    best_avg = None
    for start in candidate_start_hours:
        hours = [(start + offset) % 24 for offset in range(duration_hours)]
        avg = sum(series.intensity(region, h) for h in hours) / duration_hours
        if best_avg is None or avg < best_avg:
            best_avg = avg
            best_hour = start
    return best_hour, round(best_avg, 3)
