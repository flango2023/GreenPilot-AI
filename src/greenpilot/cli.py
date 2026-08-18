"""Command-line entrypoint: `python -m greenpilot analyze <data_dir>`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine import analyze
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
        "analyze", help="Analyze a data directory and print/save a report."
    )
    analyze_parser.add_argument(
        "data_dir",
        nargs="?",
        default="sample_data",
        help="Directory containing cost_and_usage.csv and resource_inventory.json "
        "(default: sample_data)",
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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "analyze":
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
