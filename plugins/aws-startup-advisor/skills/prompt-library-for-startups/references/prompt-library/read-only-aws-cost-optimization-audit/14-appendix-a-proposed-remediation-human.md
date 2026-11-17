<!-- markdownlint-disable -->

## APPENDIX A: PROPOSED REMEDIATION (HUMAN EXECUTION REQUIRED)

Everything here is a proposal. Per Rule 1, do not execute any of it and do not offer to. Open with this notice verbatim:

> These commands change or delete resources and may create binding financial commitments. They have not been executed. Review each against your change management process, verify resource ownership, and confirm backups before running anything. Test in a non-production environment where possible.

**Tier 1, reversible and low risk.** CloudWatch Logs retention policies, CloudWatch Logs Intelligent Tiering, S3 lifecycle rules including `AbortIncompleteMultipartUpload`, ECR lifecycle policies expiring untagged images, gp2 to gp3 modification, Gateway VPC endpoints, budgets. For each: what it does, command or console path, expected saving, how to reverse. Note that an EBS volume cannot be modified again for six hours, so reversal is not instant.

**Tier 2, reversible but needs validation.** Instance resizing, DynamoDB capacity mode changes, non-production scheduling, pausing a Redshift cluster, removing an interface endpoint. For each: what it does, command or console path, expected saving, post-change validation, rollback procedure, recommended maintenance window.

**Tier 3, destructive or binding, named approval required.** Terminating instances; deleting volumes, snapshots, AMIs, load balancers, NAT Gateways, or RDS instances; releasing Elastic IPs; purchasing Savings Plans or RIs. Give a checklist, not a runnable command: resource identifier and environment classification; named owner who confirmed removal is safe; confirmed backup or snapshot with identifier and date; what breaks if this is wrong and whether recovery is possible; commitment coverage outcome and realised-savings date per 4.13 step 6; monthly saving; approver name and date left blank.

**For commitment purchases give no CLI command at all.** Provide the console path, exact parameters, and this note:

> A Savings Plan or Reserved Instance purchase cannot be cancelled, modified, or refunded. Validate the commitment in Savings Plans Purchase Analyzer first, and confirm the waste identified in this report has been removed. Requires named approval from a budget owner.

**Follow-up mechanisms.** Budgets with actual and forecast alerts, Cost Anomaly Detection monitors *with* subscriptions, a tagging policy enforced via SCP or AWS Config, scheduled re-audits, and a Cost Optimization Hub review cadence.

---

<!-- markdownlint-enable -->
