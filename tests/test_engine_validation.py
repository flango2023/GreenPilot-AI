"""Malformed/adversarial input handling for engine.load_resources.

cost_and_usage.csv and resource_inventory.json are the two files a real
collector would populate from live AWS data — this engine has to fail
loudly on nonsensical values instead of quietly producing a wrong report.
"""

import csv
import json

import pytest

from greenpilot.engine import load_resources


def _write_data_dir(tmp_path, rows, inventory):
    csv_path = tmp_path / "cost_and_usage.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["resource_id", "service", "region", "monthly_cost"])
        writer.writeheader()
        writer.writerows(rows)
    (tmp_path / "resource_inventory.json").write_text(json.dumps(inventory))
    return tmp_path


def test_negative_monthly_cost_is_rejected(tmp_path):
    rows = [{"resource_id": "ec2-1", "service": "EC2", "region": "eu-west-1", "monthly_cost": "-50"}]
    inventory = [{"resource_id": "ec2-1", "service": "EC2", "resource_type": "m5.large", "region": "eu-west-1"}]
    data_dir = _write_data_dir(tmp_path, rows, inventory)

    with pytest.raises(ValueError, match="negative monthly_cost"):
        load_resources(data_dir)


def test_negative_hours_running_is_rejected(tmp_path):
    rows = [{"resource_id": "ec2-1", "service": "EC2", "region": "eu-west-1", "monthly_cost": "50"}]
    inventory = [
        {
            "resource_id": "ec2-1",
            "service": "EC2",
            "resource_type": "m5.large",
            "region": "eu-west-1",
            "hours_running_per_month": -1,
        }
    ]
    data_dir = _write_data_dir(tmp_path, rows, inventory)

    with pytest.raises(ValueError, match="negative hours_running_per_month"):
        load_resources(data_dir)


def test_resource_missing_from_billing_data_is_rejected(tmp_path):
    rows = []
    inventory = [{"resource_id": "ec2-orphan", "service": "EC2", "resource_type": "m5.large", "region": "eu-west-1"}]
    data_dir = _write_data_dir(tmp_path, rows, inventory)

    with pytest.raises(ValueError, match="no matching line item"):
        load_resources(data_dir)
