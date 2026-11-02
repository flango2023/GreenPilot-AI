"""Command-line entrypoint: `python -m greenpilot analyze <data_dir>`."""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from .engine import (
    analyze,
    analyze_resources,
    load_grid_intensity_series,
    load_resources,
    load_workloads,
)
from .report import render_markdown
from .rules.carbon import greenest_start_hour, workload_co2e_kg_for_window


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="greenpilot",
        description=(
            "GreenPilot AI assessment engine. Reads AWS billing and resource "
            "data and produces a cost/carbon/governance report."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser(
        "analyze", help="Analyze a data directory or a live AWS account and print/save a report."
    )
    analyze_parser.add_argument(
        "data_dir",
        nargs="?",
        default="sample_data",
        help="Directory containing cost_and_usage.csv and resource_inventory.json. "
        "Ignored when --source live is used. (default: sample_data)",
    )
    analyze_parser.add_argument(
        "--source",
        choices=["sample", "live"],
        default="sample",
        help="'sample' reads the data_dir above (no AWS account needed, the default). "
        "'live' connects to a real AWS account via boto3 using your normal "
        "AWS credentials (env vars, ~/.aws/credentials, or an assumed role). "
        "Requires `pip install -e '.[aws]'`.",
    )
    analyze_parser.add_argument(
        "--regions",
        default="eu-west-1",
        help="Comma-separated AWS regions to scan when --source live is used "
        "(default: eu-west-1). Ignored for --source sample.",
    )
    analyze_parser.add_argument(
        "--company",
        default="Acme Tech Solutions GmbH",
        help="Company name to show on the report.",
    )
    analyze_parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Write the Markdown report to this file instead of stdout.",
    )

    # --- Phase 1: carbon-aware workload telemetry ---------------------------
    telemetry_parser = subparsers.add_parser(
        "telemetry",
        help="Phase 1: measure per-workload carbon over time and find the "
        "greenest window to run deferrable work.",
    )
    telemetry_sub = telemetry_parser.add_subparsers(
        dest="telemetry_command", required=True
    )

    record = telemetry_sub.add_parser(
        "record",
        help="Compute a WorkloadCarbonSample per workload for a time window "
        "and append it to a CSV (the append-only telemetry log).",
    )
    record.add_argument(
        "--data-dir",
        type=Path,
        default=Path("sample_data"),
        help="Directory with resource_inventory.json + cost_and_usage.csv "
        "(default: sample_data).",
    )
    record.add_argument(
        "--workloads",
        type=Path,
        default=Path("sample_data/workloads.json"),
        help="Path to workloads.json (default: sample_data/workloads.json).",
    )
    record.add_argument(
        "--grid",
        type=Path,
        default=Path("sample_data/grid_intensity_hourly.csv"),
        help="Path to the hourly grid-intensity CSV "
        "(default: sample_data/grid_intensity_hourly.csv).",
    )
    record.add_argument(
        "--window-start",
        required=True,
        help="Window start, ISO 8601, e.g. 2026-01-01T00:00.",
    )
    record.add_argument(
        "--window-end",
        required=True,
        help="Window end, ISO 8601, e.g. 2026-01-02T00:00.",
    )
    record.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("telemetry.csv"),
        help="Append-only CSV to write samples to (default: telemetry.csv).",
    )

    greenest = telemetry_sub.add_parser(
        "greenest-window",
        help="For a deferrable workload, print the lowest-carbon start hour "
        "and the carbon saved versus running now. (Phase 2 teaser.)",
    )
    greenest.add_argument(
        "--workloads",
        type=Path,
        default=Path("sample_data/workloads.json"),
        help="Path to workloads.json (default: sample_data/workloads.json).",
    )
    greenest.add_argument(
        "--grid",
        type=Path,
        default=Path("sample_data/grid_intensity_hourly.csv"),
        help="Path to the hourly grid-intensity CSV.",
    )
    greenest.add_argument(
        "--workload",
        required=True,
        help="workload_id to evaluate (must exist in the workloads file).",
    )
    greenest.add_argument(
        "--duration-hours",
        type=int,
        required=True,
        help="How many whole hours the job runs.",
    )

    return parser


