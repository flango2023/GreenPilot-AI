from greenpilot.models import CarbonEstimate, IamUser, Resource
from greenpilot.rules.governance_rules import (
    rule_csrd_emissions_reporting,
    rule_gdpr_data_residency,
    rule_iam_credential_hygiene,
    rule_nis2_security_posture,
)


def test_personal_data_outside_eu_is_flagged():
    r = Resource(
        resource_id="s3-us",
        service="S3",
        resource_type="STANDARD bucket",
        region="us-east-1",
        monthly_cost=140.0,
        contains_personal_data=True,
    )
    findings = rule_gdpr_data_residency([r])
    assert len(findings) == 1
    assert findings[0].regulation == "GDPR"


def test_personal_data_inside_eu_is_not_flagged():
    r = Resource(
        resource_id="s3-eu",
        service="S3",
        resource_type="STANDARD bucket",
        region="eu-west-1",
        monthly_cost=140.0,
        contains_personal_data=True,
    )
    assert rule_gdpr_data_residency([r]) == []


def test_resource_without_personal_data_is_never_flagged_regardless_of_region():
    r = Resource(
        resource_id="s3-us-2",
        service="S3",
        resource_type="STANDARD bucket",
        region="us-east-1",
        monthly_cost=140.0,
        contains_personal_data=False,
    )
    assert rule_gdpr_data_residency([r]) == []


def test_public_and_unencrypted_resource_raises_two_nis2_findings():
    r = Resource(
        resource_id="ec2-exposed",
        service="EC2",
        resource_type="m5.large",
        region="eu-west-1",
        monthly_cost=100.0,
        publicly_accessible=True,
        encrypted=False,
    )
    findings = rule_nis2_security_posture([r])
    assert len(findings) == 2
    assert all(f.regulation == "NIS2" for f in findings)


def test_private_encrypted_resource_is_not_flagged():
    r = Resource(
        resource_id="ec2-safe",
        service="EC2",
        resource_type="m5.large",
        region="eu-west-1",
        monthly_cost=100.0,
        publicly_accessible=False,
        encrypted=True,
    )
    assert rule_nis2_security_posture([r]) == []


def test_root_account_with_active_key_and_no_mfa_raises_two_critical_findings():
    root = IamUser(
        user="<root_account>",
        is_root=True,
        mfa_active=False,
        has_console_access=True,
        key1_active=True,
        key1_age_days=10,
    )
    findings = rule_iam_credential_hygiene([root])
    titles = {f.title for f in findings}
    assert "Root account has active access keys" in titles
    assert "Root account has no MFA" in titles
    assert all(f.regulation == "NIS2" for f in findings)


def test_console_user_without_mfa_is_flagged_but_not_as_root_issue():
    user = IamUser(
        user="bob", is_root=False, mfa_active=False, has_console_access=True
    )
    findings = rule_iam_credential_hygiene([user])
    assert len(findings) == 1
    assert findings[0].title == "Console user without MFA"


def test_service_account_without_console_access_is_not_flagged_for_mfa():
    service_account = IamUser(
        user="ci-deploy",
        is_root=False,
        mfa_active=False,
        has_console_access=False,
        key1_active=True,
        key1_age_days=5,
    )
    findings = rule_iam_credential_hygiene([service_account])
    assert all(f.title != "Console user without MFA" for f in findings)


def test_stale_access_key_is_flagged_over_threshold_only():
    fresh = IamUser(
        user="fresh-key", is_root=False, mfa_active=True, has_console_access=True,
        key1_active=True, key1_age_days=30,
    )
    stale = IamUser(
        user="stale-key", is_root=False, mfa_active=True, has_console_access=True,
        key1_active=True, key1_age_days=200,
    )
    assert rule_iam_credential_hygiene([fresh]) == []
    findings = rule_iam_credential_hygiene([stale])
    assert len(findings) == 1
    assert "200 days old" in findings[0].title


def test_inactive_console_user_is_flagged():
    user = IamUser(
        user="former-contractor", is_root=False, mfa_active=True,
        has_console_access=True, days_since_password_used=400,
    )
    findings = rule_iam_credential_hygiene([user])
    assert any(f.title == "Inactive console user" for f in findings)


def test_clean_user_raises_nothing():
    user = IamUser(
        user="alice", is_root=False, mfa_active=True, has_console_access=True,
        days_since_password_used=1, key1_active=True, key1_age_days=10,
    )
    assert rule_iam_credential_hygiene([user]) == []


def test_csrd_note_reports_current_footprint():
    carbon = CarbonEstimate(
        current_tonnes_co2e_per_year=1.23, reduction_tonnes_co2e_per_year=0.5
    )
    findings = rule_csrd_emissions_reporting(carbon)
    assert len(findings) == 1
    assert findings[0].regulation == "CSRD"
    assert "1.23" in findings[0].description
