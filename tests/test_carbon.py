from greenpilot.models import Finding, Resource
from greenpilot.rules.carbon import (
    build_carbon_estimate,
    estimate_current_co2e_tonnes_per_year,
    resource_co2e_kg_per_month,
    resource_kwh_per_month,
)


def test_ec2_kwh_scales_with_known_instance_family_and_hours():
    r = Resource(
        resource_id="ec2-1",
        service="EC2",
        resource_type="m5.xlarge",
        region="eu-west-1",
        monthly_cost=100.0,
        hours_running_per_month=730,
    )
    # m5 family = 35W average -> 35 * 730 / 1000 kWh
    assert resource_kwh_per_month(r) == 35.0 * 730 / 1000.0


def test_rds_multi_az_doubles_power_draw():
    single = Resource(
        resource_id="rds-1",
        service="RDS",
        resource_type="db.m5.large",
        region="eu-west-1",
        monthly_cost=100.0,
        multi_az=False,
    )
    doubled = Resource(
        resource_id="rds-2",
        service="RDS",
        resource_type="db.m5.large",
        region="eu-west-1",
        monthly_cost=100.0,
        multi_az=True,
    )
    assert resource_kwh_per_month(doubled) == resource_kwh_per_month(single) * 2


def test_unknown_region_falls_back_to_default_intensity():
    r = Resource(
        resource_id="ec2-unknown-region",
        service="EC2",
        resource_type="m5.large",
        region="ap-southeast-9",  # not in the lookup table
        monthly_cost=100.0,
        hours_running_per_month=730,
    )
    kg = resource_co2e_kg_per_month(r)
    assert kg > 0


def test_current_estimate_is_positive_for_any_running_fleet():
    resources = [
        Resource(
            resource_id="ec2-1",
            service="EC2",
            resource_type="m5.large",
            region="eu-west-1",
            monthly_cost=100.0,
            hours_running_per_month=730,
        )
    ]
    assert estimate_current_co2e_tonnes_per_year(resources) > 0


def test_reduction_potential_is_bounded_by_current_footprint():
    r = Resource(
        resource_id="ec2-idle",
        service="EC2",
        resource_type="m5.large",
        region="eu-west-1",
        monthly_cost=100.0,
        hours_running_per_month=730,
    )
    # A finding that "saves" the resource's entire monthly cost should not
    # produce a reduction estimate larger than the resource's own footprint.
    finding = Finding(
        resource_id="ec2-idle",
        service="EC2",
        category="cost",
        title="fully removable",
        description="entire resource removed",
        monthly_savings=100.0,
    )
    estimate = build_carbon_estimate([r], [finding])
    assert estimate.reduction_tonnes_co2e_per_year <= estimate.current_tonnes_co2e_per_year
