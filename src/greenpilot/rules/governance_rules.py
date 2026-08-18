"""EU governance observations: GDPR data residency, NIS2 security posture,
and CSRD emissions-reporting relevance, matching the three subsections on
https://greenpilotai.com/sample-report.html.

These are deliberately framed as observations, not compliance verdicts. The
live product is explicit that it "flags configurations relevant to" these
regulations without replacing legal counsel, and this engine keeps the
same framing.
"""

from __future__ import annotations

from ..models import CarbonEstimate, Finding, IamUser, Resource

KEY_AGE_THRESHOLD_DAYS = 90
INACTIVE_USER_THRESHOLD_DAYS = 90

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
                        f"{r.resource_id} has no encryption at rest configured, a common "
                        "baseline control referenced under NIS2 risk-management measures."
                    ),
                    effort="low",
                    regulation="NIS2",
                )
            )
        if r.service == "S3" and r.versioning_enabled is False:
            findings.append(
                Finding(
                    resource_id=r.resource_id,
                    service=r.service,
                    category="governance",
                    title="Bucket versioning not enabled",
                    description=(
                        f"{r.resource_id} has no versioning configured. Without it, "
                        "an accidental delete or overwrite is unrecoverable, a gap "
                        "under NIS2 resilience and incident-recovery expectations."
                    ),
                    effort="low",
                    regulation="NIS2",
                )
            )
    return findings


def rule_iam_credential_hygiene(users: list[IamUser]) -> list[Finding]:
    """Credential hygiene, from a real AWS IAM credential report: root
    account access keys, missing MFA, stale access keys, and inactive
    console users. These are standard NIS2 risk-management controls, and
    the same checks a real AWS security review starts with."""
    findings = []
    for u in users:
        if u.is_root and (u.key1_active or u.key2_active):
            findings.append(
                Finding(
                    resource_id=u.user,
                    service="ACCOUNT",
                    category="governance",
                    title="Root account has active access keys",
                    description=(
                        "The AWS root account has at least one active access key. "
                        "AWS recommends the root account never hold access keys; "
                        "this is a critical NIS2 risk-management finding."
                    ),
                    effort="low",
                    regulation="NIS2",
                )
            )
        if u.is_root and not u.mfa_active:
            findings.append(
                Finding(
                    resource_id=u.user,
                    service="ACCOUNT",
                    category="governance",
                    title="Root account has no MFA",
                    description=(
                        "The AWS root account has no multi-factor authentication "
                        "configured. This is a critical NIS2 risk-management finding."
                    ),
                    effort="low",
                    regulation="NIS2",
                )
            )
        if u.has_console_access and not u.mfa_active and not u.is_root:
            findings.append(
                Finding(
                    resource_id=u.user,
                    service="ACCOUNT",
                    category="governance",
                    title="Console user without MFA",
                    description=(
                        f"{u.user} has console access but no MFA configured, a "
                        "baseline NIS2 access-control gap."
                    ),
                    effort="low",
                    regulation="NIS2",
                )
            )
        for key_active, key_age, label in (
            (u.key1_active, u.key1_age_days, "Access key 1"),
            (u.key2_active, u.key2_age_days, "Access key 2"),
        ):
            if key_active and key_age is not None and key_age > KEY_AGE_THRESHOLD_DAYS:
                findings.append(
                    Finding(
                        resource_id=u.user,
                        service="ACCOUNT",
                        category="governance",
                        title=f"{label} is {key_age} days old",
                        description=(
                            f"{u.user}'s {label.lower()} has not been rotated in over "
                            f"{KEY_AGE_THRESHOLD_DAYS} days. Regular rotation is a "
                            "standard NIS2 credential-hygiene control."
                        ),
                        effort="low",
                        regulation="NIS2",
                    )
                )
        if (
            not u.is_root
            and u.has_console_access
            and u.days_since_password_used is not None
            and u.days_since_password_used > INACTIVE_USER_THRESHOLD_DAYS
        ):
            findings.append(
                Finding(
                    resource_id=u.user,
                    service="ACCOUNT",
                    category="governance",
                    title="Inactive console user",
                    description=(
                        f"{u.user} has not logged in for "
                        f"{u.days_since_password_used} days but still has console "
                        "access. Review whether the account should be deactivated."
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
