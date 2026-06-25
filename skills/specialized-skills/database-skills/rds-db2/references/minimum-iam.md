# RDS for Db2 — Minimum IAM Permissions Reference

Source:

- Workspace: `04-db2-client/minimum-iam-permissions-rds-db2/` (`RDS-Db2-IAM-Policy-README.md`)
- Bundled policies: [`../assets/rds-db2-minimal-iam-policy.json`](../assets/rds-db2-minimal-iam-policy.json),
  [`../assets/rds-db2-trust-policy.json`](../assets/rds-db2-trust-policy.json)

Least-privilege IAM for provisioning and managing RDS for Db2 with all in-scope features. Grant only
what the workflow needs; never attach a `*FullAccess` managed policy.

---

## Features the minimal policy covers

The bundled `rds-db2-minimal-iam-policy.json` scopes permissions for: BYOK (KMS create, import,
multi-region replicate), Active Directory integration (Directory Service), S3 database restore and
backup, enhanced monitoring (CloudWatch Logs), custom parameter groups (IBM Customer ID and Site ID
for BYOL), S3 Db2 auditing (option groups), backup retention, cross-region standby and read replicas,
snapshot management, instance modify/delete, and SNS event notifications.

---

## 1. Create the role from the trust policy

The trust policy uses an `ExternalId` so the role can only be assumed by a principal in your
account that supplies the agreed external ID (the recommended guard for an IAM-principal-assumed
role). Note: `aws:SourceArn` / `aws:SourceAccount` are *service* confused-deputy keys — they are
only populated when an AWS service (e.g. `rds.amazonaws.com`) assumes the role on your behalf, and
are absent when an IAM principal calls `sts:AssumeRole`. Including them here with an `AWS` (root)
principal would make the role unassumable, so this trust policy uses `ExternalId` only:

```json
{
  "Condition": {
    "StringEquals": {
      "sts:ExternalId": "<unique-external-id>"
    }
  }
}
```

Replace `<account-id>` and `<unique-external-id>` with real values, then create the role:

```bash
aws iam create-role \
  --role-name RDS-Db2-Management-Role \
  --assume-role-policy-document file://assets/rds-db2-trust-policy.json
```

---

## 2. Attach the minimal policy

```bash
aws iam put-role-policy \
  --role-name RDS-Db2-Management-Role \
  --policy-name RDS-Db2-Minimal-Policy \
  --policy-document file://assets/rds-db2-minimal-iam-policy.json
```

---

## 3. Resource-naming scope patterns

The policy scopes most mutating actions by ARN pattern (with three documented `Resource: "*"`
exceptions noted below), so naming your resources to match the patterns is required:

| Resource | Required naming | Example ARN pattern |
|---|---|---|
| S3 buckets | name contains `db2`, `backup`, `restore`, or `audit` | `arn:aws:s3:::*db2*` |
| IAM roles | name starts with `rds-` or contains `-rds-` / `-db2-` | `arn:aws:iam::*:role/rds-*` |
| SNS topics | name starts with `rds-` or contains `-rds-` / `-db2-` | `arn:aws:sns:*:*:rds-*` |
| RDS objects | scoped by type | `db:*`, `snapshot:*`, `pg:*`, `og:*`, `subgrp:*`, `es:*` |
| KMS | key and alias ARNs | `arn:aws:kms:*:*:key/*`, `arn:aws:kms:*:*:alias/*` |

Only read-only describe actions (for example `rds:DescribeDBEngineVersions`, `ds:DescribeDirectories`,
`ec2:DescribeVpcs`) use `Resource: "*"`, because those calls cannot be ARN-scoped. Most mutating
statements are ARN-pattern-scoped. `iam:PassRole` is limited to the `rds-*` / `-rds-` / `-db2-` role
patterns **and** further constrained by an `iam:PassedToService` condition (`rds.amazonaws.com`,
`monitoring.rds.amazonaws.com`) so a matching role can only be passed to RDS, not to arbitrary
services such as Lambda or EC2.

**Documented `Resource: "*"` exceptions on mutating actions.** Three statements intentionally keep
`Resource: "*"` on mutating actions because AWS does not support practical resource-level scoping for
them at creation time:

- **`VPCNetworking`** — `ec2:CreateSecurityGroup` and the `ec2:Authorize/RevokeSecurityGroupIngress/Egress`
  actions. A security group ARN does not exist until after `CreateSecurityGroup` runs, so the create
  call cannot be ARN-scoped; the authorize/revoke calls are commonly left at `"*"` alongside it. Narrow
  these with VPC/security-group condition keys (for example `ec2:Vpc`) in environments that require it.
- **`DirectoryServiceIntegration`** — `ds:AuthorizeApplication` / `ds:UnauthorizeApplication` do not
  support resource-level permissions, so they require `Resource: "*"`.
- **`KMSNonResourceActions`** — `kms:CreateKey` (plus `kms:ListKeys` / `kms:ListAliases`). A KMS key ARN
  does not exist until after `CreateKey` runs, so the create call cannot be ARN-scoped; the list calls are
  account-wide and cannot be scoped either. All other KMS actions in the policy (encrypt, decrypt, grant,
  replicate, tag) remain scoped to `key/*` and `alias/*` ARNs.

If your environment mandates stricter scoping, split these statements and apply condition keys or VPC
ARNs as your account structure allows.

---

## 4. Security notes (Layer 3 least-privilege)

- **No `*FullAccess` managed policies** and **no `service:*` wildcard actions** — each statement lists
  explicit action names.
- **Minimal `Resource: "*"`** — read-only describe actions use `"*"` (they cannot be ARN-scoped), and
  three mutating statements (`VPCNetworking` security-group create/authorize/revoke,
  `DirectoryServiceIntegration` `ds:Authorize/UnauthorizeApplication`, and `KMSNonResourceActions`
  `kms:CreateKey`) keep `"*"` because AWS does not support resource-level permissions for them at
  creation time. Every other mutating statement is ARN-pattern-scoped. See §3 for the full exception
  rationale.
- **External ID required** for role assumption. The role is assumed by an IAM principal, so it
  relies on `sts:ExternalId` rather than the service-only `aws:SourceArn` / `aws:SourceAccount`
  confused-deputy keys (which are absent for `sts:AssumeRole` by an IAM principal). For roles a
  *service* assumes (for example the Db2 audit role that `rds.amazonaws.com` assumes), use
  `aws:SourceArn` / `aws:SourceAccount` instead — see [db2-audit.md](db2-audit.md).
- Minimal action set per operation — add actions only when a new workflow needs them.

---

## 5. Pre-deploy check with the policy simulator

Validate the role grants the actions you expect (and denies the rest) before relying on it:

```bash
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::<account-id>:role/RDS-Db2-Management-Role \
  --action-names rds:CreateDBInstance \
  --resource-arns arn:aws:rds:us-east-1:<account-id>:db:test-db2
```

Repeat `--action-names` for each action a workflow performs (for example `rds:ModifyDBInstance`,
`kms:CreateGrant`, `s3:PutObject`) and confirm the decision is `allowed`.

---

## 6. Additional permissions you may need

The minimal policy is intentionally narrow. Add scoped permissions when your deployment uses:

- **CloudFormation** — if you provision RDS for Db2 through Infrastructure as Code.
- **Secrets Manager** — if you store master credentials there (preferred over inline passwords); pairs
  with `--manage-master-user-password`.
- **Lambda** — if custom functions participate in provisioning or event handling.

Add each as a separate, ARN-scoped statement rather than widening an existing one.
