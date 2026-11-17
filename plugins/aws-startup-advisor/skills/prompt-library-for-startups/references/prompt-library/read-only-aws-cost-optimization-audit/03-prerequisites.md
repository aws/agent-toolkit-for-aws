<!-- markdownlint-disable -->

## PREREQUISITES

**Access.** The permission set is the security control for this audit; Rule 1 is defense in depth on top of it, not a substitute for it. Run the audit as an IAM role carrying exactly the two policies below, assumed with temporary credentials. The user does not need to create it in advance: 1.1.2 walks them through creating it in the chosen account. Do not mint a long-lived IAM user access key for this; it outlives the audit and tends to end up in shell history or a repository.

Do **not** use the AWS managed `ReadOnlyAccess` policy. It grants data-plane reads such as `s3:GetObject`, `dynamodb:GetItem`, `dynamodb:Scan`, and `sqs:ReceiveMessage`. This audit reads metadata and metrics only and never needs access to customer data, so granting it violates least privilege for no benefit. `ViewOnlyAccess` is the metadata-level job-function policy that provides the breadth without the data access, which is why the access story below builds on it.

**Audit policies.** Attach two policies to a dedicated audit role, suggested name `CostAuditReadOnly`:

1. **AWS managed `ViewOnlyAccess`** (`arn:aws:iam::aws:policy/job-function/ViewOnlyAccess`). List and Describe at the metadata level across every AWS service, maintained by AWS as new services launch. This is what lets the 4.13 coverage fallback inspect material services this document never names, without anyone editing a policy each time AWS ships something.

   It is narrower than `ReadOnlyAccess` in exactly the way that matters for customer data: no `s3:GetObject`, no `dynamodb:GetItem` or `Scan`, no `sqs:ReceiveMessage`. That is the reason to prefer it, and it is a real reduction.

   **It is metadata-first, not data-free, and the difference is worth stating plainly.** Several of its List and Describe actions return sensitive values inside the response of a call this audit legitimately makes. Verified against the policy document, edited 22 April 2026:

   | Grant | What the response carries |
   | --- | --- |
   | `lambda:List*` | `ListFunctions` returns `Environment.Variables` for every function - routinely API keys and database passwords. The largest secret-exposure grant in the set |
   | `cognito-idp:List*` | `ListUsers` returns user attributes: email addresses, phone numbers |
   | `ecs:Describe*` | `DescribeTaskDefinition` returns container `environment` in plaintext |
   | `sns:List*` | `ListSubscriptions` returns `Endpoint`: email addresses and phone numbers |
   | `cloudformation:DescribeStacks` | Stack `Parameters` and `Outputs` |
   | `cloudtrail:LookupEvents` | The contents of the audit log |
   | `route53:Get*` / `List*` | Full internal DNS zone contents |
   | `ec2:DescribeKeyPairs`, `DescribeSecurityGroups`, `DescribeSecurityGroupRules` | Network posture |
   | `iam:List*`, `GetAccountSummary`, `GetLoginProfile` | Users, access keys, MFA devices. 1.4 uses two of these deliberately to verify its own permission scope |

   The audit needs none of those values, and narrowing the grant is the wrong fix: 4.13's fallback must reach services this document never names, and a hand-maintained action list stops doing that the moment AWS ships something new. So the trade is deliberate - breadth of metadata in exchange for a residual data surface - and it is managed on the consumption side instead: **Rule 4 requires dropping the sensitive fields on receipt**, and the 2.1 probes project counts rather than bodies. Tell the customer's security reviewer this, rather than letting them find it. An overstated claim costs more credibility than the disclosure does.

   One action is denied outright rather than managed: `s3:ListBucket` lists object key names, which can themselves be sensitive and which the audit never needs, so the supplement denies it explicitly.
