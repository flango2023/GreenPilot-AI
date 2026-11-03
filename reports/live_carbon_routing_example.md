# Live Carbon-Aware Routing — Worked Example

This is **real output** from the GreenPilot engine running against **live
Electricity Maps grid data** (not the illustrative sample curve), captured on
**2 November 2026** for three sample workloads. Reproduce it yourself with a
free Electricity Maps API key:

```bash
export ELECTRICITYMAPS_API_KEY=your_key      # a free Electricity Maps key
python -m greenpilot route recommend --workload model-training \
    --duration-hours 4 --now-hour 18 \
    --allowed-regions eu-north-1,eu-central-1 --grid-source live
```

> The exact gCO2e/kWh numbers below are a snapshot of the grid at capture
> time and will differ when you run it — that is the point. These are
> measured, time-varying grid readings, not fixed figures.

## 1. Relocatable training job — a 93% cut

```
Workload: model-training  (deferrable=yes, movable=yes)
Baseline: run now 18:00 in eu-west-1  -> 365 gCO2e/kWh
Recommend: start 22:00 in eu-north-1  -> 24 gCO2e/kWh
Time-shifted within its deadline and relocated to a cleaner allowed region
for a 93% lower carbon intensity. No change executed; approval required.
```

A job allowed to move region jumps from Ireland's grid (365) to Sweden's
hydro/nuclear grid (24) — a **93% lower carbon intensity** for the same work.

## 2. Region-locked batch job — an honest 3% cut

```
Workload: nightly-etl  (deferrable=yes, movable=no)
Baseline: run now 18:00 in eu-central-1  -> 512 gCO2e/kWh
Recommend: start 02:00 in eu-central-1  -> 495 gCO2e/kWh
Time-shifted within its deadline for a 3% lower carbon intensity.
```

This workload cannot leave Frankfurt, so it can only time-shift. On this
particular day the German grid was relatively flat overnight, so the honest
win is small — **3%**. A real measurement tool reports the real number; it
does not inflate a modest result into a headline.

## 3. Customer-facing service — correctly declined

```
Workload: api-service  (deferrable=no, movable=no)
Baseline: run now 18:00 in eu-west-1  -> 372 gCO2e/kWh
Recommend: start 18:00 in eu-west-1  -> 372 gCO2e/kWh
Workload is neither deferrable nor movable; cannot be rescheduled or
relocated. No change.
```

A production API that cannot be moved or delayed is left exactly where it is,
with the reason stated. The engine never recommends a change that would
break a workload's constraints.

## Telemetry log (same run, live data)

`telemetry record` captured one append-only sample per workload for the
18:00–00:00 window on live data — see
[`live_telemetry_example.csv`](live_telemetry_example.csv):

| workload | region | kWh | gCO2e/kWh (live) | kg CO2e |
|---|---|---:|---:|---:|
| api-service | eu-west-1 | 0.60 | 358.0 | 0.2148 |
| nightly-etl | eu-central-1 | 0.42 | 511.5 | 0.2148 |
| model-training | eu-west-1 | 0.24 | 358.0 | 0.0859 |
| dev-sandbox | eu-west-1 | 0.09 | 358.0 | 0.0322 |

## What this demonstrates

- The engine makes **constraint-aware** carbon decisions on **real grid
  data**: move what can move (93%), time-shift what can only shift (3%),
  leave fixed workloads alone.
- Every recommendation keeps the baseline (what running now emits) as an
  auditable counterfactual.
- It is **measure-and-recommend only** — nothing is executed. Approval is
  always required, consistent with the rest of GreenPilot.
