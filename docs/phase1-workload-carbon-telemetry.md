# Phase 1 Design — Carbon-Aware Workload Telemetry

> Status: proposed design, not yet implemented.
> Author: drafted with Kiro, grounded in the current engine code.
> Audience: you (founder) + any future contributor.

## 1. Why this phase exists

GreenPilot's assessment engine today answers one question: *"How much
does my AWS account cost and emit, right now, as a snapshot?"*

Phase 1 adds a second question the current engine structurally cannot
answer: *"How do the cost and carbon of a specific workload change over
time, and when/where is it cheapest and greenest to run?"*

That second question is the seed of the whole roadmap:

- **Phase 2 (routing)** needs a time-and-region carbon signal to decide
  *when/where* to run a job. Phase 1 produces that signal.
- **Phase 3 (marketplace)** needs a per-workload, auditable carbon record
  so carbon can be a *term in a deal* between agents. Phase 1 produces
  that record.

Without Phase 1, the later phases have no data to stand on. This is the
data flywheel's first turn.

## 2. The exact limitation we are removing

From `docs/carbon-methodology.md` (the repo's own words):

> annual-average grid intensity, which ignores hour-to-hour and seasonal
> variation

And in code, `src/greenpilot/rules/carbon.py`:

```python
HOURS_PER_MONTH_ALWAYS_ON = 730.0            # flat, no time dimension

REGION_GRID_INTENSITY_G_PER_KWH = {          # one number per region, per year
    "eu-west-1": 316,
    ...
}

def _region_intensity(region: str) -> float:
    return REGION_GRID_INTENSITY_G_PER_KWH.get(region, DEFAULT_GRID_INTENSITY_G_PER_KWH)
```

Because grid intensity here is a single scalar per region, the engine can
never say "running at 02:00 in eu-west-1 emits less than at 19:00." The
published research this product is chasing says that intra-day swing is
large (reported figures of 5.5x variation across grids/hours, and 30-56%
carbon cuts from time/region shifting). Removing this scalar assumption is
the core technical work of Phase 1.

## 3. Design principles (keep the engine's existing virtues)

The current code has three properties worth preserving exactly:

1. **Demo mode needs no AWS account, no network, no credentials.** Phase 1
   must keep a fully offline path that runs against committed sample data.
2. **Sample and live paths run identical rules.** New time-series logic
   must sit behind the same `analyze_resources(...)`-style core.
3. **Honest about approximation.** Every new estimate carries the same
   "indicative only, not CSRD-grade" caveat the current `CarbonEstimate`
   does.

Phase 1 is **additive**. It does not change or break the existing
snapshot report. All current tests must still pass unchanged.

## 4. New concepts (data model)

Add to `src/greenpilot/models.py`, alongside (not replacing) `Resource`:

### 4.1 `Workload`
A unit of work that runs over time. This is the new first-class object the
marketplace will eventually trade. It is deliberately *not* an AWS resource
— a workload may map to one resource, many, or (later) to an AI agent.

```python
@dataclass
class Workload:
    workload_id: str
    name: str
    kind: Literal["service", "batch", "inference", "training", "agent"]
    region: str
    resource_ids: list[str] = field(default_factory=list)  # links to Resource
    # scheduling freedom — the lever Phase 2 will pull:
    deferrable: bool = False          # can it be time-shifted?
    movable: bool = False             # can it be region-shifted?
    deadline_hours: Optional[float] = None
    tags: dict[str, str] = field(default_factory=dict)
```

### 4.2 `GridIntensityPoint` and a time-series lookup
Replace the single-scalar region lookup with a time-indexed one. Start
simple: hourly buckets for a representative day, per region.

```python
@dataclass
class GridIntensityPoint:
    region: str
    hour_of_day: int          # 0-23, local grid time
    g_co2e_per_kwh: float
```

A `GridIntensitySeries` wraps a list of these and answers
`intensity(region, hour)` with a sane fallback to the existing
annual-average scalar when no hourly data exists. That fallback is what
keeps the old snapshot path working byte-for-byte.

### 4.3 `WorkloadCarbonSample` (the telemetry record — the dataset)
One append-only row per measurement window. This is literally the data the
flywheel accumulates.

```python
@dataclass
class WorkloadCarbonSample:
    workload_id: str
    window_start: datetime
    window_end: datetime
    region: str
    kwh: float
    g_co2e_per_kwh: float     # the time-and-region intensity actually used
    co2e_kg: float
    monthly_cost_eur: float
```

## 5. New carbon math (extend, do not rewrite)

`rules/carbon.py` keeps every existing function working. We add
time-aware variants next to them:

```python
def resource_kwh_for_window(r: Resource, hours: float) -> float:
    """Same power model as resource_kwh_per_month, but for an arbitrary
    window length instead of a flat month."""

def workload_co2e_kg_for_window(
    workload: Workload,
    resources: dict[str, Resource],
    series: GridIntensitySeries,
    window_start: datetime,
    window_end: datetime,
) -> WorkloadCarbonSample:
    """Walk the window hour by hour, multiply each hour's kWh by THAT
    hour's grid intensity, sum. This is the function that finally sees the
    intra-day swing."""
```

Key point: `estimate_current_co2e_tonnes_per_year` and
`build_carbon_estimate` are untouched. The new functions are a parallel,
opt-in path.

## 6. Storage (the dataset shape)

Start with the simplest thing that is still real: **append-only storage**,
no database engine, matching the repo's existing "plain files, no
infra" ethos.

- `greenpilot telemetry record ...` appends `WorkloadCarbonSample` rows to
  a local file (CSV first; SQLite is a drop-in upgrade later).
- Append-only matters: it is the audit trail Phase 3's CSRD/marketplace
  record is built from. Never mutate a past sample.

Sample data to commit for the offline demo:

- `sample_data/workloads.json` — a few `Workload` records that reference
  existing `resource_inventory.json` IDs.
- `sample_data/grid_intensity_hourly.csv` — 24 rows x a few EU regions,
  illustrative hourly curve (night cheaper/greener, evening peak dirtier).
  Clearly flagged illustrative, same honesty as the current tables.

## 7. New CLI surface

Keep the existing `analyze` command exactly as-is. Add a sibling group:

```
greenpilot telemetry record --workloads sample_data/workloads.json \
    --grid sample_data/grid_intensity_hourly.csv \
    --window-start 2026-01-01T00:00 --window-end 2026-01-02T00:00 \
    --out telemetry.csv

greenpilot telemetry greenest-window --workload batch-nightly \
    --grid sample_data/grid_intensity_hourly.csv
    # -> prints the hour range with the lowest gCO2e for a deferrable job.
       This is the first visible taste of Phase 2 routing.
```

## 8. What this unlocks, concretely

- A chart of one workload's carbon across 24 hours (the first thing to
  show a pilot customer or investor that GreenPilot sees *time*, not just
  a snapshot).
