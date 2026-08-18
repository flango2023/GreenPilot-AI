"""Structural checks on iam/read-only-collector-policy.json.

This isn't a full IAM policy simulator — just a guardrail so the one
security artifact in this repo that claims to be "least privilege" can't
silently regress into something broader without a test failing.
"""

import json
import re
from pathlib import Path

import pytest

POLICY_PATH = (
    Path(__file__).resolve().parent.parent / "iam" / "read-only-collector-policy.json"
)

READ_ONLY_VERB = re.compile(r"^[a-zA-Z0-9]+:(Get|List|Describe)[A-Za-z]*$")


@pytest.fixture()
def policy():
    return json.loads(POLICY_PATH.read_text())


def test_policy_is_valid_json_with_expected_version(policy):
    assert policy["Version"] == "2012-10-17"
    assert isinstance(policy["Statement"], list) and policy["Statement"]


def test_every_allow_action_is_a_read_only_verb(policy):
    allow_statements = [s for s in policy["Statement"] if s["Effect"] == "Allow"]
    assert allow_statements, "policy must contain at least one Allow statement"

    for statement in allow_statements:
        for action in statement["Action"]:
            assert action != "*", "no blanket '*' action is allowed"
            assert not action.endswith(":*"), f"no service-wide wildcard: {action}"
            assert READ_ONLY_VERB.match(action) or action == "sts:GetCallerIdentity", (
                f"{action} does not look like a read-only (Get/List/Describe) action"
            )


def test_policy_explicitly_denies_destructive_actions(policy):
    deny_statements = [s for s in policy["Statement"] if s["Effect"] == "Deny"]
    assert deny_statements, "policy should carry an explicit Deny guardrail"

    denied_actions = {a for s in deny_statements for a in s["Action"]}
    # A representative sample of destructive verbs this policy is meant to block.
    for expected in (
        "ec2:TerminateInstances",
        "rds:DeleteDBInstance",
        "s3:DeleteBucket",
        "s3:PutObject",
    ):
        assert expected in denied_actions, f"expected {expected} to be explicitly denied"


def test_no_statement_grants_iam_or_organizations_write_access(policy):
    for statement in policy["Statement"]:
        if statement["Effect"] != "Allow":
            continue
        for action in statement["Action"]:
            assert not action.startswith("iam:"), "must never grant IAM permissions"
            assert not action.startswith("organizations:"), "must never grant Organizations permissions"
