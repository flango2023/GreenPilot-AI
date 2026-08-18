# Carbon Methodology

This documents the formula implemented in [`src/greenpilot/rules/carbon.py`](../src/greenpilot/rules/carbon.py), matching the methodology published on the live product at [greenpilotai.com/carbon-methodology.html](https://greenpilotai.com/carbon-methodology.html).

## Formula

```
Estimated CO2e = Resource Usage (kWh equivalent) × Regional Grid Intensity (gCO2e/kWh)
```

Applied per resource, then summed across the account and annualized.

## Inputs

**Usage factors** (from resource configuration, not real metering):
- EC2/RDS: instance family → an approximate average power draw in watts, × hours running per month. RDS Multi-AZ doubles the draw (a standby replica draws roughly the same power as the primary).
- EBS/S3: storage volume (GB) → a small constant watts-per-TB figure, assumed always-on for the month.

**Environmental factor:**
- Annual-average regional electricity grid carbon intensity (gCO2e/kWh), looked up per AWS region.

## Data sources (for the real product; illustrative figures here)

- IEA World Energy Outlook — country-level baseline data
- EMBER European Electricity Review — EU-specific grid intensity
- European Environment Agency — generation composition data
- AWS instance type specifications — used as energy-consumption proxies

## Why this is an approximation, not a measurement

AWS does not expose per-workload metered power draw, so this — like the live product during its pilot phase — relies on:

- Instance-family power figures as proxies for actual consumption
- Annual-average grid intensity, ignoring hour-to-hour and seasonal variation
- Published infrastructure efficiency averages rather than AWS's actual (largely undisclosed) datacenter PUE
- No credit for AWS's own renewable energy procurement (excluded during the pilot phase, same as the live methodology)

**These estimates are indicative only.** They are useful for prioritizing optimization work and having an order-of-magnitude conversation about cloud emissions — they are **not** suitable for regulatory or CSRD compliance reporting without independent verification.

## The numbers this repo actually uses

See the top of [`carbon.py`](../src/greenpilot/rules/carbon.py) for the exact tables:

- `INSTANCE_FAMILY_AVG_WATTS` — a handful of coarse buckets (t3/m5/c5/r5 families and their `db.*` RDS equivalents), not a full per-instance-type lookup.
- `STORAGE_WATTS_PER_TB` — one constant for always-on block/object storage.
- `REGION_GRID_INTENSITY_G_PER_KWH` — a small table covering the EU regions used in `sample_data/`, plus `us-east-1` and `us-west-2`, with a conservative default for anything else.

Anyone extending this for a real account should swap these tables for a proper emissions-factor dataset (e.g. the [Cloud Carbon Footprint](https://www.cloudcarbonfootprint.org/) coefficients) before relying on the output for anything beyond a demo.
