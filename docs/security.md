# Security Model

This documents how the security posture described on [greenpilotai.com/security.html](https://greenpilotai.com/security.html) maps onto this repository: what is a concrete artifact here, versus what is a claim about the live product that this repo does not (and cannot) fully implement.

## Access model this engine assumes

The live product's Security page states four principles: read-only onboarding by default, least-privilege permissions, no changes without approval, and revocable access at any time by deleting the IAM role or rotating credentials.

[`iam/read-only-collector-policy.json`](../iam/read-only-collector-policy.json) is the exact least-privilege IAM policy `aws/collector.py` needs, and this is not aspirational: it's what live mode actually calls.

- Cost Explorer (`ce:Get*`), reserved for a future Cost Explorer-based pricing source (see the "not yet implemented" note below); not called by the current collector.
- CloudWatch (`cloudwatch:GetMetricData`, `GetMetricStatistics`, `ListMetrics`) for EC2 CPU utilization, RDS replica connection counts, and S3 bucket size.
- `Describe*`/`List*`/`Get*` calls on EC2, RDS, and S3 for configuration state: instance types, attachment, storage class, public-access block, encryption, versioning.
- `iam:GenerateCredentialReport` and `iam:GetCredentialReport`, the two calls behind the NIS2 credential-hygiene checks (root account keys, MFA, stale keys, inactive users). No other `iam:` action is Allow-listed.
- `sts:GetCallerIdentity` for the connectivity check.

There is no `Put*`, `Delete*`, `Terminate*`, `Modify*`, or `Create*` action anywhere in the Allow statement. A second statement adds an explicit `Deny` on the specific destructive actions closest to what this engine touches: terminate/stop/delete/modify on EC2/RDS/S3, plus verb-prefix wildcards (`iam:Create*`, `iam:Delete*`, `iam:Put*`, `iam:Update*`, `iam:Attach*`, `iam:Detach*`, `iam:Remove*`, `iam:Deactivate*`, `iam:Add*`) rather than a blanket `iam:*`, specifically so that wildcard doesn't shadow the two IAM reads the collector actually needs. That's a real guardrail in practice: if this policy is ever attached to a role alongside something broader, the explicit `Deny` still wins. `tests/test_iam_policy.py` checks both directions: that real destructive actions are covered, and that the two Allow-listed reads are not accidentally caught by the same patterns.

Every call `aws/collector.py` makes is one of the actions above; see [docs/architecture.md](architecture.md) for how the collector is structured (client-injection, not a Session, specifically so it's testable without a real account) and `tests/test_aws_collector.py` for the tests, which run against `botocore.stub.Stubber`, never a live account.

## Data handled by this repo

- Committed data is entirely synthetic. `sample_data/*.csv`/`*.json` are hand-authored fictional resources (see [README](../README.md)). No real AWS account, billing data, or customer information has touched this repository.
- No secrets, ever: no `.env`, no credentials, no API keys, no `.aws/` config. Enforced going forward by `.gitignore` and by GitHub's secret scanning, which is on by default for public repositories.
- Output escaping: `report.py` escapes every resource-derived field (`resource_id`, `title`, `description`, `rollback`, `--company`) before it is written into the Markdown report. A `|` would otherwise corrupt the findings table, and `<`/`>`/`&` would otherwise pass raw HTML through unescaped into any future renderer of this Markdown, i.e. the roadmap's web dashboard. See `_escape_md` in [`report.py`](../src/greenpilot/report.py) and `tests/test_report_escaping.py`.
- Input validation: `engine.load_resources` rejects negative costs and negative running-hours instead of letting them flow into the savings/carbon math and produce a silently wrong, inflated report. See `tests/test_engine_validation.py`.

## Repo-level controls

- [CodeQL](../.github/workflows/codeql.yml): static analysis on every push/PR and weekly, using GitHub's default Python query suite.
- [Dependabot](../.github/dependabot.yml): automated updates for the Python dependencies (`pytest`, and `boto3` for the optional `aws` extra) and for the GitHub Actions themselves.
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
- This is a local CLI tool with no server component. Live mode's only network calls are to AWS's own API endpoints via boto3, which uses TLS by default; there is no custom transport code here to audit. Demo mode makes no network calls at all.
- RBAC, automated rollback, and audit logging are live-product roadmap items, not something this repo implements.

## Reporting a concern

See [SECURITY.md](../SECURITY.md).
