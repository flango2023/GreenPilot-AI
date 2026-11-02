"""Phase 2: carbon-aware routing policy.

Turns the Phase 1 average-intensity signal into a *constrained* recommendation.
The carbon scoring is identical to Phase 1 (average of
``GridIntensitySeries.intensity(region, hour)`` over the run); Phase 2 adds
the constraint envelope (deferrable / movable / deadline) and a region axis
around that score, plus a bias toward NOT moving when the gain is not real.

Measure-and-recommend only. Nothing here executes or changes a workload.
See docs/phase2-carbon-aware-routing.md.
"""

from __future__ import annotations

from ..models import (
    GridIntensitySeries,
    RoutingCandidate,
    RoutingRecommendation,
    Workload,
)


def _avg_intensity(
    region: str,
    start_hour: int,
    duration_hours: int,
    series: GridIntensitySeries,
) -> float:
    """Average grid intensity over a run, hours wrapping past midnight.
    Same scoring Phase 1's greenest_start_hour uses."""
    hours = [(start_hour + offset) % 24 for offset in range(duration_hours)]
    return sum(series.intensity(region, h) for h in hours) / duration_hours


def candidate_regions(
    workload: Workload, allowed_regions: list[str] | None
) -> list[str]:
    """Regions the workload may run in.

    Not movable -> only its home region. Movable -> the allowed set, with
    the home region always included (and first, so ties favor staying put).
    """
    if not workload.movable:
        return [workload.region]
    if not allowed_regions:
        return [workload.region]
    ordered = [workload.region]
    for r in allowed_regions:
        if r not in ordered:
            ordered.append(r)
    return ordered


def candidate_start_hours(workload: Workload, now_hour: int) -> list[int]:
    """Start hours the workload may use, honoring deferrability + deadline.

    Not deferrable -> only ``now_hour`` (cannot be time-shifted).
    Deferrable, no deadline -> the full 24h cycle, ordered from now.
    Deferrable with deadline_hours -> now .. now+deadline inclusive (mod 24).
    """
    if not 0 <= now_hour <= 23:
        raise ValueError(f"now_hour must be 0-23, got {now_hour}")
    if not workload.deferrable:
        return [now_hour]
    if workload.deadline_hours is None:
        return [(now_hour + offset) % 24 for offset in range(24)]
    # Latest start is now + deadline_hours; include both ends. Cap at 23h of
    # slip so we never loop past a full cycle.
    max_slip = min(int(workload.deadline_hours), 23)
    return [(now_hour + offset) % 24 for offset in range(max_slip + 1)]


def recommend_route(
    workload: Workload,
    series: GridIntensitySeries,
    duration_hours: int,
    now_hour: int,
    allowed_regions: list[str] | None = None,
    min_improvement_pct: float = 0.0,
) -> RoutingRecommendation:
    """Recommend the lowest-carbon feasible (region, start_hour) for a
    workload, or decline to move it.

    Tie-breaks (in order) favor minimal disruption: the home region over a
    move, and an earlier start over a later one. A move is only recommended
    when it beats running now-at-home by more than ``min_improvement_pct``.
    """
    if duration_hours <= 0:
        raise ValueError(f"duration_hours must be positive, got {duration_hours}")

    baseline_intensity = _avg_intensity(
        workload.region, now_hour, duration_hours, series
    )
    baseline = RoutingCandidate(
        region=workload.region,
        start_hour=now_hour,
        avg_intensity_g_per_kwh=round(baseline_intensity, 3),
    )

    regions = candidate_regions(workload, allowed_regions)
    start_hours = candidate_start_hours(workload, now_hour)

    best = baseline
    for region in regions:
        for start_hour in start_hours:
            avg = _avg_intensity(region, start_hour, duration_hours, series)
            # Strictly-better wins. Equal does not displace the incumbent,
            # and because baseline is seeded first and regions/hours are
            # ordered from "stay put / now", ties keep the workload in place.
            if avg < best.avg_intensity_g_per_kwh:
                best = RoutingCandidate(
                    region=region,
                    start_hour=start_hour,
                    avg_intensity_g_per_kwh=round(avg, 3),
                )

    reduction_pct = (
        (1 - best.avg_intensity_g_per_kwh / baseline_intensity) * 100
        if baseline_intensity > 0
        else 0.0
    )

    # Honor the minimum-improvement guard: a sub-threshold gain is treated
    # as "not worth moving" and collapses back to the baseline.
    if reduction_pct <= min_improvement_pct:
        best = baseline
        reduction_pct = 0.0

    moved_in_time = best.start_hour != now_hour
    moved_in_region = best.region != workload.region
    reason = _explain(workload, moved_in_time, moved_in_region, reduction_pct)

    return RoutingRecommendation(
        workload_id=workload.workload_id,
        baseline_region=workload.region,
        baseline_start_hour=now_hour,
        baseline_intensity=round(baseline_intensity, 3),
        chosen=best,
        duration_hours=duration_hours,
        moved_in_time=moved_in_time,
        moved_in_region=moved_in_region,
        intensity_reduction_pct=round(reduction_pct, 1),
        reason=reason,
    )


def _explain(
    workload: Workload,
    moved_in_time: bool,
    moved_in_region: bool,
    reduction_pct: float,
) -> str:
    if not moved_in_time and not moved_in_region:
        if not workload.deferrable and not workload.movable:
            return (
                "Workload is neither deferrable nor movable; cannot be "
                "rescheduled or relocated. No change."
            )
        return "No feasible slot beats running now in the home region. No change."
    parts = []
    if moved_in_time:
        parts.append("time-shifted within its deadline")
    if moved_in_region:
        parts.append("relocated to a cleaner allowed region")
    return (
        f"{' and '.join(parts).capitalize()} for a "
        f"{reduction_pct:.0f}% lower carbon intensity. "
        "No change executed; approval required."
    )
