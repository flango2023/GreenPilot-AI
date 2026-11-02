# Phase 2 Design — Carbon-Aware Routing Policy

> Status: proposed design, implementation in progress.
> Builds directly on Phase 1 (docs/phase1-workload-carbon-telemetry.md).

## 1. What changes from Phase 1

Phase 1's `greenest_start_hour` answers one question with no constraints:
*"When is this region's grid cleanest for an N-hour job?"* That is a useful
signal but it is **not a routing decision**, because it ignores everything
that makes a move safe or unsafe:

- A customer-facing API service cannot be time-shifted at all.
- A nightly ETL can slip a few hours, but not past its SLA deadline.
- A training job may also be moved to a *different region*, which can be a
  far bigger carbon win than time-shifting alone.

Phase 2 turns the raw signal into a **policy**: given a workload and its
real constraints, produce a concrete, safe recommendation ("run at 02:00 in
eu-north-1 instead of now in eu-central-1, saving X%"), or explicitly
decline to move it.

Still measure-and-recommend only. Nothing executes. "We only read, you
approve" is preserved exactly as in Phase 1.

## 2. The constraints already exist on the model

No model change is needed. `Workload` (models.py) already carries the three
levers:

```python
deferrable: bool          # may it be time-shifted?
movable: bool             # may it be run in a different region?
deadline_hours: float?    # how far can its start slip from "now"?
```

Phase 2 is the logic that *honors* these fields. The hard rule:

- `deferrable is False`  -> never change the start time.
- `movable is False`     -> never change the region.
- `deadline_hours`       -> the latest allowed start is now + deadline_hours;
  candidate start hours are clipped to that horizon. `None` on a deferrable
  workload means "no explicit deadline" -> consider the whole 24h cycle.

A workload that is neither deferrable nor movable is a no-op: the policy
returns "no safe change," by design, not by omission.

## 3. New concepts (models.py, additive)

```python
@dataclass
class RoutingCandidate:
    region: str
    start_hour: int
    avg_intensity_g_per_kwh: float   # over the run, from GridIntensitySeries

@dataclass
class RoutingRecommendation:
    workload_id: str
    baseline_region: str
    baseline_start_hour: int
    baseline_intensity: float
    chosen: RoutingCandidate         # == baseline when no safe improvement
    duration_hours: int
    moved_in_time: bool
    moved_in_region: bool
    intensity_reduction_pct: float   # 0.0 when nothing moved
    reason: str                      # human-readable why (incl. "declined")
```

`RoutingRecommendation` is deliberately explicit about *what* moved and
*why*. That audit-friendly shape is what Phase 3's marketplace needs when
carbon becomes a term in an agent-to-agent deal: the record must show the
counterfactual (what it would have emitted) and the constraint that bounded
the decision.

## 4. The policy (rules/routing.py, new module)

```python
def candidate_regions(workload, allowed_regions) -> list[str]:
    """[workload.region] if not movable, else the allowed set (incl. home)."""

def candidate_start_hours(workload, now_hour) -> range | list[int]:
    """[now_hour] if not deferrable; else now..now+deadline (mod 24),
    full 24h cycle if deferrable with no deadline."""

def recommend_route(
    workload, series, duration_hours, now_hour,
    allowed_regions=None,
) -> RoutingRecommendation:
    """Search the (region x start_hour) grid the constraints allow, score
    each with the Phase 1 average-intensity math, pick the lowest. Ties
    resolve to: same region over a move, earlier start over later, to
    minimize disruption. Returns baseline unchanged (reduction 0%) when no
    candidate beats running now at home."""
```

Scoring reuses Phase 1 exactly: the average `series.intensity(region, hour)`
over the run, the same function `greenest_start_hour` already uses. Phase 2
adds the *constraint envelope* and the *region axis* around that score; it
does not invent new carbon math.

### Why a tie-break toward "don't move"
A routing tool that reshuffles workloads for a rounding-error gain is
untrustworthy. Equal or near-equal carbon should leave the workload where
and when it already runs. We only recommend a move when it beats the
baseline by a configurable minimum margin (default: any strict improvement;
a `min_improvement_pct` guard can be added when wired to real feeds).

## 5. CLI (extends the Phase 1 `telemetry` group's sibling: `route`)

```bash
# Recommend a safe, carbon-minimizing slot for a workload.
greenpilot route recommend --workload nightly-etl --duration-hours 6 \
    --now-hour 18 --allowed-regions eu-central-1,eu-north-1

# Example output:
#   Workload: nightly-etl  (deferrable=yes, movable=no)
#   Baseline: run now 18:00 in eu-central-1  -> 452 gCO2e/kWh
#   Recommend: start 00:00 in eu-central-1   -> 243 gCO2e/kWh
#   Time-shifted within an 8h deadline. Region unchanged (not movable).
#   -> 46% lower carbon intensity. No change executed; approval required.
```

For a `movable` workload (e.g. `model-training`), the same command may
recommend eu-north-1 (hydro/nuclear, ~20 gCO2e/kWh) over eu-west-1,
a much larger cut, and the output will say the region moved.

## 6. Non-goals for Phase 2

- No execution/orchestration. Recommendation only.
- No live grid feed yet (still the Phase 1 hourly sample curve; swapping in
  ElectricityMaps/WattTime is a later, isolated change behind
  `load_grid_intensity_series`).
- No cost/latency co-optimization yet. Phase 2 minimizes carbon subject to
  the deferrable/movable/deadline constraints; cost and latency joins come
  after, and are where the published SLA-constrained routing work plugs in.
- No multi-workload / whole-fleet scheduling. One workload at a time.

## 7. Build order (test-first, each independently shippable)

1. Add `RoutingCandidate`, `RoutingRecommendation` to models.py + tests.
2. Add `rules/routing.py` with `candidate_regions`,
   `candidate_start_hours`, `recommend_route` + unit tests that prove:
   - non-deferrable workload is never time-shifted,
   - non-movable workload is never region-shifted,
   - deadline clips the search window,
   - a movable workload prefers a genuinely cleaner region.
3. Add `greenpilot route recommend` CLI + offline CLI tests on sample_data.
4. Update README Status (Phase 2 -> done).
```
