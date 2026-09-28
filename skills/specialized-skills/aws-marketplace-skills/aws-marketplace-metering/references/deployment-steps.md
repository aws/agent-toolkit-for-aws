### Step 1: Generate the Code

Generate these files using the templates in `references/`. Replace the placeholders with the user's actual values.

> **Materialize, then deploy the same files (parity).** Write these artifacts to disk in the seller's workspace and deploy exactly those files — `deploy.sh` runs `sam build --template-file template.yaml` / `template-events.yaml` from the on-disk copies, so the deployed stack always matches the source. Do NOT deploy an inline or transient template that you do not also leave in the workspace. For a **modify/extend** case (an existing stack), edit the seller's existing on-disk files in place (merging environment variables) rather than scaffolding a fresh copy that diverges from what is deployed. Leave all artifacts in the workspace after deploying: they are the seller-owned source of truth, so the seller can version-control, re-deploy, test, and further develop them — customizing the marked `TODO:` sections (usage-write logic, VMT tags). `deploy.sh` fails fast (read-only) if the template it is about to build is missing or renamed.

| File | Purpose | Template |
|------|---------|----------|
| `template.yaml` | Main SAM stack (API GW, DynamoDB, Register + metering-pipeline Lambdas) | `assets/template-main.yaml` |
| `template-events.yaml` | Events stack (EventBridge rule, SQS, Subscription Lambda) | `assets/template-events.yaml` |
| `src/handlers/register.py` | ResolveCustomer — buyer onboarding | `scripts/register.py` |
| `src/handlers/metering_core.py` | Shared metering logic imported by the pipeline handlers (GSI discovery, targeted read, VMT merge, validation, BatchMeterUsage submit) | `scripts/metering_core.py` |
| `src/handlers/discoverer.py` | discoverer — hourly, 30 invocations; enqueues per-group work + age-out | `scripts/discoverer.py` |
| `src/handlers/aggregator.py` | aggregator — folds a group, validates, conditional-writes aggregated_usage, enqueues cleanup | `scripts/aggregator.py` |
| `src/handlers/cleanup.py` | cleanup — clears raw-row `meteringPending` (per-key UpdateItem) | `scripts/cleanup.py` |
| `src/handlers/submitter.py` | submitter — reads aggregated_usage, BatchMeterUsage, writes back | `scripts/submitter.py` |
| `src/handlers/expiry.py` | expiry — scheduled aggregated_usage age-out (>24h / post-grace previous-month) | `scripts/expiry.py` |
| `src/handlers/subscription.py` | EventBridge/SNS notification processing | `scripts/subscription.py` |
| `src/requirements.txt` | Python dependencies (latest AWS SDK) | `assets/requirements.txt` |

> **Important:** Always include `requirements.txt` with `boto3>=1.35.0` in the `src/` directory. SAM will bundle the latest AWS SDK with the Lambda functions. The Lambda runtime's built-in boto3 may be outdated and missing support for newer Marketplace API features (e.g., `LicenseArn` in `BatchMeterUsage`).

**Placeholders to replace:**

- `{{PRODUCT_CODE}}` — the actual metering product code
- `{{DEPLOYMENT_REGION}}` — e.g. `us-west-2`
- `{{STACK_PREFIX}}` — a unique prefix for resource names to avoid collisions (e.g. `myapp`)

### Step 2: Deploy Events Stack FIRST (us-east-1)

The events stack must deploy first because it creates the subscriptions table that the main stack references.

```bash
sam build --template-file template-events.yaml --region us-east-1
sam deploy \
  --template-file .aws-sam/build/template.yaml \
  --stack-name awsmp-events-stack \
  --region us-east-1 \
  --capabilities CAPABILITY_NAMED_IAM \
  --s3-bucket aws-sam-cli-managed-default-<ACCOUNT_ID>-us-east-1 \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset
```

> Use `--capabilities CAPABILITY_NAMED_IAM` (the events stack has a named role, `awsmp-events-subscription-role`) and `--s3-bucket` with a directly-provisioned artifact bucket — **not** `--resolve-s3`, which bootstraps a non-`awsmp-*` `aws-sam-cli-managed-default` CloudFormation stack the least-privilege deployer policy denies. `deploy.sh` creates the SSE+versioned artifact bucket for you (per region) and passes `--s3-bucket`.

