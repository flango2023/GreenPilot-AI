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

from ..models import CarbonEstimate, Finding, Resource

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
