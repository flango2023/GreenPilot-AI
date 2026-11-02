"""Phase 2 routing policy tests. The point of these is the *constraints*:
a non-deferrable workload must never be time-shifted, a non-movable one
never region-shifted, deadlines must bound the search, and a movable
workload should prefer a genuinely cleaner region."""

from greenpilot.models import GridIntensityPoint, GridIntensitySeries, Workload
from greenpilot.rules.routing import (
    candidate_regions,
    candidate_start_hours,
    recommend_route,
)


def _flat_region(region, value):
    return [GridIntensityPoint(region, h, value) for h in range(24)]


def _dirty_then_clean(region):
    """0-5 clean (80), 17-21 dirty (500), else 250."""
    pts = []
    for h in range(24):
        if 0 <= h <= 5:
            g = 80.0
        elif 17 <= h <= 21:
            g = 500.0
        else:
            g = 250.0
        pts.append(GridIntensityPoint(region, h, g))
    return pts


# --- candidate enumeration ------------------------------------------------


def test_non_deferrable_only_offers_now():
    w = Workload("svc", "svc", "service", "eu-west-1", deferrable=False)
    assert candidate_start_hours(w, now_hour=18) == [18]


def test_deferrable_no_deadline_offers_full_cycle():
    w = Workload("b", "b", "batch", "eu-west-1", deferrable=True)
    hours = candidate_start_hours(w, now_hour=18)
    assert len(hours) == 24
    assert hours[0] == 18  # ordered from now


def test_deferrable_with_deadline_is_clipped():
    w = Workload("b", "b", "batch", "eu-west-1", deferrable=True, deadline_hours=4)
    # now + 0..4 inclusive = 5 candidate start hours
    assert candidate_start_hours(w, now_hour=20) == [20, 21, 22, 23, 0]


def test_non_movable_only_offers_home_region():
    w = Workload("svc", "svc", "service", "eu-west-1", movable=False)
    assert candidate_regions(w, ["eu-north-1", "eu-central-1"]) == ["eu-west-1"]


def test_movable_includes_home_region_first():
    w = Workload("t", "t", "training", "eu-west-1", movable=True)
    regions = candidate_regions(w, ["eu-north-1", "eu-west-1"])
    assert regions[0] == "eu-west-1"  # home first so ties favor staying
    assert set(regions) == {"eu-west-1", "eu-north-1"}


# --- the routing guarantees ----------------------------------------------


def test_non_deferrable_non_movable_is_never_changed():
    series = GridIntensitySeries(points=_dirty_then_clean("eu-west-1"))
    w = Workload("api", "API", "service", "eu-west-1",
                 deferrable=False, movable=False)
    rec = recommend_route(w, series, duration_hours=4, now_hour=18)
    assert rec.moved_in_time is False
    assert rec.moved_in_region is False
    assert rec.intensity_reduction_pct == 0.0
    assert "neither deferrable nor movable" in rec.reason


def test_deferrable_job_is_time_shifted_to_clean_hours():
    series = GridIntensitySeries(points=_dirty_then_clean("eu-central-1"))
    w = Workload("etl", "ETL", "batch", "eu-central-1",
                 deferrable=True, movable=False, deadline_hours=8)
    rec = recommend_route(w, series, duration_hours=4, now_hour=18)
    assert rec.moved_in_time is True
    assert rec.moved_in_region is False  # not movable
    assert rec.chosen.region == "eu-central-1"
    assert rec.intensity_reduction_pct > 0


def test_deadline_prevents_reaching_the_cleanest_hours():
    """If the clean window is outside the deadline horizon, the policy must
    NOT jump to it."""
    series = GridIntensitySeries(points=_dirty_then_clean("eu-central-1"))
    # now=18 (dirty). Clean hours are 0-5. A 2h deadline only reaches 18,19,20
    # (all dirty/peak), so no meaningful shift into the clean window.
    w = Workload("etl", "ETL", "batch", "eu-central-1",
                 deferrable=True, movable=False, deadline_hours=2)
    rec = recommend_route(w, series, duration_hours=1, now_hour=18)
    assert rec.chosen.start_hour in (18, 19, 20)


def test_movable_job_prefers_a_cleaner_region():
    # Home region dirty everywhere (400), a cleaner allowed region (50).
    pts = _flat_region("eu-west-1", 400.0) + _flat_region("eu-north-1", 50.0)
    series = GridIntensitySeries(points=pts)
    w = Workload("train", "Training", "training", "eu-west-1",
                 deferrable=True, movable=True, deadline_hours=24)
    rec = recommend_route(
        w, series, duration_hours=4, now_hour=12,
        allowed_regions=["eu-north-1"],
    )
    assert rec.moved_in_region is True
    assert rec.chosen.region == "eu-north-1"
    assert rec.intensity_reduction_pct > 80  # 400 -> 50 is an ~88% cut


def test_no_region_move_when_home_is_already_cleanest():
    pts = _flat_region("eu-west-1", 50.0) + _flat_region("eu-north-1", 400.0)
    series = GridIntensitySeries(points=pts)
    w = Workload("train", "Training", "training", "eu-west-1",
                 deferrable=True, movable=True, deadline_hours=24)
    rec = recommend_route(
        w, series, duration_hours=4, now_hour=12,
        allowed_regions=["eu-north-1"],
    )
    assert rec.moved_in_region is False
    assert rec.chosen.region == "eu-west-1"


def test_min_improvement_guard_suppresses_trivial_moves():
    # A tiny gain (250 now -> 245 elsewhere) should be ignored at a 5% guard.
    pts = _flat_region("eu-west-1", 250.0)
    pts += [GridIntensityPoint("eu-west-1", h, 245.0) for h in range(0, 3)]
    series = GridIntensitySeries(points=pts)
    w = Workload("b", "b", "batch", "eu-west-1",
                 deferrable=True, movable=False, deadline_hours=6)
    rec = recommend_route(
        w, series, duration_hours=1, now_hour=12, min_improvement_pct=5.0
    )
    assert rec.moved_in_time is False
    assert rec.intensity_reduction_pct == 0.0


def test_recommendation_carries_the_counterfactual():
    series = GridIntensitySeries(points=_dirty_then_clean("eu-central-1"))
    w = Workload("etl", "ETL", "batch", "eu-central-1",
                 deferrable=True, movable=False, deadline_hours=8)
    rec = recommend_route(w, series, duration_hours=4, now_hour=18)
    # The baseline (what it would have emitted running now) is always kept.
    assert rec.baseline_region == "eu-central-1"
    assert rec.baseline_start_hour == 18
    assert rec.baseline_intensity > rec.chosen.avg_intensity_g_per_kwh
