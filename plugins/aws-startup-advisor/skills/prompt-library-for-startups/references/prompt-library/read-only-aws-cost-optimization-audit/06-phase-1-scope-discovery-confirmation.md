<!-- markdownlint-disable -->

## PHASE 1: SCOPE DISCOVERY & CONFIRMATION

Discover what you can; ask only what you cannot.

### 1.1 Identity and accessible accounts

This step runs under whatever credentials the user already has, before the audit role exists. It is read-only and short: list the accounts the user can reach, then let them pick one. Never read `~/.aws/credentials`, `~/.aws/config`, or the SSO token cache to do it (Rule 4); ask the CLI instead.

```bash
aws sts get-caller-identity --query '[Account,Arn]' --output text
# Profile names cannot contain whitespace, so word-splitting is safe here. An expired SSO
# profile prints its error instead of an account; report it, never log in on the user's behalf.
for p in $(aws configure list-profiles); do
  printf '%s\t%s\n' "$p" \
    "$(aws sts get-caller-identity --profile "$p" --query '[Account,Arn]' --output text 2>&1 | tr '\n' ' ')"
done
aws organizations describe-organization \
  --query 'Organization.{Id:Id,ManagementAccountId:MasterAccountId,FeatureSet:FeatureSet}'
```

If the current identity is in the organization's management account, also run `aws organizations list-accounts --query 'Accounts[].{Id:Id,Name:Name,Status:Status}' --output table`. Label that list "accounts in the organization", not "accounts you can access": it shows what exists, not what the user can sign in to. Both Organizations queries omit email fields per Rule 4: `list-accounts` returns `Email` per account and `describe-organization` returns the management account's address in `MasterAccountEmail` (the API's field name). `--query` filters client-side, so the raw responses still contain the addresses; never echo an unfiltered response. `AWSOrganizationsNotInUseException` means the account is standalone; `AccessDenied` means the organization is unknown, so record that.

#### 1.1.1 Choose the account

Present one table: profile name, account ID (masked per Rule 4 unless the user confirmed the full variant), principal type (IAM user, IAM role, or Identity Center role, recognisable by `AWSReservedSSO_` in the ARN), and, where `list-accounts` ran, the account name. Then ask: "Which account should this audit analyse? Pick a profile from the list, or give me a 12-digit account ID." One account per run; if the user names several, audit the first and tell them to run the prompt again for each of the others.

Set `AUDIT_ACCOUNT` to the answer and record the profile that reaches it as the source profile. An account ID with no matching profile needs one first: tell the user to configure a CLI profile for that account (for Identity Center, `aws configure sso`), then re-run 1.1. In unattended mode (Rule 8), audit the account of the current credentials and record it as assumed.

#### 1.1.2 Create and switch to the audit role

Tell the user: "I will not create anything in your account. Below is a least-privilege, read-only role for this audit. Please create it, or tell me to continue with your current credentials, which I will then treat as write-capable." Then give them everything they need to create `CostAuditReadOnly` in `AUDIT_ACCOUNT`, as text they run themselves. Never run these commands; Rule 1 applies to them exactly as to Appendix A.

**1. The trust policy.** The role trusts only the identity the user already signs in with through the source profile. Build it from that profile's caller ARN. For an IAM user, the principal ARN is the user ARN. For a role session (`arn:aws:sts::<acct>:assumed-role/<RoleName>/<session>`), the principal is the underlying role, whose ARN includes a path for Identity Center roles (`role/aws-reserved/sso.amazonaws.com/<region>/AWSReservedSSO_...`). Get the exact ARN with `aws iam get-role --role-name <RoleName> --query Role.Arn --profile <source profile>`; if that read is denied, use `ArnLike` with `role/*<RoleName>` and say so. Identity Center recreates its role with a new suffix when a permission set is unassigned and reassigned, which breaks this trust; the fix is re-running this step.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowOnlyTheAuditor",
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::AUDIT-ACCOUNT-ID:root" },
      "Action": "sts:AssumeRole",
      "Condition": {
        "ArnEquals": { "aws:PrincipalArn": "REPLACE-WITH-THE-SOURCE-PROFILE-PRINCIPAL-ARN" }
      }
    }
  ]
}
```

The account-root principal delegates to the account, and the `aws:PrincipalArn` condition narrows that to one identity, so no other user or role in the account can assume the audit role. Fill both placeholders before showing it to the user.

**2. The commands**, for the user to run with the source profile. Tell them to save the trust policy above as `cost-audit-trust.json` and the Prerequisites supplement as `cost-audit-supplement.json` first. `MaxSessionDuration` is one hour because the audit is bounded work and nothing should outlive it.

```text
aws iam create-role --role-name CostAuditReadOnly --max-session-duration 3600 \
  --assume-role-policy-document file://cost-audit-trust.json --profile SOURCE-PROFILE