- A "greenest window" recommendation for any `deferrable` workload — a
  real, provable number, not a slide.
- An append-only per-workload record — the exact artifact Phase 3 needs to
  make carbon a term in an agent-to-agent deal.

## 9. Explicit non-goals for Phase 1

- No live grid-intensity API yet (ElectricityMaps/WattTime). Hourly sample
  curve first; swap in a real feed in Phase 2.
- No automated action / routing execution. Phase 1 only *measures and
  recommends*. This preserves the product's "we only read, you approve"
  guarantee.
- No multi-tenant anything. One account, local files.
- No ML scoring. Still rule/arithmetic based, as the README promises.

## 10. Suggested build order (small, test-first PRs)

1. Add `Workload`, `GridIntensityPoint`, `GridIntensitySeries`,
   `WorkloadCarbonSample` to `models.py` + unit tests. No behavior change.
2. Add `resource_kwh_for_window` + `workload_co2e_kg_for_window` to
   `carbon.py` + tests that assert the intra-day swing actually moves the
   number. Existing `test_carbon.py` stays green.
3. Add sample `workloads.json` + `grid_intensity_hourly.csv`.
4. Add `telemetry record` CLI writing append-only CSV + an end-to-end test.
5. Add `telemetry greenest-window` CLI + test (the Phase 2 teaser).

Each step is independently reviewable and leaves the engine shippable.
```
