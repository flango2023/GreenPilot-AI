"""Command-line entrypoint: `python -m greenpilot analyze <data_dir>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine import analyze, analyze_resources
from .report import render_markdown


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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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
