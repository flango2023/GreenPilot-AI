from datetime import datetime, timezone

from greenpilot.credential_report import parse_credential_report

NOW = datetime(2026, 8, 18, tzinfo=timezone.utc)

HEADER = (
    "user,arn,user_creation_time,password_enabled,password_last_used,"
    "password_last_changed,password_next_rotation,mfa_active,"
    "access_key_1_active,access_key_1_last_rotated,access_key_1_last_used_date,"
    "access_key_2_active,access_key_2_last_rotated,access_key_2_last_used_date,"
    "cert_1_active,cert_2_active\n"
)


def _row(**overrides) -> str:
    defaults = {
        "user": "alice",
        "arn": "arn:aws:iam::123456789012:user/alice",
        "user_creation_time": "2023-01-01T00:00:00+00:00",
        "password_enabled": "true",
        "password_last_used": "2026-08-17T00:00:00+00:00",
        "password_last_changed": "2023-01-01T00:00:00+00:00",
        "password_next_rotation": "not_supported",
        "mfa_active": "true",
        "access_key_1_active": "false",
        "access_key_1_last_rotated": "N/A",
        "access_key_1_last_used_date": "N/A",
        "access_key_2_active": "false",
        "access_key_2_last_rotated": "N/A",
        "access_key_2_last_used_date": "N/A",
        "cert_1_active": "false",
        "cert_2_active": "false",
    }
    defaults.update(overrides)
    return ",".join(str(defaults[k]) for k in defaults) + "\n"


def test_parses_basic_user_fields():
    csv_text = HEADER + _row()
    users = parse_credential_report(csv_text, now=NOW)
    assert len(users) == 1
    u = users[0]
    assert u.user == "alice"
    assert u.is_root is False
    assert u.mfa_active is True
    assert u.has_console_access is True


def test_root_account_is_flagged_by_username():
    csv_text = HEADER + _row(user="<root_account>")
    users = parse_credential_report(csv_text, now=NOW)
    assert users[0].is_root is True


def test_access_key_age_is_computed_in_days():
    csv_text = HEADER + _row(
        access_key_1_active="true", access_key_1_last_rotated="2026-05-01T00:00:00+00:00"
    )
    users = parse_credential_report(csv_text, now=NOW)
    assert users[0].key1_active is True
    assert users[0].key1_age_days == (NOW - datetime(2026, 5, 1, tzinfo=timezone.utc)).days


def test_not_available_markers_become_none():
    csv_text = HEADER + _row(password_last_used="N/A", access_key_1_last_rotated="no_information")
    users = parse_credential_report(csv_text, now=NOW)
    assert users[0].days_since_password_used is None
    assert users[0].key1_age_days is None


def test_committed_sample_credential_report_parses_cleanly():
    from pathlib import Path

    path = (
        Path(__file__).resolve().parent.parent
        / "sample_data"
        / "iam_credential_report.csv"
    )
    users = parse_credential_report(path.read_text())
    assert len(users) == 5
    assert any(u.is_root for u in users)