2. **The customer managed supplement below**, named exactly `CostAuditSupplement` (fits the 6,144-character managed-policy limit). The name is fixed because 1.4 verifies the role's permission scope by its policy set; 1.1.2 attaches it inline under that name, and a customer managed policy of that name is accepted too. It adds the cost tooling `ViewOnlyAccess` lacks and carries the explicit `Deny`. `Resource: "*"` is correct here: the audit must see every resource, and most of these actions do not support resource-level constraints. The `Deny` covers every purchase and enrollment path this document refuses to run, plus `s3:ListBucket`; an explicit Deny wins over any Allow, including an admin policy someone attaches to the same principal later, so Rule 1 stops depending on model behavior alone.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CostToolingRead",
      "Effect": "Allow",
      "Action": [
        "aoss:BatchGetCollection",
        "aoss:ListCollections",
        "bedrock:ListProvisionedModelThroughputs",
        "budgets:Describe*",
        "budgets:ViewBudget",
        "ce:Describe*",
        "ce:Get*",
        "ce:List*",
        "compute-optimizer:Describe*",
        "compute-optimizer:Get*",
        "logs:GetStorageTierPolicy",
        "organizations:Describe*",
        "pricing:DescribeServices",
        "pricing:GetProducts",
        "redshift:Describe*",
        "s3:GetBucketLocation",
        "s3:GetBucketTagging",
        "s3:GetLifecycleConfiguration",
        "s3:GetMetricsConfiguration",
        "s3:ListBucketMultipartUploads",
        "savingsplans:Describe*",
        "tag:GetResources"
      ],
      "Resource": "*"
    },
    {
      "Sid": "DenyPurchaseEnrollmentAndObjectListing",
      "Effect": "Deny",
      "Action": [
        "ce:StartSavingsPlansPurchaseRecommendationGeneration",
        "compute-optimizer:UpdateEnrollmentStatus",
        "dynamodb:PurchaseReservedCapacityOfferings",
        "ec2:PurchaseReservedInstancesOffering",
        "elasticache:PurchaseReservedCacheNodesOffering",
        "es:PurchaseReservedInstanceOffering",
        "memorydb:PurchaseReservedNodesOffering",
        "rds:PurchaseReservedDBInstancesOffering",
        "redshift:PurchaseReservedNodeOffering",
        "s3:ListBucket",
        "savingsplans:CreateSavingsPlan"
      ],
      "Resource": "*"
    }
  ]
}
```

**Trust policy.** The role trusts exactly one principal: the identity the user already signs in with in the audited account. 1.1.2 builds that trust policy from the caller identity and gives it to the user together with the role-creation steps.

Notes on the policies. The `es:` prefix covers managed OpenSearch domains only; OpenSearch **Serverless** is a separate IAM namespace, `aoss:`, which `ViewOnlyAccess` does not include. Without the two `aoss:` actions in the supplement, a collection billing the always-on OCU floor is invisible to this audit, and a single collection can cost several hundred USD per month. `savingsplans:Describe*` feeds the 6.1 commitment expiry dates. `organizations:Describe*` and `redshift:Describe*` (reserved nodes) fill `ViewOnlyAccess` gaps this audit relies on. `bedrock:ListProvisionedModelThroughputs` feeds 4.12.1 (`ViewOnlyAccess` already carries `bedrock:ListCustomModels`), and `logs:GetStorageTierPolicy` feeds the 4.9 Intelligent Tiering check; `logs:Describe*` covers neither. `sts:GetCallerIdentity` needs no permission. The Deny lists every per-service RI purchase action, not just EC2, because RI purchases are per-service APIs. `ce:StartSavingsPlansPurchaseRecommendationGeneration` is denied, not merely omitted: it is a write action. See 6.2.

If the user runs with broader credentials anyway, treat it as a degraded mode: warn prominently in the Phase 1 output (see 1.4), state that the least-privilege role removes the risk, and continue only after the user acknowledges. Never present broader credentials as an equivalent path.

**MCP servers.** `billing-cost-management` for Cost Explorer, commitment coverage and utilization, Cost Optimization Hub, anomalies, pricing. `aws-knowledge` or `aws-documentation` for verifying service behavior, limits, and pricing models. `aws-pricing-calculator` for target-state modelling. AWS CLI v2 is the fallback and is required for Compute Optimizer and all resource-level `Describe` calls.

**Shell.** AWS CLI v2 runs natively on Windows, macOS, and Linux, and `--query` is implemented in the CLI, so **every single-command block below runs unchanged in PowerShell, cmd, and bash once the preamble variables are set.** Dates are agent-computed literals (see the Dates convention), so no shell performs date arithmetic; only loops and JSON post-processing are shell-specific, and preambles for bash and PowerShell follow. PowerShell 5.1 or 7+ needs no WSL. `cmd` handles single commands but not loops. Single-quote JSON `--filter` arguments in bash and PowerShell (here-string in PowerShell when the JSON has double quotes), escape inner quotes in cmd; this is the usual cause of parse failures. With no shell, use MCP for cost, commitment, and Hub data and list the resource-level checks you skipped.

---

<!-- markdownlint-enable -->
