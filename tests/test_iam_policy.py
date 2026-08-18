"""Structural checks on iam/read-only-collector-policy.json.

This isn't a full IAM policy simulator, just a guardrail so the one
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

# iam:GenerateCredentialReport and iam:GetCredentialReport are the two
# exceptions: report generation/retrieval, not user or policy management.
# Everything else under iam: must stay out of the Allow list.
ALLOWED_IAM_ACTIONS = {"iam:GenerateCredentialReport", "iam:GetCredentialReport"}


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
            assert (
                READ_ONLY_VERB.match(action)
                or action == "sts:GetCallerIdentity"
                or action in ALLOWED_IAM_ACTIONS
            ), f"{action} does not look like a read-only (Get/List/Describe) action"


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
            if action.startswith("iam:"):
                assert action in ALLOWED_IAM_ACTIONS, (
                    f"{action} is an IAM permission beyond the credential-report "
                    "exception; must never be Allow-listed"
                )
            assert not action.startswith("organizations:"), "must never grant Organizations permissions"


def test_iam_deny_covers_common_destructive_verbs_by_prefix(policy):
    """The Deny statement uses verb-prefix wildcards (iam:Create*, iam:Delete*,
    ...) instead of a single iam:*, specifically so the two Allow-listed
    read actions above aren't shadowed by their own guardrail. Confirm a
    handful of real destructive actions actually match one of those prefixes."""
    deny_statements = [s for s in policy["Statement"] if s["Effect"] == "Deny"]
    deny_patterns = [a for s in deny_statements for a in s["Action"] if a.startswith("iam:")]
    assert deny_patterns, "expected at least one iam: deny pattern"

    destructive_examples = [
        "iam:CreateUser",
        "iam:DeleteUser",
        "iam:PutUserPolicy",
        "iam:UpdateAssumeRolePolicy",
        "iam:AttachUserPolicy",
        "iam:DeactivateMFADevice",
    ]
    for action in destructive_examples:
        matched = any(
            pattern.endswith("*") and action.startswith(pattern[:-1]) for pattern in deny_patterns
        )
        assert matched, f"{action} isn't covered by any iam: deny pattern: {deny_patterns}"

    # And the two Allow-listed read actions must NOT be swallowed by those
    # same prefixes (this is the whole reason iam:* was replaced).
    for allowed in ALLOWED_IAM_ACTIONS:
        matched = any(
            pattern.endswith("*") and allowed.startswith(pattern[:-1]) for pattern in deny_patterns
        )
        assert not matched, f"{allowed} is shadowed by a deny pattern: {deny_patterns}"
