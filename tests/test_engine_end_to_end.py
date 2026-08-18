from pathlib import Path

from greenpilot.engine import analyze
from greenpilot.report import render_markdown

SAMPLE_DATA = Path(__file__).resolve().parent.parent / "sample_data"


def test_analyze_runs_end_to_end_on_the_committed_sample_data():
    report = analyze(SAMPLE_DATA, company_name="Acme Tech Solutions GmbH")

    assert report.resources_analyzed == 15
    # Every rule type in the sample data should produce at least one finding.
    assert len(report.cost_findings) >= 8
    assert len(report.governance_findings) >= 3
    assert report.monthly_savings_total > 0
    assert report.annual_savings_total == round(report.monthly_savings_total * 12, 2)
    assert report.carbon.current_tonnes_co2e_per_year > 0
    assert 0 < report.carbon.reduction_tonnes_co2e_per_year <= report.carbon.current_tonnes_co2e_per_year


def test_action_plan_is_sorted_by_savings_descending():
    report = analyze(SAMPLE_DATA)
    savings = [f.monthly_savings for f in report.action_plan]
    assert savings == sorted(savings, reverse=True)


def test_report_renders_to_markdown_with_expected_sections():
    report = analyze(SAMPLE_DATA, company_name="Acme Tech Solutions GmbH")
    markdown = render_markdown(report)

    assert "# GreenPilot AI — Cloud Assessment Report" in markdown
    assert "Acme Tech Solutions GmbH" in markdown
    assert "## Executive Summary" in markdown
    assert "## Cloud Waste Findings" in markdown
    assert "## Prioritized Action Plan" in markdown
    assert "## Carbon Impact Estimate" in markdown
    assert "## EU Governance Observations" in markdown