def _run_live(regions: list[str], company_name: str):
    try:
        from .aws.collector import check_connectivity, collect_all
    except ImportError:
        print(
            "boto3 is not installed. Run: pip install -e '.[aws]'",
            file=sys.stderr,
        )
        raise SystemExit(1)

    import boto3

    try:
        connectivity = check_connectivity(boto3.Session())
    except Exception as exc:  # noqa: BLE001 - surface any auth/credential failure plainly
        print(f"Could not connect to AWS: {exc}", file=sys.stderr)
        print(
            "Check that AWS credentials are configured (env vars, "
            "~/.aws/credentials, or an assumed role) and that the identity "
            "has the permissions in iam/read-only-collector-policy.json.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print(f"Connected as {connectivity.arn} (account {connectivity.account_id})", file=sys.stderr)
    for name, check in connectivity.services.items():
        status = "ok" if check.ok else f"failed: {check.detail}"
        print(f"  {name}: {status}", file=sys.stderr)

    result = collect_all(regions)
    for warning in result.warnings:
        print(f"Warning: {warning}", file=sys.stderr)

    return analyze_resources(result.resources, result.iam_users, company_name=company_name)


_SAMPLE_FIELDS = [
    "workload_id",
    "window_start",
    "window_end",
    "region",
    "kwh",
    "g_co2e_per_kwh",
    "co2e_kg",
    "monthly_cost_eur",
]


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise SystemExit(
            f"Could not parse datetime {value!r}. Use ISO 8601, e.g. "
            "2026-01-01T00:00."
        )


def _run_telemetry_record(args) -> int:
    start = _parse_dt(args.window_start)
    end = _parse_dt(args.window_end)
    if end <= start:
        raise SystemExit("--window-end must be after --window-start.")

    resources = {r.resource_id: r for r in load_resources(args.data_dir)}
    workloads = load_workloads(args.workloads)
    series = load_grid_intensity_series(args.grid)

    samples = [
        workload_co2e_kg_for_window(w, resources, series, start, end)
        for w in workloads
    ]

    # Append-only: never rewrite past rows. Write the header only when the
    # file is new, so repeated runs keep accumulating the audit trail.
    out = Path(args.out)
    is_new = not out.exists()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_SAMPLE_FIELDS)
        if is_new:
            writer.writeheader()
        for s in samples:
            row = asdict(s)
            row["window_start"] = s.window_start.isoformat()
            row["window_end"] = s.window_end.isoformat()
            writer.writerow(row)

    total_kg = sum(s.co2e_kg for s in samples)
    print(
        f"Recorded {len(samples)} workload sample(s) for "
        f"{start.isoformat()} -> {end.isoformat()} "
        f"(total {total_kg:.3f} kg CO2e) to {out}"
    )
    return 0


def _run_telemetry_greenest_window(args) -> int:
    workloads = {w.workload_id: w for w in load_workloads(args.workloads)}
    workload = workloads.get(args.workload)
    if workload is None:
        raise SystemExit(
            f"workload {args.workload!r} not found. Available: "
            f"{', '.join(sorted(workloads)) or '(none)'}"
        )
    if not workload.deferrable:
        print(
            f"Note: workload {workload.workload_id!r} is not marked deferrable; "
            "showing the greenest window anyway, but moving it may not be safe.",
            file=sys.stderr,
        )

    series = load_grid_intensity_series(args.grid)
    best_hour, best_avg = greenest_start_hour(
        workload.region, series, args.duration_hours
    )

    # Compare against the dirtiest equally-long window, to show the spread.
    worst_hour, worst_avg = max(
        (
            (
                h,
                sum(
                    series.intensity(workload.region, (h + o) % 24)
                    for o in range(args.duration_hours)
                )
                / args.duration_hours,
            )
            for h in range(24)
        ),
        key=lambda pair: pair[1],
    )
    saving_pct = (1 - best_avg / worst_avg) * 100 if worst_avg > 0 else 0.0

    print(f"Workload: {workload.workload_id} ({workload.name})")
    print(f"Region:   {workload.region}")
    print(f"Duration: {args.duration_hours}h")
    print(
        f"Greenest start: {best_hour:02d}:00  "
        f"(avg {best_avg:.0f} gCO2e/kWh over the run)"
    )
    print(
        f"Dirtiest start: {worst_hour:02d}:00  "
        f"(avg {worst_avg:.0f} gCO2e/kWh over the run)"
    )
    print(
        f"-> Running in the greenest window cuts carbon intensity by "
        f"{saving_pct:.0f}% versus the worst time."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "telemetry":
        if args.telemetry_command == "record":
            return _run_telemetry_record(args)
        if args.telemetry_command == "greenest-window":
            return _run_telemetry_greenest_window(args)
        parser.error(f"Unknown telemetry command: {args.telemetry_command}")
        return 2

    if args.command == "analyze":
        if args.source == "live":
            regions = [r.strip() for r in args.regions.split(",") if r.strip()]
            report = _run_live(regions, args.company)
        else:
            report = analyze(Path(args.data_dir), company_name=args.company)

        markdown = render_markdown(report)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(markdown, encoding="utf-8")
            print(f"Report written to {args.output}")
        else:
            print(markdown)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
