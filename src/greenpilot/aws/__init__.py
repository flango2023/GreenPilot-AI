"""Live AWS collection. Only imported when `--source live` is used.

boto3 is an optional dependency (`pip install -e ".[aws]"`) precisely so
the sample-data demo path keeps its standard-library-only guarantee. See
collector.py for the actual boto3 calls, and iam/read-only-collector-policy.json
for the exact IAM permissions this package needs and nothing more.
"""
