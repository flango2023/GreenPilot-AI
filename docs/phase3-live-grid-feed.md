# Live Grid-Intensity Feed (Electricity Maps)

> Status: implemented, optional, offline-first.
> Builds on Phase 1 (GridIntensitySeries) and Phase 2 (routing).

## Why

Phase 1 and 2 prove the logic with an *illustrative* hourly curve
(`sample_data/grid_intensity_hourly.csv`). The headline figures (e.g. a
~46% time-shift and a ~97% region-shift on the sample fleet) are therefore
"illustrative," not "measured." A live feed turns them into real numbers
for a real grid, which is the single biggest credibility step for the
carbon-aware story.

## Design principle: offline-first, nothing breaks without it

The engine's default path makes **zero network calls and needs no API key**.
The live feed is strictly opt-in:

- Default `--grid-source sample` -> the committed curve, same as before.
- `--grid-source live` -> Electricity Maps, and only then is a key needed.

This preserves the repo's "runs in two minutes from a fresh clone, no
account" promise. The live feed also uses only the Python standard library
(`urllib`), so it adds **no new install-time dependency**.

## How it slots in

Everything goes through one seam, `engine.resolve_grid_series(source, ...)`,
so no call site changed. `source="live"` lazily imports
`grid/electricitymaps.py` and returns the same `GridIntensitySeries` the
sample loader returns. The rest of the engine cannot tell where the numbers
came from.

```
cli --grid-source live
   -> engine.resolve_grid_series("live", ...)
      -> grid.electricitymaps.fetch_series(regions, api_key)
         -> GET /v3/carbon-intensity/history?zone=<ZONE>  (auth-token header)
         -> map each {carbonIntensity, datetime} to a GridIntensityPoint
         -> GridIntensitySeries  (same type the sample curve produces)
```

## API contract used

- Endpoint: `GET https://api.electricitymap.org/v3/carbon-intensity/history?zone=<ZONE>`
- Auth: header `auth-token: <API_KEY>` (Electricity Maps' own scheme).
- Response: `{"zone": "...", "history": [{"carbonIntensity": <gCO2e/kWh>,
  "datetime": "<ISO 8601, Z-suffixed>", ...}, ...]}` (last 24h).
- Mapping: `datetime` -> hour-of-day (UTC), `carbonIntensity` ->
  `g_co2e_per_kwh`. AWS region -> EM zone via `AWS_REGION_TO_EM_ZONE`
  (eu-west-1->IE, eu-central-1->DE, eu-north-1->SE, ...).

## Graceful degradation

- An AWS region with no zone mapping is skipped and falls back to the
  existing annual-average table (no error).
- An hour the feed doesn't return falls back to that region's annual
  average, then the global default.
- Incomplete readings (missing intensity or datetime) are skipped, not
  fatal.
- Only if NO usable data could be fetched at all does it raise
  `ElectricityMapsError`, which the CLI turns into a clean one-line message
  (not a traceback) advising the offline source.

## Using it

```bash
# Get a free key from Electricity Maps (NOT an OpenAI key — different service).
export ELECTRICITYMAPS_API_KEY=your_real_key

python -m greenpilot telemetry greenest-window \
    --workload nightly-etl --duration-hours 6 \
    --grid-source live --regions eu-central-1

python -m greenpilot route recommend \
    --workload model-training --duration-hours 4 --now-hour 18 \
    --allowed-regions eu-north-1,eu-central-1 \
    --grid-source live
```

Without the env var, pass `--api-key ...`. With neither, the command exits
with a readable message pointing back to the offline default.

## Testing without a key or network

`tests/test_electricitymaps.py` injects a recorded response via the
`fetch` parameter, exercising the full history-to-series mapping, the auth
header, zone selection, fallback, and the no-data error, with no network
call and no credentials. Same approach the AWS collector uses with
botocore's Stubber.

## Not done yet

- Forecast endpoint (future start times beyond the last 24h). Today the
  feed is historical/recent; routing uses it as a representative daily
  shape, same as the sample curve.
- Caching / rate-limit handling for repeated calls (fine for the current
  one-shot CLI usage; matters once a dashboard polls it).
- Per-reading provenance labels in the output ("measured" vs "modelled").
  The data is real when live, but the CLI does not yet stamp each figure;
  worth adding before using live output in any CSRD-facing context.
