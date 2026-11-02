"""Tests for the engine.resolve_grid_series seam: 'sample' stays fully
offline (the default), 'live' routes to Electricity Maps, bad source fails
loudly."""

from pathlib import Path

import pytest

from greenpilot.engine import resolve_grid_series

SAMPLE_GRID = Path("sample_data/grid_intensity_hourly.csv")


def test_sample_source_is_offline_and_loads_the_curve():
    series = resolve_grid_series("sample", SAMPLE_GRID)
    # A known sample point: eu-central-1 hour 18 is the dirty evening peak.
    assert series.intensity("eu-central-1", 18) == 580.0


def test_unknown_source_raises():
    with pytest.raises(ValueError) as exc:
        resolve_grid_series("satellite", SAMPLE_GRID)
    assert "Unknown grid source" in str(exc.value)


def test_live_source_without_key_raises(monkeypatch):
    monkeypatch.delenv("ELECTRICITYMAPS_API_KEY", raising=False)
    # Neutralize any ambient .env so this isolates the truly-absent-key case.
    monkeypatch.setattr(
        "greenpilot.grid.electricitymaps._load_dotenv_key", lambda *a, **k: None
    )
    from greenpilot.grid.electricitymaps import ElectricityMapsError

    with pytest.raises(ElectricityMapsError):
        resolve_grid_series("live", SAMPLE_GRID, regions=["eu-west-1"])
