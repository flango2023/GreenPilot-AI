"""Render a Report to Markdown, in the same shape as
https://greenpilotai.com/sample-report.html: an executive summary, a cloud
waste findings table, a prioritized action plan, a carbon impact estimate,
and EU governance observations grouped by regulation.
"""

from __future__ import annotations

from .models import Report

_REGULATION_LABELS = {
    "GDPR": "Data Residency (GDPR)",
    "NIS2": "Security Posture (NIS2)",
    "CSRD": "Emissions Reporting (CSRD)",
}


def render_markdown(report: Report) -> str:
    lines: list[str] = []
    w = lines.append

    w(f"# GreenPilot AI — Cloud Assessment Report\n")
    w(f"**Company:** {report.company_name}  ")
    w(f"**Generated:** {report.generated_on.isoformat()}  ")
    w(f"**Resources analyzed:** {report.resources_analyzed}  ")
    w(f"**Findings flagged:** {len(report.findings)}\n")

    w("## Executive Summary\n")
    w(f"- **€{report.monthly_savings_total:,.2f}** estimated monthly savings potential")
    w(f"- **€{report.annual_savings_total:,.2f}** estimated annual savings potential")
    w(
        f"- **{report.carbon.reduction_tonnes_co2e_per_year:.2f} t** estimated "
        "CO2e reduction / year"
    )
    services_flagged = {f.service for f in report.cost_findings}
    w(
        f"- **{len(report.cost_findings)}** cost-waste findings across "
        f"{len(services_flagged)} AWS services\n"
    )

    w("## Cloud Waste Findings\n")
    w("| Resource | Service | Finding | Monthly Cost Today | Monthly Savings | Effort |")
    w("|---|---|---|---:|---:|---|")
    for f in report.cost_findings:
        current_cost = (
            f.optimized_monthly_cost + f.monthly_savings
            if f.optimized_monthly_cost is not None
            else f.monthly_savings
        )
        w(
            f"| {f.resource_id} | {f.service} | {f.title} | "
            f"€{current_cost:,.2f} | €{f.monthly_savings:,.2f} | {f.effort} |"
        )
    w("")

    w("## Prioritized Action Plan\n")
    for i, f in enumerate(report.action_plan, start=1):
        w(f"{i}. **{f.title}** ({f.resource_id}) — save ~€{f.monthly_savings:,.2f}/mo, "
          f"effort: {f.effort}")
        w(f"   - {f.description}")
        if f.rollback:
            w(f"   - Rollback: {f.rollback}")
    w("")

    w("## Carbon Impact Estimate\n")
    w(f"- **{report.carbon.current_tonnes_co2e_per_year:.2f} t** estimated current CO2e / year")
    w(
        f"- **{report.carbon.reduction_tonnes_co2e_per_year:.2f} t** potential "
        "reduction / year if all findings above are actioned"
    )
    w(f"- {report.carbon.methodology_note}\n")

    w("## EU Governance Observations\n")
    for regulation, label in _REGULATION_LABELS.items():
        notes = [f for f in report.governance_findings if f.regulation == regulation]
        if not notes:
            continue
        w(f"### {label}\n")
        for f in notes:
            w(f"- **{f.title}** ({f.resource_id}): {f.description}")
        w("")

    w(
        "---\n*This is a demo report generated from synthetic sample data by the "
        "open-source engine in this repository — see [sample_data/](../sample_data) "
        "and [docs/carbon-methodology.md](../docs/carbon-methodology.md). It mirrors "
        "the report structure at [greenpilotai.com/sample-report.html]"
        "(https://greenpilotai.com/sample-report.html); figures here are illustrative, "
        "not from a real customer account.*"
    )

    return "\n".join(lines) + "\n"
