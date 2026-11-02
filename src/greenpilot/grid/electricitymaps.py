"""Electricity Maps live carbon-intensity feed (optional).

Fetches the last 24 hours of hourly carbon intensity for a zone and maps it
onto a GridIntensitySeries, the same structure the committed sample curve
produces. Nothing here runs unless the caller asks for the live source AND
an API key is present; the engine's default path never touches the network.

API contract (Electricity Maps v3):
  GET https://api.electricitymap.org/v3/carbon-intensity/history?zone=<ZONE>
  header: auth-token: <API_KEY>
  -> {"zone": "...", "history": [{"carbonIntensity": <int gCO2e/kWh>,
      "datetime": "2026-..T..:..:..Z", ...}, ...]}

Uses only the standard library (urllib), so adding a live feed introduces no
new install-time dependency. A `fetch` callable can be injected so tests can
exercise the full mapping against a recorded response with no network call,
the same no-live-credentials approach the AWS collector tests use.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable

from ..models import GridIntensityPoint, GridIntensitySeries
from ..rules.carbon import REGION_GRID_INTENSITY_G_PER_KWH

API_BASE = "https://api.electricitymap.org/v3"
ENV_API_KEY = "ELECTRICITYMAPS_API_KEY"

# AWS region -> Electricity Maps zone. Covers the regions the sample data and
# the carbon.py annual-average table already use. Unknown regions simply have
# no live data and fall back to the annual average, so the engine degrades
# gracefully rather than failing.
AWS_REGION_TO_EM_ZONE: dict[str, str] = {
    "eu-west-1": "IE",       # Ireland
    "eu-west-2": "GB",       # London
    "eu-west-3": "FR",       # Paris
    "eu-central-1": "DE",    # Frankfurt
    "eu-north-1": "SE",      # Stockholm
    "us-east-1": "US-MIDA-PJM",
    "us-west-2": "US-NW-PACW",
}

# A fetch callable takes (url, headers) and returns the decoded JSON dict.
FetchFn = Callable[[str, dict], dict]


class ElectricityMapsError(RuntimeError):
    """Raised when the live feed cannot be used or returns unusable data."""


def _default_fetch(url: str, headers: dict) -> dict:
    """Real HTTP GET via the standard library. Isolated so tests can inject a
    stub instead and never hit the network."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:  # pragma: no cover - network path
        raise ElectricityMapsError(
            f"Electricity Maps returned HTTP {exc.code} for {url}"
        ) from exc
    except urllib.error.URLError as exc:  # pragma: no cover - network path
        raise ElectricityMapsError(
            f"Could not reach Electricity Maps: {exc.reason}"
        ) from exc


def _load_dotenv_key(start: "os.PathLike | str | None" = None) -> str | None:
    """Best-effort read of ELECTRICITYMAPS_API_KEY from a .env file, walking
    up from the current directory. Dependency-free (no python-dotenv), and
    never overrides an already-set environment variable. Returns None if no
    .env or key is found. Malformed files are ignored silently rather than
    breaking the offline path."""
    import pathlib

    cwd = pathlib.Path(start or os.getcwd()).resolve()
    for directory in [cwd, *cwd.parents]:
        candidate = directory / ".env"
        if not candidate.is_file():
            continue
        try:
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                if name.strip() == ENV_API_KEY:
                    return value.strip().strip("'").strip('"') or None
        except OSError:
            return None
        return None  # .env found but no key line
    return None


def resolve_api_key(explicit: str | None = None) -> str | None:
    """The explicit key if given, else the env var, else a .env file, else
    None (offline)."""
    return explicit or os.environ.get(ENV_API_KEY) or _load_dotenv_key()


def _history_to_points(region: str, history: list[dict]) -> list[GridIntensityPoint]:
    """Map one zone's 24h history to hour-of-day GridIntensityPoints.

    Later entries for the same hour win, so the most recent reading for a
    given hour-of-day is the one kept."""
    points: list[GridIntensityPoint] = []
    for entry in history:
        ci = entry.get("carbonIntensity")
        dt_raw = entry.get("datetime")
        if ci is None or dt_raw is None:
            continue  # skip incomplete readings rather than fail the whole feed
        hour = _parse_hour(dt_raw)
        points.append(
            GridIntensityPoint(
                region=region,
                hour_of_day=hour,
                g_co2e_per_kwh=float(ci),
            )
        )
    return points


def _parse_hour(dt_raw: str) -> int:
    """Hour-of-day (UTC) from an ISO 8601 timestamp, tolerating a 'Z' suffix."""
    normalized = dt_raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.hour


def fetch_series(
    regions: list[str],
    api_key: str | None = None,
    fetch: FetchFn | None = None,
    annual_average_by_region: dict[str, float] | None = None,
) -> GridIntensitySeries:
    """Build a GridIntensitySeries from live Electricity Maps data.

    For each AWS region with a known zone mapping, fetch 24h of hourly
    carbon intensity and add it as hour-of-day points. Regions without a
    mapping, or hours the feed doesn't cover, fall back to the existing
    annual-average table, so the result is always usable.

    Raises ElectricityMapsError only when NO usable data could be fetched at
    all (e.g. missing key, or every region failed); partial coverage is fine.
    """
    key = resolve_api_key(api_key)
    if not key:
        raise ElectricityMapsError(
            f"No Electricity Maps API key. Set ${ENV_API_KEY} or pass "
            "api_key=..., or use the offline sample data instead."
        )
    fetch = fetch or _default_fetch
    headers = {"auth-token": key}

    points: list[GridIntensityPoint] = []
    regions_with_data: list[str] = []
    for region in regions:
        zone = AWS_REGION_TO_EM_ZONE.get(region)
        if zone is None:
            continue  # no mapping -> falls back to annual average
        url = f"{API_BASE}/carbon-intensity/history?zone={zone}"
        payload = fetch(url, headers)
        history = payload.get("history") or []
        region_points = _history_to_points(region, history)
        if region_points:
            points.extend(region_points)
            regions_with_data.append(region)

    if not points:
        raise ElectricityMapsError(
            "Electricity Maps returned no usable carbon-intensity data for "
            f"regions {regions}. Falling back to offline data is recommended."
        )

    averages = (
        annual_average_by_region
        if annual_average_by_region is not None
        else dict(REGION_GRID_INTENSITY_G_PER_KWH)
    )
    return GridIntensitySeries(points=points, annual_average_by_region=averages)
