# Security Model

This documents how the security posture described on [greenpilotai.com/security.html](https://greenpilotai.com/security.html) maps onto this repository — what's a concrete artifact here versus what's a claim about the live product this repo doesn't (and can't) fully implement.

## Access model this engine assumes

The live product's stated model: **read-only by default**, **only the IAM permissions necessary** to analyze usage/cost/config data, **customer-revocable at any time**, **no long-term credential storage beyond operational necessity**, **no application data or end-user personal data collected**.

[`iam/read-only-collector-policy.json`](../iam/read-only-collector-policy.json) is a concrete least-privilege IAM policy scoped to exactly what this engine's data model needs to populate `resource_inventory.json` and `cost_and_usage.csv` from a real account:

- **Cost Explorer** (`ce:Get*`) for billing data
- **CloudWatch** (`cloudwatch:GetMetricData`/`GetMetricStatistics`/`ListMetrics`) for the CPU utilization the idle/underutilized EC2 rule needs
- **`Describe*`/`List*`/`Get*`** calls on EC2, RDS, and S3 for configuration state (instance types, attachment, storage class, public-access/encryption flags)
- **`sts:GetCallerIdentity`** for a basic connectivity check

There is no `Put*`, `Delete*`, `Terminate*`, `Modify*`, or `Create*` action anywhere in the Allow statement. A second statement adds an **explicit `Deny`** on the specific destructive actions closest to what this engine touches (terminate/stop/delete/modify on EC2/RDS/S3, plus a blanket `iam:*`/`organizations:*` deny). That's redundant with IAM's default-deny in isolation, but it's a real guardrail in practice: if this policy is ever attached to a role alongside something broader, the explicit `Deny` still wins and blocks those actions regardless.

Nothing in `src/greenpilot/` calls the AWS API at all — v1 only reads local files (see [docs/architecture.md](architecture.md)) — so this policy documents what a real collector *would* need, matching the "documented permission lists before onboarding" the live site describes, not something this code currently exercises.

## Data handled by this repo

- **Committed data is entirely synthetic.** `sample_data/*.csv`/`*.json` are hand-authored fictional resources (see [README](../README.md)) — no real AWS account, billing data, or customer information has ever touched this repository.
- **No secrets, ever.** No `.env`, no credentials, no API keys, no `.aws/` config — checked at commit time (see below) and enforced going forward via `.gitignore` and GitHub's secret scanning (on by default for public repos).
- **Output escaping.** `report.py` escapes every resource-derived field (`resource_id`, `title`, `description`, `rollback`, `--company`) before interpolating it into the Markdown report — `|` (which would corrupt the findings table) and `<`/`>`/`&` (which would pass raw HTML/script through unescaped into any future HTML renderer of this Markdown, i.e. the roadmap's web dashboard). See `_escape_md` in [`report.py`](../src/greenpilot/report.py) and `tests/test_report_escaping.py`.
- **Input validation.** `engine.load_resources` rejects negative costs and negative running-hours outright rather than letting them flow into the savings/carbon math and produce a silently wrong (and inflated) report — see `tests/test_engine_validation.py`.

## Repo-level controls

- **[CodeQL](../.github/workflows/codeql.yml)** — static analysis on every push/PR and weekly, using GitHub's default Python query suite.
- **[Dependabot](../.github/dependabot.yml)** — automated updates for the (currently single, `pytest`) Python dependency and for the GitHub Actions themselves.
- **CI (`pytest`)** enforces the rule/engine/escaping tests above on every push — a regression in any of this can't land on `main` silently.
- **No write-capable GitHub Actions permissions and no secrets used** in any workflow — a malicious PR from a fork can't exfiltrate anything, because there's nothing sensitive for it to reach.

## What's explicitly *not* covered here

Matching the live site's own honesty about pilot-stage limitations:

- No ISO 27001 / SOC 2 — not claimed, not applicable to a portfolio repo.
- No penetration test has been run against this code.
- Encryption-in-transit/at-rest is not applicable — this is a local CLI tool with no network calls and no server component.
- RBAC, automated rollback, and audit logging are live-product roadmap items, not something this repo implements.

## Reporting a concern

See [SECURITY.md](../SECURITY.md).
