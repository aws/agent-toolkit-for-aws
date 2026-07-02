# Verify Dependencies

Before running workflows that require external tools, verify the following:

- **Python 3.10+** — required for [rds_commitment_pricing_analyzer.py](../scripts/rds_commitment_pricing_analyzer.py). If `boto3` is missing, offer offline mode for commitment pricing.
- **AWS CLI v2** — required for upgrade, proxy, and Blue/Green workflows.
- **Credentials** — confirm with `aws sts get-caller-identity` before live runs. Prefer IAM roles (EC2 instance profiles, ECS task roles, or AWS SSO session credentials) over long-lived IAM user access keys. If long-lived keys are used, ensure they are rotated regularly. For database connections during prechecks, prefer IAM database authentication where supported.

**Constraints:**

- You MUST ONLY check tool existence and MUST NOT invoke the tools here, because that would trigger live calls before the user is ready
- You MUST ask before switching to offline mode
