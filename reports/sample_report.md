# GreenPilot AI — Cloud Assessment Report

**Company:** Acme Tech Solutions GmbH  
**Generated:** 2026-08-18  
**Resources analyzed:** 15  
**Findings flagged:** 14

## Executive Summary

- **€1,081.86** estimated monthly savings potential
- **€12,982.32** estimated annual savings potential
- **0.23 t** estimated CO2e reduction / year
- **9** cost-waste findings across 4 AWS services

## Cloud Waste Findings

| Resource | Service | Finding | Monthly Cost Today | Monthly Savings | Effort |
|---|---|---|---:|---:|---|
| ec2-web-01 | EC2 | Idle EC2 instance (m5.xlarge) | €420.00 | €294.00 | low |
| ec2-batch-02 | EC2 | Underutilized/oversized EC2 instance (c5.2xlarge) | €640.00 | €256.00 | medium |
| ebs-vol-02 | EBS | Unattached EBS volume (250 GB) | €38.00 | €38.00 | low |
| ebs-vol-03 | EBS | Unattached EBS volume (60 GB) | €15.00 | €15.00 | low |
| rds-replica-02 | RDS | Redundantly configured RDS instance (db.m5.large) | €310.00 | €155.00 | medium |
| s3-logs-archive | S3 | Misclassified S3 storage tier | €95.00 | €66.50 | low |
| s3-backups | S3 | Misclassified S3 storage tier | €72.00 | €28.80 | low |
| ec2-dev-04 | EC2 | Schedulable workload running 24/7 (t3.large) | €180.00 | €115.89 | low |
| ec2-staging-05 | EC2 | Schedulable workload running 24/7 (t3.large) | €175.00 | €112.67 | low |

## Prioritized Action Plan

1. **Idle EC2 instance (m5.xlarge)** (ec2-web-01) — save ~€294.00/mo, effort: low
   - Average CPU utilization is 3.2%, below the idle threshold. Likely safe to stop or terminate.
   - Rollback: Instance can be re-launched from its AMI/snapshot if needed.
2. **Underutilized/oversized EC2 instance (c5.2xlarge)** (ec2-batch-02) — save ~€256.00/mo, effort: medium
   - Average CPU utilization is 14.5%. Instance class is likely larger than the workload needs.
   - Rollback: Resize back up in one change if performance regresses.
3. **Redundantly configured RDS instance (db.m5.large)** (rds-replica-02) — save ~€155.00/mo, effort: medium
   - Configuration overlaps with another instance serving the same workload (e.g. an unused read replica or duplicated Multi-AZ).
   - Rollback: Re-provision the replica from a snapshot if load increases.
4. **Schedulable workload running 24/7 (t3.large)** (ec2-dev-04) — save ~€115.89/mo, effort: low
   - Tagged as a non-production workload but running continuously. A start/stop schedule matching business hours removes most of the cost.
   - Rollback: Schedule can be paused instantly to return to always-on.
5. **Schedulable workload running 24/7 (t3.large)** (ec2-staging-05) — save ~€112.67/mo, effort: low
   - Tagged as a non-production workload but running continuously. A start/stop schedule matching business hours removes most of the cost.
   - Rollback: Schedule can be paused instantly to return to always-on.
6. **Misclassified S3 storage tier** (s3-logs-archive) — save ~€66.50/mo, effort: low
   - Bucket has 'rare' access patterns but is stored in STANDARD. Moving to GLACIER matches access to cost.
   - Rollback: Lifecycle transitions are reversible by changing the storage class back.
7. **Unattached EBS volume (250 GB)** (ebs-vol-02) — save ~€38.00/mo, effort: low
   - Volume is not attached to any running instance.
   - Rollback: Snapshot before deletion to allow full recovery.
8. **Misclassified S3 storage tier** (s3-backups) — save ~€28.80/mo, effort: low
   - Bucket has 'infrequent' access patterns but is stored in STANDARD. Moving to STANDARD_IA matches access to cost.
   - Rollback: Lifecycle transitions are reversible by changing the storage class back.
9. **Unattached EBS volume (60 GB)** (ebs-vol-03) — save ~€15.00/mo, effort: low
   - Volume is not attached to any running instance.
   - Rollback: Snapshot before deletion to allow full recovery.

## Carbon Impact Estimate

- **0.89 t** estimated current CO2e / year
- **0.23 t** potential reduction / year if all findings above are actioned
- Indicative only — instance specs and annual grid averages used as proxies for metered energy use. See docs/carbon-methodology.md.

## EU Governance Observations

### Data Residency (GDPR)

- **Personal data stored outside the EU/EEA** (s3-active-assets): s3-active-assets is tagged as containing personal data but is provisioned in 'us-east-1', outside the EU/EEA. Worth reviewing against your GDPR data-residency and transfer-mechanism obligations.

### Security Posture (NIS2)

- **Publicly accessible resource** (ec2-api-06): ec2-api-06 is reachable from the public internet. Under NIS2's risk-management duties, confirm this is intentional and covered by your access-control and monitoring baseline.
- **Storage not encrypted at rest** (rds-analytics-03): rds-analytics-03 has no encryption at rest configured — a common baseline control referenced under NIS2 risk-management measures.
- **Publicly accessible resource** (s3-active-assets): s3-active-assets is reachable from the public internet. Under NIS2's risk-management duties, confirm this is intentional and covered by your access-control and monitoring baseline.

### Emissions Reporting (CSRD)

- **Cloud emissions are in-scope for CSRD reporting** (ACCOUNT): Estimated cloud energy use for this account is 0.89 t CO2e/year, relevant to Scope 2/3 disclosures under the Corporate Sustainability Reporting Directive. Treat this as a starting estimate, not an audited figure.

---
*This is a demo report generated from synthetic sample data by the open-source engine in this repository — see [sample_data/](../sample_data) and [docs/carbon-methodology.md](../docs/carbon-methodology.md). It mirrors the report structure at [greenpilotai.com/sample-report.html](https://greenpilotai.com/sample-report.html); figures here are illustrative, not from a real customer account.*
