"""Phase 1 model tests. These cover the new, additive telemetry types only;
they must not depend on or alter any existing snapshot behavior."""

from datetime import datetime

import pytest

from greenpilot.models import (
    GridIntensityPoint,
    GridIntensitySeries,
    Workload,
    WorkloadCarbonSample,
)


def test_workload_defaults_are_conservative():
    w = Workload(
        workload_id="batch-nightly",
        name="Nightly ETL",
        kind="batch",
        region="eu-west-1",
    )
    # A workload is NOT assumed shiftable unless explicitly marked so; this
    # keeps Phase 2 routing from ever moving something it shouldn't.
    assert w.deferrable is False
    assert w.movable is False
    assert w.deadline_hours is None
    assert w.resource_ids == []
    assert w.tags == {}


def test_workload_can_reference_resources():
    w = Workload(
        workload_id="svc-api",
        name="API service",
        kind="service",
        region="eu-west-1",
        resource_ids=["ec2-api-06", "rds-primary-01"],
        deferrable=False,
        movable=False,
    )
    assert w.resource_ids == ["ec2-api-06", "rds-primary-01"]


def test_grid_intensity_point_rejects_bad_hour():
    with pytest.raises(ValueError):
        GridIntensityPoint(region="eu-west-1", hour_of_day=24, g_co2e_per_kwh=300)
    with pytest.raises(ValueError):
        GridIntensityPoint(region="eu-west-1", hour_of_day=-1, g_co2e_per_kwh=300)


def test_grid_intensity_point_rejects_negative_intensity():
    with pytest.raises(ValueError):
        GridIntensityPoint(region="eu-west-1", hour_of_day=3, g_co2e_per_kwh=-5)


def test_series_returns_hourly_value_when_present():
    series = GridIntensitySeries(
        points=[
            GridIntensityPoint("eu-west-1", 2, 120.0),
            GridIntensityPoint("eu-west-1", 19, 480.0),
        ]
    )
    assert series.intensity("eu-west-1", 2) == 120.0
    assert series.intensity("eu-west-1", 19) == 480.0


def test_series_falls_back_to_annual_average_then_default():
    series = GridIntensitySeries(
        points=[GridIntensityPoint("eu-west-1", 2, 120.0)],
        annual_average_by_region={"eu-west-1": 316.0},
        default=400.0,
    )
    # Hour present -> hourly value.
    assert series.intensity("eu-west-1", 2) == 120.0
    # Hour absent, region known -> annual average (preserves old behavior).
    assert series.intensity("eu-west-1", 10) == 316.0
    # Region unknown -> default.
    assert series.intensity("ap-southeast-9", 10) == 400.0


def test_series_captures_intra_day_swing():
    """The whole point of Phase 1: the same region must be able to report a
    different intensity at different hours."""
    series = GridIntensitySeries(
        points=[
            GridIntensityPoint("eu-central-1", 3, 90.0),
            GridIntensityPoint("eu-central-1", 18, 520.0),
        ]
    )
    night = series.intensity("eu-central-1", 3)
    evening = series.intensity("eu-central-1", 18)
    assert evening > night
    # Sanity: the swing is the >5x kind of variation the research describes.
    assert evening / night > 5


def test_later_point_overrides_earlier_for_same_key():
    series = GridIntensitySeries(
        points=[
            GridIntensityPoint("eu-west-1", 5, 100.0),
            GridIntensityPoint("eu-west-1", 5, 150.0),
        ]
    )
    assert series.intensity("eu-west-1", 5) == 150.0


def test_workload_carbon_sample_is_a_plain_record():
    sample = WorkloadCarbonSample(
        workload_id="batch-nightly",
        window_start=datetime(2026, 1, 1, 0, 0),
        window_end=datetime(2026, 1, 1, 1, 0),
        region="eu-west-1",
        kwh=0.5,
        g_co2e_per_kwh=120.0,
        co2e_kg=0.06,
        monthly_cost_eur=12.0,
    )
    assert sample.workload_id == "batch-nightly"
    assert sample.window_end > sample.window_start
    assert sample.co2e_kg == 0.06