Note the `SubscribersTableName` from the stack outputs.

#### Wiring alarm notifications to your ticketing system

Alarms are always created, but their notification actions are OPTIONAL: pass an in-region
SNS topic ARN via `AlertsTopicArn` (a us-east-1 topic for the events stack; a
metering-region topic for the main stack) and the alarms will notify it. Neither the
deployer role nor any Lambda publishes to the topic — CloudWatch fires the action, and
acting on alarms is the seller's responsibility. Create your own SNS topic and subscribe
your alerting/ticketing system to it:

> **Encrypt the topic at rest.** Alarm notifications can carry sensitive identifiers (buyer AWS account IDs, license ARNs, resource names), so create the SNS topic with server-side encryption — the AWS-managed key `alias/aws/sns` at minimum, or a customer-managed KMS key: `aws sns create-topic --name <NAME> --attributes KmsMasterKeyId=alias/aws/sns`.
>
> **Validate recipients.** Ensure only authorized operations personnel are subscribed. Review SNS subscriptions periodically and consider SNS access / subscription filter policies.

- **Email (simplest):** `aws sns subscribe --topic-arn <TOPIC_ARN> --protocol email --endpoint ops@company.com`
- **Jira Cloud:** Use [AWS Chatbot → Jira integration](https://docs.aws.amazon.com/chatbot/latest/adminguide/jira-setup.html) or Jira's native SNS subscription
- **PagerDuty:** Create a PagerDuty [SNS integration](https://support.pagerduty.com/docs/aws-cloudwatch-integration-guide) (Events API v2 endpoint as HTTPS subscription)
- **ServiceNow:** Deploy a thin Lambda subscriber that calls the SNOW REST API (`/api/now/table/incident`)
- **Slack:** Use [AWS Chatbot → Slack](https://docs.aws.amazon.com/chatbot/latest/adminguide/slack-setup.html)

Then pass the topic ARN as `AlertsTopicArn` when deploying each stack.

### Step 3: Deploy Main Stack (Seller's Region)

Use the product code in the stack name to avoid conflicts (especially for multi-product sellers). `<DEPLOYMENT_REGION>` is the seller's metering region and **may be `us-east-1`** — us-east-1 is a supported `BatchMeterUsage` region. When it is us-east-1, the main stack simply deploys alongside the events stack (single-region, no cross-region reads). For the full list of regions where `BatchMeterUsage` is supported, see [BatchMeterUsage region support](https://docs.aws.amazon.com/marketplace/latest/developerguide/metering-regions.html#batchmeterusage-region-support):

```bash
sam build --region <DEPLOYMENT_REGION>
sam deploy \
  --stack-name awsmp-<PRODUCT_CODE>-metering \
  --region <DEPLOYMENT_REGION> \
  --capabilities CAPABILITY_NAMED_IAM \
  --s3-bucket aws-sam-cli-managed-default-<ACCOUNT_ID>-<DEPLOYMENT_REGION> \
  --no-confirm-changeset \
  --no-fail-on-empty-changeset \
  --parameter-overrides \
    "ProductCode=<PRODUCT_CODE>" \
    "StackPrefix=awsmp-<PRODUCT_CODE>" \
    "SubscribersTableName=<SUBSCRIBERS_TABLE_NAME>" \
    "StageName=<STAGE_NAME_FROM_QUESTIONNAIRE>" \
    "WebAclArn=<WAFV2_WEBACL_ARN>" \
    "LogsKmsKeyArn=<KMS_KEY_ARN_FOR_LOGS>" \
    "LogRetentionInDays=90" \
    "AllowedRegistrationFields=<comma,separated,form,fields>" \
    "PromotedProfileFields=<subset,to,index>" \
    "PermissionsBoundaryName=awsmp-metering-boundary"
```

> **Prerequisite — permissions boundary MUST exist first.** SAM auto-generates the Lambda
> execution roles, and the deployer role only permits `iam:CreateRole` when a matching
> `iam:PermissionsBoundary` is attached. Create the boundary policy (see
> `references/iam-credentials.md` for `boundary.json`) BEFORE deploying, and keep its name
> equal to `PermissionsBoundaryName` (default `awsmp-metering-boundary`). `deploy.sh` checks
> for it and fails fast if missing:
>
> ```bash
> aws iam create-policy --policy-name awsmp-metering-boundary --policy-document file://boundary.json
> ```
>
> **Security parameters:**
>
> - `StageName` has **no default** and an `AllowedPattern` that rejects an empty value; it is a **mandatory** questionnaire answer (Q4) — the seller MUST supply a non-empty value (e.g. `v1`, `live`, or `prod` — their choice). A direct `sam deploy` fails fast at the template level if it is missing/empty, and `deploy.sh` performs the same check; there is no fallback to `prod`.
> - `WebAclArn` — strongly recommended: associate a WAFv2 REGIONAL WebACL with the unauthenticated registration stage (rate-based + common-exploit rules). Omit only if a WAF is attached out-of-band.
> - `LogsKmsKeyArn` — KMS-encrypts the Lambda + API access log groups (they contain buyer account IDs / license ARNs). The key policy must allow `logs.<region>.amazonaws.com`.
> - `AllowedRegistrationFields` — the ONLY registration-form fields the public register Lambda will persist (each length-bounded), written as a `registrationData` map on the **in-region `customer-profile` table** (buyer PII stays in-region; the us-east-1 subscribers table is PII-free). Leave empty to persist none.
> - `PromotedProfileFields` — a subset of `AllowedRegistrationFields` to promote to top-level attributes on the customer-profile table so a GSI can look profiles up by that field (e.g. `email`). Add the matching `AttributeDefinition` + GSI in the `CustomerProfileTable` `TODO(seller)` block. Leave empty for none.

### Step 4: Configure Fulfillment URL

1. Determine the Fulfillment URL: the **branded registration page URL** (the CloudFront/custom-domain front-end from `references/registration-page.md`). Use the raw `RegistrationUrl` main-stack output ONLY as a bare-bones smoke-test fallback.
2. Go to [AWS Marketplace Management Portal](https://aws.amazon.com/marketplace/management/products/saas)
3. Select the product → Request changes → Update fulfillment options → Edit default fulfillment URL
4. Paste the branded page URL (the Marketplace redirect must land the buyer's browser on a page that renders; the page then POSTs the token + captured fields to `RegistrationUrl`)

> **The seller does this manually.** The skill/deployer intentionally has NO catalog-write
> permission (no `aws-marketplace:StartChangeSet`) — updating the product's Fulfillment URL is
> a seller action in the Management Portal. For testing, the seller sets it to the
> `RegistrationUrl` output above; do not request catalog-write access to automate this.
>
> **`RegistrationUrl` is a backend, not the finished onboarding page.** For a smoke test the
> Fulfillment URL can point straight at it, but most sellers want a **branded buyer-facing
> registration page** (S3 + CloudFront, optional custom domain) that captures extra buyer
> fields — including the Know Your Buyer (KYB) fields — and forwards the token + fields to
> `RegistrationUrl`. Offer to build it and set `ALLOWED_REGISTRATION_FIELDS` accordingly. See
> `references/registration-page.md`.

### Step 5: Test End-to-End

The agent runs the verification steps below directly. The **manual, seller/browser
prerequisites — allowlist, subscribe, and Set up your account — are NOT restated here to
avoid drift; they are owned authoritatively by `references/test-plan.md` §0** (which also
covers the AMMP Fulfillment-URL change set and the seller↔skill handshake). Complete
test-plan.md §0 first, then run these.

> **This is the core happy path.** For the FULL structured test plan — the manual prerequisites (test-plan.md §0), the scoped test-case suite (registration, rejects by reason, server-side `InvalidUsageDimension`, idempotency, age-out/expiry, month-boundary, direct-submit cases), seller-supplied custom tests, and how to POLL for asynchronous `License Updated`/EventBridge results (default: up to ~5 min at 15s intervals) — see `references/test-plan.md`.

1. **Verify registration + license** — after test-plan.md §0 (subscribe → Set up your account), poll the unified subscribers table in us-east-1 until `licenseArn` and `productCode` are populated (from the `License Updated` event; default poll up to ~5 min at 15s intervals):

   ```bash
   aws dynamodb scan --table-name <STACK_PREFIX>-subscribers --region us-east-1
   ```

   Confirm `customerAWSAccountId`, `productCode`, `licenseArn`, and `subscriptionStatus=active`.

2. **Record test usage** — insert a dummy usage row. The usage table is keyed by `licenseArn` (PK) + `customerAWSAccountId#dimension#timestamp` (SK composite, **SECOND precision**), and the pipeline discovers pending usage via the `metering_pending` GSI. The sort-key suffix MUST be an exact whole-second timestamp `YYYY-MM-DDTHH:MM:SS` (NOT millisecond — the aggregator rejects a non-second suffix as `MalformedTimestamp`), its account/dimension segments MUST match the row's own `customerAWSAccountId`/`dimension` attributes, and `meteringPending` MUST equal the row's hour bucket (`YYYY-MM-DDTHH`) so it appears in the GSI. Only COMPLETED hours are processed (`now-23h … now-1h`) and only after the configured `MeteringLockHours`, so use a recent PAST hour older than the lock (default lock 1 ⇒ any hour ≥1h ago works):

   ```bash
   HOUR=$(date -u -d '2 hours ago' +%Y-%m-%dT%H)   # completed UTC hour, older than the default lock
   SEC="${HOUR}:00:07"                              # whole-second UTC precision (NOT .000Z, NOT local time)
   aws dynamodb put-item --table-name <STACK_PREFIX>-usage --region <DEPLOYMENT_REGION> --item "{
     \"licenseArn\": {\"S\": \"<LICENSE_ARN>\"},
     \"customerAWSAccountId_dimension_timestamp\": {\"S\": \"<BUYER_ACCOUNT_ID>#<DIMENSION_KEY>#${SEC}\"},
     \"customerAWSAccountId\": {\"S\": \"<BUYER_ACCOUNT_ID>\"},
     \"dimension\": {\"S\": \"<DIMENSION_KEY>\"},
     \"timestamp\": {\"S\": \"${SEC}\"},
     \"meteringPending\": {\"S\": \"${HOUR}\"},
     \"quantity\": {\"N\": \"5\"}
   }"
   ```

3. **Trigger the pipeline** — the pipeline is decoupled (discoverer → work SQS → aggregator → cleanup SQS → cleanup; a scheduled submitter drains `aggregated_usage`). Invoke the **discoverer** in `meter` mode for the hour offset matching your test hour (offset = hours-ago; here `2`), then let the SQS chain run, then invoke the **submitter**:

   ```bash
   # a) discover + enqueue the group for that completed hour (offset must be >= MeteringLockHours)
   aws lambda invoke --function-name <DISCOVERER_FUNCTION_NAME> --region <DEPLOYMENT_REGION> \
     --payload '{"mode":"meter","hourOffset":2}' /tmp/discoverer.json && cat /tmp/discoverer.json
   # b) the aggregator (SQS-triggered) folds the group and conditionally writes aggregated_usage;
   #    the cleanup Lambda (SQS-triggered) then stamps the raw row Aggregated. Wait a few seconds.
   sleep 10
   # c) submit the aggregated record to BatchMeterUsage
   aws lambda invoke --function-name <SUBMITTER_FUNCTION_NAME> --region <DEPLOYMENT_REGION> \
     --payload '{}' /tmp/submitter.json && cat /tmp/submitter.json
   ```

4. **Verify each stage succeeded:**

   ```bash
   # Raw row finalized as Aggregated (meteringPending removed, meteringStatus=Aggregated):
   aws dynamodb get-item --table-name <STACK_PREFIX>-usage --region <DEPLOYMENT_REGION> \
     --key "{\"licenseArn\":{\"S\":\"<LICENSE_ARN>\"},\"customerAWSAccountId_dimension_timestamp\":{\"S\":\"<BUYER_ACCOUNT_ID>#<DIMENSION_KEY>#${SEC}\"}}"
   # Aggregated record carries a MeteringRecordId + meteringStatus=Success after the submitter:
   aws dynamodb scan --table-name <STACK_PREFIX>-aggregated-usage --region <DEPLOYMENT_REGION>
   # Submitter log shows a successful BatchMeterUsage (no InvalidUsageDimension / CustomerNotSubscribed):
   aws logs filter-log-events --log-group-name /aws/lambda/<SUBMITTER_FUNCTION_NAME> \
     --region <DEPLOYMENT_REGION> --start-time $(date -d '5 minutes ago' +%s000) \
     --query 'events[*].message' --output text
   ```

   - A raw row still carrying `meteringPending` after the run, plus a `UsageRecordRejected` metric, means the **writer contract was violated** — check the reason code (`MalformedTimestamp`, `MalformedSortKey`, `SortKeyMismatch`, `MissingDimension`, `NegativeQuantity`, `NonIntegerQuantity`, …) in the aggregator log and fix the row.
   - An `aggregated_usage` row with `meteringStatus=RejectedClientSide` and reason `InvalidUsageDimensionException` means the dimension key is not defined in the catalog — `BatchMeterUsage` failed the call with a request-level `InvalidUsageDimensionException` (server-authoritative), which the submitter isolated to this record (surfaced on the `BatchMeterUsageException` metric). Fix the dimension in the AMMP listing (no redeploy needed).

### Step 6: Validate via Logs

```bash
# Registration Lambda logs
aws logs filter-log-events \
  --log-group-name /aws/lambda/<REGISTER_FUNCTION_NAME> \
  --region <DEPLOYMENT_REGION> \
  --start-time $(date -d '1 hour ago' +%s000) \
  --query 'events[*].message' --output text

# Pipeline logs (decoupled: discoverer / aggregator / cleanup / submitter)
for fn in <DISCOVERER_FUNCTION_NAME> <AGGREGATOR_FUNCTION_NAME> <CLEANUP_FUNCTION_NAME> <SUBMITTER_FUNCTION_NAME>; do
  echo "=== $fn ==="
  aws logs filter-log-events \
    --log-group-name "/aws/lambda/$fn" \
    --region <DEPLOYMENT_REGION> \
    --start-time $(date -d '1 hour ago' +%s000) \
    --query 'events[*].message' --output text
done

# Subscription Lambda logs (always us-east-1)
aws logs filter-log-events \
  --log-group-name /aws/lambda/<SUBSCRIPTION_FUNCTION_NAME> \
  --region us-east-1 \
  --start-time $(date -d '1 hour ago' +%s000) \
  --query 'events[*].message' --output text
```

## Per-region prerequisite: API Gateway CloudWatch Logs account role

Because the registration API enables stage access logging, API Gateway requires a
**per-region, account-level** CloudWatch Logs role BEFORE any logging-enabled stage can be
created — otherwise stage create fails with "CloudWatch Logs role ARN must be set in
account settings to enable logging". This is an account-global setting **per region**, so
the first region you deploy to may already have it while every additional region needs it
set. `deploy.sh` provisions this idempotently for each metering region (`ensure_apigw_cw_role`):
it creates the `awsmp-apigw-cloudwatch-logs` role once and sets the region's
`cloudwatchRoleArn` if unset. If deploying by hand, run before the main stack per region:

```bash
aws apigateway update-account --region <DEPLOYMENT_REGION> \
  --patch-operations op=replace,path=/cloudwatchRoleArn,value=arn:aws:iam::<ACCOUNT_ID>:role/awsmp-apigw-cloudwatch-logs
```

## Recovering from a failed deploy

A mid-deploy failure/rollback can leave behind `DeletionPolicy: Retain` resources — the
usage table, the subscribers table, the subscription role, and especially the
`/aws/lambda/awsmp-*` **log groups** (which are easy to miss — they are not listed in the
rollback resource summary) — and can orphan a partially-created baseline WebACL. On retry
these collide (`AWS::EarlyValidation::ResourceExistenceCheck`, or WebACL `AlreadyExists`).

`deploy.sh` runs a **read-only** preflight that detects likely collisions and prints
guidance; it never auto-deletes. Remove a reviewed leftover resource with your own
credentials, then retry:

- Leftover log group after a failed first deploy:
  `aws logs delete-log-group --log-group-name /aws/lambda/<prefix>-<fn> --region <region>`
- Empty usage table after a **failed first** deploy (only when it holds no billable usage —
  never delete a table with real usage):
  `aws dynamodb delete-table --table-name <prefix>-usage --region <region>`
- Orphaned baseline WebACL (`AlreadyExists`): the real fix is prevention — the deployer
  policy grants `wafv2:ListTagsForResource` + `wafv2:GetWebACLForResource` so the create+tag
  succeeds atomically. If an orphan does exist, delete the reviewed WebACL with your own
  credentials, then retry. The deployer role deliberately does NOT have account-wide
  `wafv2:ListWebACLs`/delete to auto-clean.
