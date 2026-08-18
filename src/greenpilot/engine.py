"""Orchestration: load AWS data (sample files or a live account), run every
rule set, assemble a Report.

This is the "rule-based optimization engine" described on
https://greenpilotai.com/platform.html. ML-based scoring is a documented
roadmap item for the real product, not something faked here.

Two data sources feed the same pipeline:

- `analyze(data_dir, ...)`: reads sample_data/*.csv and *.json. No network,
  no credentials, no dependencies beyond the standard library.
- `analyze_resources(resources, iam_users, ...)`: the shared core, also
  called by `aws/collector.py` with data read live from a real AWS account
  via boto3 (only imported when that path is used; see cli.py --source live).

Both paths run identical rules and produce an identical Report shape.
"""

from __future__ import annotations

import csv
import json
from dataclasses import fields
from datetime import date
from pathlib import Path

from .credential_report import parse_credential_report
from .models import Finding, IamUser, Report, Resource
from .rules.carbon import build_carbon_estimate
from .rules.cost_rules import ALL_COST_RULES
from .rules.governance_rules import (
    ALL_GOVERNANCE_RESOURCE_RULES,
    rule_csrd_emissions_reporting,
    rule_iam_credential_hygiene,
)

_RESOURCE_FIELD_NAMES = {f.name for f in fields(Resource)}


def load_resources(data_dir: Path) -> list[Resource]:
    """Join cost_and_usage.csv (billing) with resource_inventory.json
    (config/utilization) on resource_id: the same two-source shape a real
    read-only AWS collector would use (Cost Explorer/CUR + describe-* calls)."""
    data_dir = Path(data_dir)

    costs: dict[str, float] = {}
    with (data_dir / "cost_and_usage.csv").open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            costs[row["resource_id"]] = costs.get(row["resource_id"], 0.0) + float(
                row["monthly_cost"]
            )

    inventory = json.loads(
        (data_dir / "resource_inventory.json").read_text(encoding="utf-8")
    )

    resources = []
    for item in inventory:
        resource_id = item["resource_id"]
        if resource_id not in costs:
            raise ValueError(
                f"{resource_id} appears in resource_inventory.json but has no "
                "matching line item in cost_and_usage.csv"
            )
        cost = costs[resource_id]
        if cost < 0:
            # Negative cost would flow straight through the savings-ratio
            # math in cost_rules.py/carbon.py and produce a nonsensical,
            # inflated "savings" figure instead of failing loudly.
            raise ValueError(
                f"{resource_id} has a negative monthly_cost ({cost}) in "
                "cost_and_usage.csv. Refusing to analyze untrusted/malformed data."
            )
        hours = item.get("hours_running_per_month")
        if hours is not None and hours < 0:
            raise ValueError(
                f"{resource_id} has a negative hours_running_per_month ({hours}) "
                "in resource_inventory.json."
            )
        kwargs = {k: v for k, v in item.items() if k in _RESOURCE_FIELD_NAMES}
        resources.append(Resource(monthly_cost=cost, **kwargs))
    return resources


def load_iam_users(data_dir: Path) -> list[IamUser]:
    """Load sample_data/iam_credential_report.csv if present. Uses the same
    parser a live collector uses on a real AWS credential report, so this
    file is exercised by the exact same code path (see credential_report.py)."""
    path = Path(data_dir) / "iam_credential_report.csv"
    if not path.exists():
        return []
    return parse_credential_report(path.read_text(encoding="utf-8"))


def run_cost_rules(resources: list[Resource]) -> list[Finding]:
    findings: list[Finding] = []
    for rule in ALL_COST_RULES:
        findings.extend(rule(resources))
    return findings


def run_governance_rules(
    resources: list[Resource], iam_users: list[IamUser], carbon
) -> list[Finding]:
    findings: list[Finding] = []
    for rule in ALL_GOVERNANCE_RESOURCE_RULES:
        findings.extend(rule(resources))
    findings.extend(rule_iam_credential_hygiene(iam_users))
    findings.extend(rule_csrd_emissions_reporting(carbon))
    return findings


def analyze_resources(
    resources: list[Resource],
    iam_users: list[IamUser] | None = None,
    company_name: str = "Sample Company",
) -> Report:
    """The shared analysis core. Takes already-collected data (from either
    sample files or a live AWS account) and runs the full rule pipeline."""
    iam_users = iam_users or []
    cost_findings = run_cost_rules(resources)
    carbon = build_carbon_estimate(resources, cost_findings)
    governance_findings = run_governance_rules(resources, iam_users, carbon)

    return Report(
        company_name=company_name,
        generated_on=date.today(),
        resources_analyzed=len(resources),
        findings=[*cost_findings, *governance_findings],
        carbon=carbon,
    )


def analyze(data_dir: Path, company_name: str = "Sample Company") -> Report:
    """Analyze the sample_data/ directory shape: cost_and_usage.csv,
    resource_inventory.json, and (optionally) iam_credential_report.csv."""
    resources = load_resources(data_dir)
    iam_users = load_iam_users(data_dir)
    return analyze_resources(resources, iam_users, company_name)