aws iam attach-role-policy --role-name CostAuditReadOnly \
  --policy-arn arn:aws:iam::aws:policy/job-function/ViewOnlyAccess --profile SOURCE-PROFILE
aws iam put-role-policy --role-name CostAuditReadOnly --policy-name CostAuditSupplement \
  --policy-document file://cost-audit-supplement.json --profile SOURCE-PROFILE
```

Offer the console route as an alternative: IAM, Roles, Create role, custom trust policy, attach `ViewOnlyAccess`, then add the supplement as an inline policy named `CostAuditSupplement` (AWS documents it under "Create a role to give permissions to an IAM user"). If the user cannot create IAM roles, for example because they only reach the account through Identity Center, tell them an administrator can create an Identity Center permission set instead, with `ViewOnlyAccess` plus the supplement as its inline policy, and assign it to them for this account; they then sign in with that permission set and give you its profile.

**3. The profile.** Ask the user to add this to `~/.aws/config` themselves; you never write to CLI configuration or credential files:

```text
[profile cost-audit]
role_arn = arn:aws:iam::AUDIT-ACCOUNT-ID:role/CostAuditReadOnly
source_profile = SOURCE-PROFILE
role_session_name = costaudit-AUDIT_RUN_ID
```

The session name is what a security responder correlates this audit's API burst on (see 1.7), so keep the run ID in it. The CLI renews the role session from `source_profile` on its own; that matters because assuming a role from another role session is role chaining, which caps each session at one hour.

**4. Switch.** Wait for the user to reply that the role and profile exist, and for the profile name. Set `AUDIT_PROFILE` and run `use_audit_profile` (PowerShell: `Use-AuditProfile`). It must print `AUDIT_ACCOUNT` and an ARN containing `assumed-role/CostAuditReadOnly/`. If it prints another account, or fails, quote the error per Rule 3 and do not continue until it is resolved or the user chooses degraded mode. The 1.4 check then verifies the policy set.

If the user declines to create the role, continue under the source profile, set `AUDIT_PROFILE` to it, and let 1.4 report the degraded mode. In unattended mode (Rule 8) no role is created: do exactly that.

**5. Record the account type.** Now under the audit profile, repeat `describe-organization`. Record `account_type` in the state block: `management` when `ManagementAccountId` equals `AUDIT_ACCOUNT`, `member` when an organization exists and it does not, `standalone` on `AWSOrganizationsNotInUseException`. This answer is load-bearing: it switches on the management-account scoping convention and gates 6.1, 6.2, 6.3, and 7.1, so record it explicitly rather than inferring it later.

### 1.2 Regions with spend

Audit regions that cost money, not all 30-plus.

MCP: `cost_explorer` `getCostAndUsage`, MONTHLY, `UnblendedCost`, grouped by `REGION`, last three months, keep non-zero.

The `REGION` dimension returns the pseudo-regions `global` (CloudFront, Route 53, WAF, and other non-regional services) and `NoRegion`. Neither is a place a region-scoped command can run: report their spend separately as "global services" and keep both out of `CONFIRMED_REGIONS`, or every region loop runs against a region that does not exist.

```bash
aws ce get-cost-and-usage --time-period Start="$START_3M",End="$MONTH_START" \
  --granularity MONTHLY --metrics "UnblendedCost" --group-by Type=DIMENSION,Key=REGION \
  --output json | jq -r '[.ResultsByTime[].Groups[]
    | select((.Metrics.UnblendedCost.Amount|tonumber) > 0) | .Keys[0]]
    | unique | .[] | select(. != "global" and . != "NoRegion")'
```

### 1.3 Baseline spend and commitments

MCP: `cost_explorer` for the last complete calendar month of `UnblendedCost`, then `sp_performance` `get_savings_plans_coverage` and `ri_performance` `get_reservation_coverage`. Both default to console-aligned windows, so omit dates unless you need a specific range.

Label windows for what they are: "monthly spend" means the last complete calendar month, and a rolling window is reported as "trailing N days", never as a month. The two differ whenever spend trends, which is exactly when the number matters.

```bash
aws ce get-cost-and-usage --time-period Start="$START_1M",End="$MONTH_START" \
  --granularity MONTHLY --metrics "UnblendedCost" \
  --query 'ResultsByTime[].Total.UnblendedCost.Amount' --output text
