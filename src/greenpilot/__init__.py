"""GreenPilot AI: AWS cost, carbon, and EU-governance assessment engine.

This package implements the rule-based optimization engine described at
https://greenpilotai.com/platform.html: it reads AWS resource and billing
data, flags waste and governance-relevant configurations, estimates the
carbon footprint of the account, and renders a ranked, human-readable report,
in the same shape as the report at https://greenpilotai.com/sample-report.html.

It is read-only and makes no changes to any real infrastructure. Nothing in
this package talks to AWS directly; it operates on exported/CSV or synthetic
data, matching GreenPilot's "read-only, approval-based" product principle.
"""

__version__ = "0.1.0"
