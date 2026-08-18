# Security Model

This documents how the security posture described on [greenpilotai.com/security.html](https://greenpilotai.com/security.html) maps onto this repository: what is a concrete artifact here, versus what is a claim about the live product that this repo does not (and cannot) fully implement.

## Access model this engine assumes

The live product's Security page states four principles: read-only onboarding by default, least-privilege permissions, no changes without approval, and revocable access at any time by deleting the IAM role or rotating credentials.

[`iam/read-only-collector-policy.json`](../iam/read-only-collector-policy.json) is a concrete least-privilege IAM policy scoped to exactly what this engine's data model needs to populate `resource_inventory.json` and `cost_and_usage.csv` from a real account:

- Cost Explorer (`ce:Get*`) for billing data
- CloudWatch (`cloudwatch:GetMetricData`, `GetMetricStatistics`, `ListMetrics`) for the CPU utilization the idle/underutilized EC2 rule needs
- `Describe*`/`List*`/`Get*` calls on EC2, RDS, and S3 for configuration state: instance types, attachment, storage class, public-access and encryption flags
- `sts:GetCallerIdentity` for a basic connectivity check

There is no `Put*`, `Delete*`, `Terminate*`, `Modify*`, or `Create*` action anywhere in the Allow statement. A second statement adds an explicit `Deny` on the specific destructive actions closest to what this engine touches: terminate/stop/delete/modify on EC2/RDS/S3, plus a blanket `iam:*`/`organizations:*` deny. That is redundant with IAM's default-deny in isolation, but it is a real guardrail in practice: if this policy is ever attached to a role alongside something broader, the explicit `Deny` still wins.

Nothing in `src/greenpilot/` calls the AWS API at all. Version 1 only reads local files (see [docs/architecture.md](architecture.md)), so this policy documents what a real collector would need, matching the live product's "you configure and review permissions before granting access" statement, not something this code currently exercises.

## Data handled by this repo

- Committed data is entirely synthetic. `sample_data/*.csv`/`*.json` are hand-authored fictional resources (see [README](../README.md)). No real AWS account, billing data, or customer information has touched this repository.
- No secrets, ever: no `.env`, no credentials, no API keys, no `.aws/` config. Enforced going forward by `.gitignore` and by GitHub's secret scanning, which is on by default for public repositories.
- Output escaping: `report.py` escapes every resource-derived field (`resource_id`, `title`, `description`, `rollback`, `--company`) before it is written into the Markdown report. A `|` would otherwise corrupt the findings table, and `<`/`>`/`&` would otherwise pass raw HTML through unescaped into any future renderer of this Markdown, i.e. the roadmap's web dashboard. See `_escape_md` in [`report.py`](../src/greenpilot/report.py) and `tests/test_report_escaping.py`.
- Input validation: `engine.load_resources` rejects negative costs and negative running-hours instead of letting them flow into the savings/carbon math and produce a silently wrong, inflated report. See `tests/test_engine_validation.py`.

## Repo-level controls

- [CodeQL](../.github/workflows/codeql.yml): static analysis on every push/PR and weekly, using GitHub's default Python query suite.
- [Dependabot](../.github/dependabot.yml): automated updates for the Python dependency (currently `pytest` only) and for the GitHub Actions themselves.
- CI (`pytest`) enforces the rule/engine/escaping tests on every push, so a regression in any of this cannot land on `main` silently.
- No write-capable GitHub Actions permissions and no secrets used in any workflow, so a malicious pull request from a fork has nothing to reach.

## Third-party services (live product)

Listed on the live Security page, for reference:

- Vercel: website hosting, HTTPS, DDoS protection, CDN
- Formspree: contact/pilot-request form processing
- Google Analytics 4: optional, consent-based
- AWS: customer-controlled data access via IAM roles/credentials, for the assessment itself

None of these are used by this repository. It has no hosting, no forms, and no analytics.

## What this repo does not cover

Matching the live site's own stated pilot-stage limitations:

- No ISO 27001 or SOC 2. Not claimed by the live product, and not applicable to a portfolio repository.
- No penetration test has been run against this code.
- Encryption in transit or at rest does not apply here: this is a local CLI tool with no network calls and no server component.
- RBAC, automated rollback, and audit logging are live-product roadmap items, not something this repo implements.

## Reporting a concern

See [SECURITY.md](../SECURITY.md).