aws ce get-savings-plans-coverage --time-period Start="$START_7D",End="$TODAY" \
  --granularity DAILY --query 'SavingsPlansCoverages[-1].Coverage' --output json
aws ce get-reservation-coverage --time-period Start="$START_7D",End="$TODAY" \
  --granularity DAILY --query 'Total.CoverageHours' --output json
```

### 1.4 Present discovered scope

Report: audited account ID and account type (1.1.2), current identity ARN, credential type, permission scope (see below), the identity MCP tools run under (Rule 2: not the audit role, scope unverified, and whether the 1.1 reachability check passed), organization, regions with spend (global services listed separately), spend for the last complete calendar month, existing SP and RI coverage, shell, tooling path (MCP / CLI / mixed), and estimated Cost Explorer charge for this audit.

**Permission scope is measured, and fails closed when it cannot be.** `sts get-caller-identity` returns identity, not permissions, so it cannot answer this on its own. **Never infer capability from the role name.** A role named `AdministratorAccess` is easy to spot, but a role named `PowerUser` or `PlatformEngineer` with identical write access would pass a name check silently.

Inspect the role's identity policies instead. `ViewOnlyAccess` grants `iam:List*`, `iam:GetAccountSummary`, and `iam:GetLoginProfile` (verified against the policy document, edited 22 April 2026), so `iam:ListAttachedRolePolicies` and `iam:ListRolePolicies` are both available and no supplement change is needed.

**Match on ARN, not on name, and accept the supplement in either place.** A policy *name* proves nothing: `ViewOnlyAccess` is a legal name for a customer-managed policy in any account, so only the AWS-managed ARN `arn:<partition>:iam::aws:policy/job-function/ViewOnlyAccess` identifies the real one. The supplement is customer-managed and its ARN carries the account ID, so it is matched by its fixed name `CostAuditSupplement` in the policy path, and it is accepted either attached or inline: 1.1.2 puts it inline under that name, so a role built from the document's own steps must pass. An Identity Center permission set is the one other accepted shape: its role is named `AWSReservedSSO_<permission set>_<suffix>`, and Identity Center always names the inline policy `AwsSSOInlinePolicy`, so on such a role that name counts as the supplement.

```bash
# The caller ARN is arn:<partition>:sts::<acct>:assumed-role/<RoleName>/<SessionName>.
CALLER_ARN=$(aws sts get-caller-identity --query Arn --output text)
AUDIT_ROLE=$(echo "$CALLER_ARN" | sed -n 's#.*:assumed-role/\([^/]*\)/.*#\1#p')
PARTITION=$(echo "$CALLER_ARN" | cut -d: -f2)
VIEW_ONLY_ARN="arn:${PARTITION}:iam::aws:policy/job-function/ViewOnlyAccess"

if [ -z "$AUDIT_ROLE" ]; then
  echo "SCOPE: unable to verify - treated as write-capable | caller is not an assumed role"
# Rule 3: report the exact error, never swallow it. A denial here is itself a finding.
elif attached=$(aws iam list-attached-role-policies --role-name "$AUDIT_ROLE" \
                  --query 'AttachedPolicies[].PolicyArn' --output text 2>&1) \
  && inline=$(aws iam list-role-policies --role-name "$AUDIT_ROLE" \
                --query 'PolicyNames' --output text 2>&1); then
  view_only=0; supplement=0; extra=""
  for p in $attached; do            # ARNs cannot contain whitespace
    case "$p" in
      None) ;;
      "$VIEW_ONLY_ARN")                        view_only=1 ;;
      arn:*:iam::[0-9]*:policy/CostAuditSupplement) supplement=$((supplement + 1)) ;;
      *)                                        extra="$extra $p" ;;
    esac
  done
  for p in $inline; do              # inline policy names cannot contain whitespace
    case "$p" in
      None) ;;
      CostAuditSupplement) supplement=$((supplement + 1)) ;;
      # Identity Center names every permission-set inline policy this way (see above).
      AwsSSOInlinePolicy)
        case "$AUDIT_ROLE" in
          AWSReservedSSO_*) supplement=$((supplement + 1)) ;;
          *)                extra="$extra inline:$p" ;;
        esac ;;
      *)                   extra="$extra inline:$p" ;;
    esac
  done
  echo "SCOPE EVIDENCE | role=$AUDIT_ROLE | attached=[$attached] | inline=[$inline]"
  if [ "$view_only" -eq 1 ] && [ "$supplement" -eq 1 ] && [ -z "$extra" ]; then
    echo "SCOPE: read-only (verified by policy set) | ViewOnlyAccess by AWS-managed ARN + CostAuditSupplement, nothing else"
  else
    echo "SCOPE: unable to verify - treated as write-capable | view_only=$view_only supplement=$supplement extra=[$extra]"
  fi
