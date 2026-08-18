# Security Policy

## Reporting a vulnerability

If you find a security issue in this repository or believe it reflects a security issue in the live GreenPilot AI product, please email **info@greenpilotai.com** with the subject line **"Security concern — GreenPilot AI"**, including:

- A description of the issue and its potential impact
- Steps to reproduce (if applicable)
- Any relevant logs, screenshots, or PoC code

You'll get an acknowledgment within **5 business days**. Credible reports are investigated in good faith. Please do not open a public GitHub issue for anything you believe is a security vulnerability — email first.

## Scope

This repository ships:
- A local, offline Python rule engine (no network calls, no AWS API calls)
- Synthetic sample data only — never real customer or AWS account data
- No secrets, credentials, or API keys anywhere in the codebase or history

For the security model of the live product this repo supports (IAM access model, data handling, third-party services, current certification status), see [docs/security.md](docs/security.md) and the live [greenpilotai.com/security.html](https://greenpilotai.com/security.html).

## Supported versions

This is a pre-1.0 portfolio/demo project. Only the `main` branch is supported; there are no maintained release branches.

## Automated checks

- [CodeQL](.github/workflows/codeql.yml) static analysis runs on every push/PR and weekly.
- [Dependabot](.github/dependabot.yml) tracks dependency and GitHub Actions updates.
- GitHub's default secret scanning is enabled on this public repository.
