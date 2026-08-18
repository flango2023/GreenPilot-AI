"""Untrusted-data handling in the report renderer.

resource_inventory.json / cost_and_usage.csv model what a real AWS
collector would read out of someone's account — tags, instance types,
regions. This engine doesn't get to assume that data is clean.
"""

import datetime
import json
import re
from pathlib import Path

from greenpilot.models import CarbonEstimate, Report, Resource
from greenpilot.report import _escape_md, render_markdown
from greenpilot.rules.cost_rules import rule_idle_or_underutilized_ec2


def test_escape_md_neutralizes_table_and_html_breaking_characters():
    raw = "m5.large | evil <script>alert(1)</script> `backtick`"
    escaped = _escape_md(raw)

    assert "|" not in escaped.replace("\\|", "")
    assert "<script>" not in escaped
    assert "&lt;script&gt;" in escaped
    assert "\\`" in escaped


def test_malicious_resource_type_does_not_corrupt_the_report_table(tmp_path):
    # A resource_type is attacker/customer-controlled data (it's just an AWS
    # tag/label in the real product) that flows straight into a Finding's
    # title via an f-string in cost_rules.py. Confirm the render step still
    # neutralizes it even though the rule layer doesn't.
    resource = Resource(
        resource_id="ec2-evil | injected <img src=x onerror=alert(1)>",
        service="EC2",
        resource_type="m5.large",
        region="eu-west-1",
        monthly_cost=100.0,
        avg_cpu_utilization_pct=1.0,
    )
    findings = rule_idle_or_underutilized_ec2([resource])
    assert len(findings) == 1

    report = Report(
        company_name="Acme | <b>Corp</b>",
        generated_on=datetime.date(2026, 1, 1),
        resources_analyzed=1,
        findings=findings,
        carbon=CarbonEstimate(current_tonnes_co2e_per_year=1.0, reduction_tonnes_co2e_per_year=0.1),
    )
    markdown = render_markdown(report)

    assert "<img src=x onerror=alert(1)>" not in markdown
    assert "<b>Corp</b>" not in markdown
    # The findings table row count must stay correct: an unescaped `|`
    # in resource_id would have split into extra (broken) table cells.
    table_rows = [
        line
        for line in markdown.splitlines()
        if line.startswith("| ec2-evil") or line.startswith("| ec2-evil ")
    ]
    assert len(table_rows) == 1
    # An unescaped `|` acts as a column delimiter; the injected one must
    # come through as the escaped literal `\|` instead, leaving exactly the
    # 7 real delimiters for a 6-column row.
    unescaped_pipes = len(re.findall(r"(?<!\\)\|", table_rows[0]))
    assert unescaped_pipes == 7
    assert "\\|" in table_rows[0]


def test_committed_sample_data_has_no_markdown_or_html_breaking_characters():
    """The sample data ships as-is in the public repo; keep it clean so the
    committed reports/sample_report.md stays a trustworthy example."""
    data_dir = Path(__file__).resolve().parent.parent / "sample_data"
    inventory = json.loads((data_dir / "resource_inventory.json").read_text())
    for item in inventory:
        for value in item.values():
            if isinstance(value, str):
                assert "|" not in value
                assert "<" not in value
