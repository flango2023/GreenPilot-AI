"""Phase 1 time-aware carbon tests. These exercise the new window/workload
functions only. The existing snapshot functions (test_carbon.py) are left
untouched and must stay green."""

from datetime import datetime

from greenpilot.models import (
    GridIntensityPoint,
    GridIntensitySeries,
    Resource,
    Workload,
)
from greenpilot.rules.carbon import (
    greenest_start_hour,
    resource_kwh_for_window,
    resource_kwh_per_month,
    workload_co2e_kg_for_window,
)

M5_WATTS = 35.0  # matches INSTANCE_FAMILY_AVG_WATTS["m5"]


def _m5(region="eu-west-1", monthly_cost=100.0):
    return Resource(
        resource_id="ec2-1",
        service="EC2",
        resource_type="m5.large",
        region=region,
        monthly_cost=monthly_cost,
    )


def test_window_kwh_matches_monthly_math_at_month_length():
    """resource_kwh_for_window over a full always-on month must equal the
    existing resource_kwh_per_month, i.e. the new path is consistent with
    the old one, not a different model."""
    r = Resource(
        resource_id="ec2-1",
        service="EC2",
        resource_type="m5.large",
        region="eu-west-1",
        monthly_cost=100.0,
        hours_running_per_month=730,
    )
    assert resource_kwh_for_window(r, 730) == resource_kwh_per_month(r)


def test_window_kwh_scales_linearly_with_hours():
    r = _m5()
    one_hour = resource_kwh_for_window(r, 1)
    ten_hours = resource_kwh_for_window(r, 10)
    assert abs(ten_hours - one_hour * 10) < 1e-9
    assert one_hour == M5_WATTS / 1000.0


def test_same_workload_emits_less_in_a_green_hour():
    """The core Phase 1 assertion: identical workload, identical duration,
    different hour of day -> different (lower) carbon when the grid is clean."""
    r = _m5()
    resources = {"ec2-1": r}
    workload = Workload(
        workload_id="batch",
        name="batch",
        kind="batch",
        region="eu-west-1",
        resource_ids=["ec2-1"],
        deferrable=True,
    )
    series = GridIntensitySeries(
        points=[
            GridIntensityPoint("eu-west-1", 3, 90.0),  # clean night hour
            GridIntensityPoint("eu-west-1", 19, 500.0),  # dirty evening hour
        ]
    )
    green = workload_co2e_kg_for_window(
        workload, resources, series,
        datetime(2026, 1, 1, 3, 0), datetime(2026, 1, 1, 4, 0),
    )
    dirty = workload_co2e_kg_for_window(
        workload, resources, series,
        datetime(2026, 1, 1, 19, 0), datetime(2026, 1, 1, 20, 0),
    )
    assert green.kwh == dirty.kwh  # same energy...
    assert green.co2e_kg < dirty.co2e_kg  # ...less carbon in the green hour
    assert green.g_co2e_per_kwh == 90.0
    assert dirty.g_co2e_per_kwh == 500.0


def test_window_blends_across_hour_boundary():
    """A window that straddles a clean->dirty transition should report an
    effective intensity between the two, not one or the other."""
    r = _m5()
    resources = {"ec2-1": r}
    workload = Workload(
        workload_id="batch",
        name="batch",
        kind="batch",
        region="eu-west-1",
        resource_ids=["ec2-1"],
    )
    series = GridIntensitySeries(
        points=[
            GridIntensityPoint("eu-west-1", 3, 100.0),
            GridIntensityPoint("eu-west-1", 4, 300.0),
        ]
    )
    # 03:30 -> 04:30: half an hour at 100, half at 300 -> effective ~200.
    sample = workload_co2e_kg_for_window(
        workload, resources, series,
        datetime(2026, 1, 1, 3, 30), datetime(2026, 1, 1, 4, 30),
    )
    assert 100.0 < sample.g_co2e_per_kwh < 300.0
    assert abs(sample.g_co2e_per_kwh - 200.0) < 1e-6


def test_sample_carries_cost_and_region():
    r = _m5(monthly_cost=250.0)
    resources = {"ec2-1": r}
    workload = Workload(
        workload_id="svc",
        name="svc",
        kind="service",
        region="eu-west-1",
        resource_ids=["ec2-1"],
    )
    series = GridIntensitySeries(annual_average_by_region={"eu-west-1": 316.0})
    sample = workload_co2e_kg_for_window(
        workload, resources, series,
        datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 1, 1, 0),
    )
    assert sample.region == "eu-west-1"
    assert sample.monthly_cost_eur == 250.0
    # No hourly point -> falls back to the annual average, preserving old math.
    assert sample.g_co2e_per_kwh == 316.0


def test_unknown_resource_ids_are_skipped_not_fatal():
    resources = {"ec2-1": _m5()}
    workload = Workload(
        workload_id="svc",
        name="svc",
        kind="service",
        region="eu-west-1",
        resource_ids=["ec2-1", "does-not-exist"],
    )
    series = GridIntensitySeries(annual_average_by_region={"eu-west-1": 316.0})
    sample = workload_co2e_kg_for_window(
        workload, resources, series,
        datetime(2026, 1, 1, 0, 0), datetime(2026, 1, 1, 1, 0),
    )
    # Only the real resource contributes; the missing id is ignored.
    assert sample.kwh == resource_kwh_for_window(resources["ec2-1"], 1)


def test_greenest_start_hour_picks_the_clean_window():
    # Cheap/clean overnight (0-5), expensive/dirty evening (17-21).
    points = []
    for h in range(24):
        if 0 <= h <= 5:
            g = 80.0
        elif 17 <= h <= 21:
            g = 500.0
        else:
            g = 250.0
        points.append(GridIntensityPoint("eu-west-1", h, g))
    series = GridIntensitySeries(points=points)

    start, avg = greenest_start_hour("eu-west-1", series, duration_hours=4)
    # Best 4h block sits inside the clean overnight stretch.
    assert start in (0, 1, 2)
    assert avg == 80.0


def test_greenest_start_hour_wraps_past_midnight():
    # Only 22,23,0,1 are clean; the best 4h block must wrap midnight.
    points = []
    for h in range(24):
        g = 90.0 if h in (22, 23, 0, 1) else 600.0
        points.append(GridIntensityPoint("eu-west-1", h, g))
    series = GridIntensitySeries(points=points)
    start, avg = greenest_start_hour("eu-west-1", series, duration_hours=4)
    assert start == 22
    assert avg == 90.0
