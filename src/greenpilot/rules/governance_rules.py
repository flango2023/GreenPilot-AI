"""EU governance observations — GDPR data residency, NIS2 security posture,
and CSRD emissions-reporting relevance, matching the three subsections on
https://greenpilotai.com/sample-report.html.

These are deliberately framed as *observations*, not compliance verdicts —
the live product is explicit that it "flags configurations relevant to"
these regulations without replacing legal counsel, and this engine keeps
the same framing.
"""

from __future__ import annotations

from ..models import CarbonEstimate, Finding, Resource

EU_EEA_REGIONS = {
    "eu-west-1",
    "eu-west-2",
    "eu-west-3",
    "eu-central-1",
    "eu-central-2",
    "eu-north-1",
    "eu-south-1",
    "eu-south-2",
}


def rule_gdpr_data_residency(resources: list[Resource]) -> list[Finding]:
    findings = []
    for r in resources:
        if not r.contains_personal_data or r.region in EU_EEA_REGIONS:
            continue
        findings.append(
            Finding(
                resource_id=r.resource_id,
                service=r.service,
                category="governance",
                title="Personal data stored outside the EU/EEA",
                description=(
                    f"{r.resource_id} is tagged as containing personal data but is "
                    f"provisioned in '{r.region}', outside the EU/EEA. Worth reviewing "
                    "against your GDPR data-residency and transfer-mechanism obligations."
                ),
                effort="low",
                regulation="GDPR",
            )
        )
    return findings


def rule_nis2_security_posture(resources: list[Resource]) -> list[Finding]:
    findings = []
    for r in resources:
        if r.publicly_accessible:
            findings.append(
                Finding(
                    resource_id=r.resource_id,
                    service=r.service,
                    category="governance",
                    title="Publicly accessible resource",
                    description=(
                        f"{r.resource_id} is reachable from the public internet. "
                        "Under NIS2's risk-management duties, confirm this is intentional "
                        "and covered by your access-control and monitoring baseline."
                    ),
                    effort="low",
                    regulation="NIS2",
                )
            )
        if r.encrypted is False:
            findings.append(
                Finding(
                    resource_id=r.resource_id,
                    service=r.service,
                    category="governance",
                    title="Storage not encrypted at rest",
                    description=(
                        f"{r.resource_id} has no encryption at rest configured — a common "
                        "baseline control referenced under NIS2 risk-management measures."
                    ),
                    effort="low",
                    regulation="NIS2",
                )
            )
    return findings


def rule_csrd_emissions_reporting(carbon: CarbonEstimate) -> list[Finding]:
    """One account-level note: cloud emissions are in-scope for CSRD Scope 2/3
    reporting, and this report is a starting point for that inventory."""
    return [
        Finding(
            resource_id="ACCOUNT",
            service="ACCOUNT",
            category="governance",
            title="Cloud emissions are in-scope for CSRD reporting",
            description=(
                "Estimated cloud energy use for this account is "
                f"{carbon.current_tonnes_co2e_per_year:.2f} t CO2e/year, relevant to "
                "Scope 2/3 disclosures under the Corporate Sustainability Reporting "
                "Directive. Treat this as a starting estimate, not an audited figure."
            ),
            effort="low",
            regulation="CSRD",
        )
    ]


ALL_GOVERNANCE_RESOURCE_RULES = [
    rule_gdpr_data_residency,
    rule_nis2_security_posture,
]