else
  # Whichever call failed left its error text in its variable; quote both verbatim.
  echo "SCOPE: unable to verify - treated as write-capable | iam call failed | attached=[${attached}] inline=[${inline:-not reached}]"
fi
```

Report `read-only (verified)` only when the block prints it: the principal is an assumed role, `ViewOnlyAccess` is present by its AWS-managed ARN, `CostAuditSupplement` is present exactly once (attached or inline), and nothing else is attached or inline. Any extra policy, a missing or duplicated supplement, or an `AccessDenied` on either call reports `unable to verify - treated as write-capable` with the exact error quoted per Rule 3. The role name is corroborating evidence at most; the policy set is the verdict.

State the limits of this evidence in the report, because they are real. First, this verifies the policy *set*, not its *contents*: `ViewOnlyAccess` is AWS-managed and its ARN is sufficient, but a customer-managed policy named `CostAuditSupplement` could contain anything, and reading it needs `iam:GetPolicy`, `iam:GetPolicyVersion`, and `iam:GetRolePolicy`, none of which `ViewOnlyAccess` grants. The audit deliberately does not add them, so `read-only (verified)` means *the role carries exactly the two expected policies by identity*, and the customer's own review of the supplement document is what vouches for its contents. Second, identity-policy inspection does not see service control policies, permission boundaries, or session policies. An SCP can only subtract, so it cannot invalidate the verdict, but a session policy or boundary attached outside this view changes what the principal can actually do, and the 2.1 probes exist partly to surface that.

When the scope is anything other than `read-only (verified)`, this is a degraded mode, not an equivalent path. Open the scope report with a prominent warning: "WARNING: these credentials are not the audit role and must be treated as write-capable. The audit stays read-only by instruction, but an instruction is not a security boundary. The read-only role from step 1.1.2 removes the risk; creating it takes minutes." Ask the user to either switch to the audit role or explicitly acknowledge continuing with write-capable credentials, and record the answer in the report header and Appendix B. In unattended mode (Rule 8) no acknowledgment is possible: continue in degraded mode and promote the warning to the first line of the report header.

### 1.5 Ask what you could not discover

1. **Scope.** All regions with spend, or exclude any?
2. **Environment separation.** Prod, dev, test split by account, by tag key and value, or by naming convention? Drives Rule 7, so a vague answer means everything is production. A tag answer sets `ENV_TAG_KEY` and `NONPROD_VALUES` in the preamble, which 4.4 and 5.3 consume; an account or naming answer changes 5.3's selection step instead.
3. **Constraints.** Compliance, uptime, licensing, change-freeze?
4. **Workload context.** Upcoming migration, launch, or decommission that would distort a baseline?
5. **Credits.** On AWS Activate or other promotional credits? Remaining balance and expiry date? Both live on the Billing console Credits page with no public API, so ask rather than guess, and capture the **Applicable Products** column if the user can see it. Drives 3.4 and the Phase 6 commitment gate.
6. **Savings target** in dollars or percent?
7. **Report format and audience.** Markdown, HTML, PDF, CSV, console. Will the output stay inside the account team? That decides Rule 4 masking.

### 1.6 Confirm scope

Summarize the audited account, its account type, and the discovered plus supplied scope, set `CONFIRMED_REGIONS`, then ask: "Does this scope look correct? Reply 'Confirmed' to proceed, or tell me what to adjust."

**Do not proceed until confirmed.** In unattended mode (Rule 8), audit all regions with spend and label the scope assumed rather than confirmed. Then run resource-level commands only in confirmed regions, apply the management-account scoping convention if `account_type` is `management`, and list exclusions in the report.

### 1.7 Security notification gate

This audit produces hundreds of read calls from one principal in a burst, which looks like reconnaissance to GuardDuty and CloudTrail anomaly detection. Before Phase 2 begins, ask: "Has your security team been notified of this audit? Reply 'Notified' or 'Waived' to proceed." Do not start Phase 2 until one of those answers arrives, and record the answer in Appendix B. In unattended mode (Rule 8), proceed with the header warning "security team was not notified of this audit's API burst" recorded in the report header and Appendix B.

---

<!-- markdownlint-enable -->
