"""Live grid-feed tests. These exercise the full Electricity Maps mapping
against a RECORDED response via an injected fetch stub, so the suite never
makes a network call and needs no API key, the same no-live-credentials
approach the AWS collector tests use."""

import pytest

from greenpilot.grid.electricitymaps import (
    AWS_REGION_TO_EM_ZONE,
    ElectricityMapsError,
    fetch_series,
    resolve_api_key,
)


def _recorded_history(zone, base_intensity):
    """A fake 24h history payload shaped like the real v3 response."""
    return {
        "zone": zone,
        "history": [
            {
                "carbonIntensity": base_intensity + hour,
                "datetime": f"2026-01-01T{hour:02d}:00:00Z",
            }
            for hour in range(24)
        ],
    }


def test_resolve_api_key_prefers_explicit(monkeypatch):
    monkeypatch.setenv("ELECTRICITYMAPS_API_KEY", "from-env")
    assert resolve_api_key("explicit") == "explicit"
    assert resolve_api_key(None) == "from-env"


def test_resolve_api_key_none_when_absent(monkeypatch):
    monkeypatch.delenv("ELECTRICITYMAPS_API_KEY", raising=False)
    # Also neutralize any ambient .env file so this tests the truly-absent
    # case regardless of the developer's local setup.
    monkeypatch.setattr(
        "greenpilot.grid.electricitymaps._load_dotenv_key", lambda *a, **k: None
    )
    assert resolve_api_key(None) is None


def test_missing_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("ELECTRICITYMAPS_API_KEY", raising=False)
    monkeypatch.setattr(
        "greenpilot.grid.electricitymaps._load_dotenv_key", lambda *a, **k: None
    )
    with pytest.raises(ElectricityMapsError) as exc:
        fetch_series(["eu-west-1"], api_key=None, fetch=lambda u, h: {})
    assert "API key" in str(exc.value)


def test_fetch_maps_history_to_hourly_points():
    calls = []

    def stub(url, headers):
        calls.append((url, headers))
        # eu-central-1 -> zone DE
        return _recorded_history("DE", base_intensity=200)

    series = fetch_series(["eu-central-1"], api_key="k", fetch=stub)

    # Auth header and zone made it into the request.
    assert calls[0][1] == {"auth-token": "k"}
    assert "zone=DE" in calls[0][0]
    # Hour 0 -> 200, hour 23 -> 223, exactly as recorded.
    assert series.intensity("eu-central-1", 0) == 200.0
    assert series.intensity("eu-central-1", 23) == 223.0


def test_unmapped_region_falls_back_to_annual_average():
    # ap-southeast-9 has no zone mapping; fetch should never be called for it,
    # and lookups fall back to the annual-average default.
    def stub(url, headers):
        raise AssertionError("fetch should not be called for an unmapped region")

    # Pair it with a mapped region so the call doesn't raise "no data".
    def mixed(url, headers):
        return _recorded_history("IE", base_intensity=100)

    series = fetch_series(
        ["eu-west-1", "ap-southeast-9"], api_key="k", fetch=mixed
    )
    # Mapped region has live data...
    assert series.intensity("eu-west-1", 5) == 105.0
    # ...unmapped region falls back (default intensity, not an error).
    assert series.intensity("ap-southeast-9", 5) == series.default


def test_all_regions_failing_raises():
    def empty(url, headers):
        return {"zone": "DE", "history": []}

    with pytest.raises(ElectricityMapsError) as exc:
        fetch_series(["eu-central-1"], api_key="k", fetch=empty)
    assert "no usable" in str(exc.value)


def test_incomplete_entries_are_skipped_not_fatal():
    def partial(url, headers):
        return {
            "zone": "DE",
            "history": [
                {"carbonIntensity": 150, "datetime": "2026-01-01T06:00:00Z"},
                {"carbonIntensity": None, "datetime": "2026-01-01T07:00:00Z"},
                {"datetime": "2026-01-01T08:00:00Z"},  # missing intensity
                {"carbonIntensity": 180},  # missing datetime
            ],
        }

    series = fetch_series(["eu-central-1"], api_key="k", fetch=partial)
    # Only the one complete reading is used; the rest are skipped silently.
    assert series.intensity("eu-central-1", 6) == 150.0
    # Hour 7 had no usable value -> falls back to the region's annual average
    # (380 for eu-central-1), which fetch_series seeds from the real table.
    assert series.intensity("eu-central-1", 7) == 380.0


def test_zone_map_covers_sample_regions():
    # The three EU regions used across sample_data must all have a zone.
    for region in ("eu-west-1", "eu-central-1", "eu-north-1"):
        assert region in AWS_REGION_TO_EM_ZONE


def test_dotenv_loader_reads_key_from_file(tmp_path, monkeypatch):
    from greenpilot.grid.electricitymaps import _load_dotenv_key

    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "OTHER_VAR=ignored\n"
        "ELECTRICITYMAPS_API_KEY='secret-from-file'\n",
        encoding="utf-8",
    )
    assert _load_dotenv_key(start=tmp_path) == "secret-from-file"


def test_dotenv_loader_returns_none_when_no_file(tmp_path):
    from greenpilot.grid.electricitymaps import _load_dotenv_key

    assert _load_dotenv_key(start=tmp_path) is None
