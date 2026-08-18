from greenpilot.models import CarbonEstimate, Resource
from greenpilot.rules.governance_rules import (
    rule_csrd_emissions_reporting,
    rule_gdpr_data_residency,
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


def test_csrd_note_reports_current_footprint():
    carbon = CarbonEstimate(
        current_tonnes_co2e_per_year=1.23, reduction_tonnes_co2e_per_year=0.5
    )
    findings = rule_csrd_emissions_reporting(carbon)
    assert len(findings) == 1
    assert findings[0].regulation == "CSRD"
    assert "1.23" in findings[0].description
