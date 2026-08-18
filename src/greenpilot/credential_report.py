"""Parser for the AWS IAM credential report (`iam:GetCredentialReport`).

This has no dependency on boto3: it only parses the CSV text the report
comes as. That means the exact same function handles two sources:

- A live AWS account (`aws/collector.py` calls `iam:GenerateCredentialReport`
  and `iam:GetCredentialReport`, then hands the decoded CSV text here).
- The demo data (`sample_data/iam_credential_report.csv`, written in the
  same column format AWS itself uses, so this parser is exercised by
  `pytest` without needing an AWS account or network access).

Column reference: https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_getting-report.html
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from .models import IamUser

_NOT_AVAILABLE = {"", "N/A", "no_information", "not_supported"}


def _parse_timestamp(value: str) -> datetime | None:
    if value in _NOT_AVAILABLE:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _days_since(value: str, now: datetime) -> int | None:
    dt = _parse_timestamp(value)
    return (now - dt).days if dt else None


def parse_credential_report(csv_text: str, now: datetime | None = None) -> list[IamUser]:
    """Parse raw AWS IAM credential report CSV text into `IamUser` records."""
    now = now or datetime.now(timezone.utc)
    users = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        users.append(
            IamUser(
                user=row["user"],
                is_root=row["user"] == "<root_account>",
                mfa_active=row.get("mfa_active") == "true",
                has_console_access=row.get("password_enabled") == "true",
                days_since_password_used=_days_since(row.get("password_last_used", ""), now),
                key1_active=row.get("access_key_1_active") == "true",
                key1_age_days=_days_since(row.get("access_key_1_last_rotated", ""), now),
                key2_active=row.get("access_key_2_active") == "true",
                key2_age_days=_days_since(row.get("access_key_2_last_rotated", ""), now),
            )
        )
    return users
