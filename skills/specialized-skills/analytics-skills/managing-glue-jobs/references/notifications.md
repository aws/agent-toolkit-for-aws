# Auto Version Email Notifications (Phase 3)

One notification set per account and Region: an SNS topic, an email subscription, and four EventBridge rules on the default event bus — one per state group — each with one SNS target that formats a plain-text email. The rules match every job's auto version state change in the account and Region; they are not tied to the jobs enabled in this session.

All names are fixed: `glue-auto-version-notifications` (topic and key alias) and `glue-auto-version-<group>` (rules), so an existing setup is found and reused. Below, `<prefix>` stands for `glue-auto-version`; `<region>`, `<account>`, and `<partition>` come from the user and from the `Arn` returned by `aws sts get-caller-identity` (the partition is the second field of that ARN, for example `aws`).

## Resources

| Resource | Name | ARN |
|----------|------|-----|
| SNS topic | `<prefix>-notifications` | `arn:<partition>:sns:<region>:<account>:<prefix>-notifications` |
| Rule: consent required | `<prefix>-consent-required` | `arn:<partition>:events:<region>:<account>:rule/<prefix>-consent-required` |
| Rule: upgrade completed | `<prefix>-upgrade-completed` | `arn:<partition>:events:<region>:<account>:rule/<prefix>-upgrade-completed` |
| Rule: upgrade failed | `<prefix>-upgrade-failed` | `arn:<partition>:events:<region>:<account>:rule/<prefix>-upgrade-failed` |
| Rule: upgrade stopped | `<prefix>-upgrade-stopped` | `arn:<partition>:events:<region>:<account>:rule/<prefix>-upgrade-stopped` |

Every rule has exactly one target, Id `<prefix>-sns`, pointing at the topic.

## State Groups

Each event carries `source` = `aws.glue-autoversion`, `detail-type` = `Auto Version Job State Change`, `resources` = `[<job ARN>]` (not filtered on), and `detail.jobName` + `detail.state`.

| Rule | `detail.state` values | Additional `detail` fields per state |
|------|----------------------|--------------------------------------|
| `<prefix>-consent-required` | `CONSENT_REQUIRED` | `currentVersion`, `targetVersion`, `analysisId`, `consentDeadline` (Unix epoch seconds), `eligibilityReportS3Uri` (only when the report is available) |
| `<prefix>-upgrade-completed` | `UPGRADE_COMPLETED` | `currentVersion` (the previous version), `newVersion`, `analysisId`, `outcome` (`GRADUATED`), `consecutiveSuccesses` |
| `<prefix>-upgrade-failed` | `UPGRADE_FAILED` | `currentVersion`, `attemptedVersion`, `analysisId`, `outcome` (`FAILED`), `failureReason`, `rollbackVersion` |
| `<prefix>-upgrade-stopped` | `CONSENT_EXPIRED` | `analysisId`; `currentVersion` and `targetVersion` when known; no reason field |
| | `UPGRADE_STOPPED` | `currentVersion`, `targetVersion`, `analysisId`, `stoppedReason` |

Never route these states to email: `UPGRADE_RUN_SUCCEEDED` (one per upgrade run — noise), `UPGRADE_RUN_FAILED` and `POST_OBSERVING_FAILED` (each is always followed by `UPGRADE_FAILED` with the same `failureReason`, so emailing them would send an extra email per failure), `OBSERVATION_COMPLETED`, `EVALUATION_STARTED`. No rule matches them.

## Event Patterns

All four rules use the same shape; only `detail.state` differs. There is no `resources` or `jobName` filter: each rule matches that state for every job in the account and Region.

```json
{
  "source": ["aws.glue-autoversion"],
  "detail-type": ["Auto Version Job State Change"],
  "detail": { "state": ["CONSENT_REQUIRED"] }
}
```

| Rule | `detail.state` |
|------|----------------|
| `<prefix>-consent-required` | `["CONSENT_REQUIRED"]` |
| `<prefix>-upgrade-completed` | `["UPGRADE_COMPLETED"]` |
| `<prefix>-upgrade-failed` | `["UPGRADE_FAILED"]` |
| `<prefix>-upgrade-stopped` | `["CONSENT_EXPIRED", "UPGRADE_STOPPED"]` |

## Input Transformers

Each target formats the event as plain text. Every line of `InputTemplate` is a separate double-quoted string; lines are separated by `\n`, and an empty line (`\n\n`) separates the parts of the email. Never send the raw event JSON. The emails contain no state names and no raw timestamps; the consent email shows the event time (`$.time`, UTC). The upgrade-stopped email covers both `CONSENT_EXPIRED` and `UPGRADE_STOPPED` and explains both causes. The console link uses the raw job name; for job names with characters other than letters, digits, '-', '_' or '.', open the job from the console's job list.

### Consent required

```json
{
  "InputPathsMap": {
    "job": "$.detail.jobName",
    "analysis": "$.detail.analysisId",
    "from": "$.detail.currentVersion",
    "to": "$.detail.targetVersion",
    "sent": "$.time",
    "account": "$.account",
    "region": "$.region"
  },
  "InputTemplate": "\"AWS Glue auto version: approve the upgrade of <job> to Glue <to>\"\n\n\"What happened\"\n\"AWS Glue watched runs of <job> on Glue <from> and found no blocking issues.\"\n\"The upgrade to Glue <to> now needs your approval. Account <account>, Region <region>.\"\n\n\"What to do\"\n\"Review the upgrade eligibility report, then approve or decline.\"\n\"Sent <sent> (UTC). The approval request expires 7 days after this time. If you don't decide, the job stays on Glue <from>.\"\n\"Once approved, up to 3 of the job's normal runs use Glue <to> and write to their real output locations. That data is not rolled back.\"\n\n\"Review and approve: https://<region>.console.aws.amazon.com/gluestudio/home?region=<region>#/editor/job/<job>/upgradeAnalysis\"\n\"Or ask your agent: 'review the pending Glue upgrade for <job> in <region>'.\"\n\n\"Analysis ID: <analysis>\""
}
```

### Upgrade completed

```json
{
  "InputPathsMap": {
    "job": "$.detail.jobName",
    "analysis": "$.detail.analysisId",
    "from": "$.detail.currentVersion",
    "to": "$.detail.newVersion",
    "successes": "$.detail.consecutiveSuccesses",
    "account": "$.account",
    "region": "$.region"
  },
  "InputTemplate": "\"AWS Glue auto version: <job> is now on Glue <to>\"\n\n\"What happened\"\n\"<job> passed <successes> validation runs on Glue <to> and was upgraded from Glue <from>.\"\n\"Account <account>, Region <region>.\"\n\n\"What to do\"\n\"Nothing. GlueVersion stays auto, so future Glue versions will ask for your approval the same way.\"\n\n\"Upgrade summary: https://<region>.console.aws.amazon.com/gluestudio/home?region=<region>#/editor/job/<job>/upgradeAnalysis\"\n\n\"Analysis ID: <analysis>\""
}
```

### Upgrade failed

```json
{
  "InputPathsMap": {
    "job": "$.detail.jobName",
    "analysis": "$.detail.analysisId",
    "attempted": "$.detail.attemptedVersion",
    "rollback": "$.detail.rollbackVersion",
    "reason": "$.detail.failureReason",
    "account": "$.account",
    "region": "$.region"
  },
  "InputTemplate": "\"AWS Glue auto version: <job> was not upgraded and is back on Glue <rollback>\"\n\n\"What happened\"\n\"AWS Glue stopped the upgrade of <job> to Glue <attempted> and set the job back to Glue <rollback>.\"\n\"Auto version is now off for this job. Account <account>, Region <region>.\"\n\"Reason from AWS Glue: <reason>\"\n\n\"What to do\"\n\"Check the evaluation summary on the analysis page in the AWS Glue console (link below), or ask your agent: 'why did the Glue upgrade of <job> fail'.\"\n\n\"Analysis: https://<region>.console.aws.amazon.com/gluestudio/home?region=<region>#/editor/job/<job>/upgradeAnalysis\"\n\n\"Analysis ID: <analysis>\""
}
```

### Upgrade stopped (consent expired or auto version turned off)

```json
{
  "InputPathsMap": {
    "job": "$.detail.jobName",
    "analysis": "$.detail.analysisId",
    "account": "$.account",
    "region": "$.region"
  },
  "InputTemplate": "\"AWS Glue auto version: the upgrade of <job> did not go ahead\"\n\n\"What happened\"\n\"AWS Glue stopped the upgrade of <job>. Account <account>, Region <region>.\"\n\n\"What to do\"\n\"Check the upgrade analysis in the AWS Glue console (link below), or ask your agent: 'why did the Glue upgrade of <job> not go ahead'.\"\n\n\"Analysis: https://<region>.console.aws.amazon.com/gluestudio/home?region=<region>#/editor/job/<job>/upgradeAnalysis\"\n\n\"Analysis ID: <analysis>\""
}
```

## Procedure

Run every command with `--region <region>`. With the AWS CLI, pass JSON through files (`file://`), not inline shell strings: the templates contain quotes and `<...>` placeholders that shells mangle. With the AWS MCP server's `run_script` tool, which has no local file access, pass the same JSON documents (key policy, event patterns, targets, topic policy) directly in the tool call.

0. **Existing setup (read-only).**
   - Run `aws events list-rules --region <region> --no-cli-pager --query "Rules[?contains(EventPattern || '', 'aws.glue-autoversion')].{Name:Name,State:State,EventPattern:EventPattern}"`.
   - For each of the four fixed rules found, run `aws events list-targets-by-rule --rule <rule>`, then `aws sns get-topic-attributes` and `aws sns list-subscriptions-by-topic` on the target topic.
   - **Already set up:** all four fixed rules exist with exactly the patterns in Event Patterns above (same `detail.state` list, no `resources` or `jobName` filter), an SNS target with exactly the group's transformer above, and at least one email subscription (confirmed or pending); list the subscribed addresses. Report it as already set up (topic, rules, subscription status) and do not offer or run the setup again.
   - **Older setup:** a fixed rule from an earlier version of this skill differs from the current one: its pattern has a `resources` or `jobName` filter, or a different `detail.state` list (for example `<prefix>-upgrade-failed` still includes `UPGRADE_RUN_FAILED`, which sends an extra email for each failed upgrade run, or `POST_OBSERVING_FAILED`, which sends a separate email before every rollback email), or its target's InputTransformer differs. Report each such rule with what differs ("currently limited to N jobs", "also emails each failed upgrade run", "also emails a separate message before every rollback email", "uses the earlier email text"). When several rules differ, offer one reply that names all of them (for example "update glue-auto-version-consent-required, glue-auto-version-upgrade-failed and glue-auto-version-upgrade-stopped"). Offer to update it to the current pattern and transformer: `put-rule` with the same name, description and state, then `put-targets` for its target. Run the update only after the user confirms it by naming the rule (for example "update glue-auto-version-upgrade-failed"). Otherwise leave it unchanged and report it as outdated.
   - **Other auto version rules:** rules with other names whose pattern matches `aws.glue-autoversion`, for example from a different prefix. List them by name. Never modify or delete them unless the user confirms by naming the rule (for example "delete rule X"); then run `aws events remove-targets` followed by `aws events delete-rule` for that rule only.
   - **Partial setup:** some resources are missing or different. Create only what is missing and update only what differs (steps 2-7; existing rules and targets only per Older setup). Report each resource as created, updated or unchanged.
1. **Confirm inputs.** Ask only for the recipient email address if the user hasn't given it, and ask the user to confirm the address belongs to personnel authorized to receive job names, Glue versions, failure reasons and AWS Glue console links for every auto version job in this account and Region. Use the fixed names above. Encryption is one of:
   - (a) the user's own customer-managed KMS key;
   - (b) by default, a dedicated new customer-managed key `alias/<prefix>-notifications` (step 2);
   - (c) no encryption, only when the user explicitly opts out.

   The preview for this phase lists the key alias, the key policy below, and its cost: a customer-managed key has a monthly charge plus request charges; see [AWS KMS pricing](https://aws.amazon.com/kms/pricing/). It also states that the AWS managed key `alias/aws/sns` cannot be used: its key policy cannot be changed to let `events.amazonaws.com` use it, so EventBridge deliveries to the topic would fail. The Phase 3 confirmation covers the key as well.
2. **Key.**
   - Dedicated key (default): `aws kms create-key --description "AWS Glue auto version notifications (<prefix>)" --tags TagKey=glue-auto-version-notifications,TagValue=<prefix> --policy file://key-policy.json`, then `aws kms create-alias --alias-name alias/<prefix>-notifications --target-key-id <KeyId>`. The key policy keeps account-root administration (so the key cannot become unmanageable) and lets EventBridge use the key only for the four rules:

     ```json
     {
       "Version": "2012-10-17",
       "Statement": [
         {
           "Sid": "EnableRootAdministration",
           "Effect": "Allow",
           "Principal": { "AWS": "arn:<partition>:iam::<account>:root" },
           "Action": "kms:*",
           "Resource": "*"
         },
         {
           "Sid": "AllowGlueAutoVersionEventBridge",
           "Effect": "Allow",
           "Principal": { "Service": "events.amazonaws.com" },
           "Action": ["kms:GenerateDataKey*", "kms:Decrypt"],
           "Resource": "*",
           "Condition": {
             "ArnEquals": {
               "aws:SourceArn": [
                 "arn:<partition>:events:<region>:<account>:rule/<prefix>-consent-required",
                 "arn:<partition>:events:<region>:<account>:rule/<prefix>-upgrade-completed",
                 "arn:<partition>:events:<region>:<account>:rule/<prefix>-upgrade-failed",
                 "arn:<partition>:events:<region>:<account>:rule/<prefix>-upgrade-stopped"
               ]
             }
           }
         }
       ]
     }
     ```

     The rule ARNs are known before the rules exist, because they follow from the prefix.
   - User-supplied key: use it as is and never edit its key policy. Tell the user the policy must contain the `AllowGlueAutoVersionEventBridge` statement above (or an equivalent grant to `events.amazonaws.com`); without it, delivery fails without an error.
   - Opt-out: only on the user's explicit request. Warn that the topic is unencrypted at rest and that the emails carry metadata (job names, versions, analysis IDs, reason text, console links) — never job data. A wish to avoid cost is not an opt-out: recommend the dedicated key, state its cost (a monthly charge plus request charges; see AWS KMS pricing), and create an unencrypted topic only if the user then explicitly opts out after the warning.
3. **Topic.** `aws sns create-topic --name <prefix>-notifications --attributes KmsMasterKeyId=<key ARN>` (omit `--attributes` only on the opt-out). To check whether the topic already exists, use `aws sns list-topics` or `get-topic-attributes`; never call `create-topic` as a check. Call `create-topic` only after the Phase 3 confirmation, with the key attribute (omitted only on the opt-out). It is idempotent when the attributes match and returns the existing ARN. If it fails because the topic already exists with different attributes (for example a different KMS key), report the error and ask the user how to proceed; never change the topic's encryption silently.
4. **Rules.** For each of the four rules: if `describe-rule` shows the same account-level pattern, leave it unchanged. Otherwise run `aws events put-rule --name <rule> --event-pattern file://<rule>-pattern.json --state ENABLED --description "AWS Glue auto version notifications: <group>"` (for an existing rule, keep its description and state). For an existing rule that differs, do this only after the named confirmation from step 0; without it, leave the rule unchanged.
5. **Targets.** For each rule: `aws events list-targets-by-rule --rule <rule>`; call `put-targets` only if the target with Id `<prefix>-sns` is missing, points to another ARN, or has a different InputTransformer. `aws events put-targets --rule <rule> --targets file://<rule>-targets.json` with one target: `{"Id": "<prefix>-sns", "Arn": "<topic ARN>", "InputTransformer": <group transformer above>}`. For an existing target whose InputTransformer differs, do this only after the named confirmation from step 0; without it, leave the target unchanged.
6. **Topic policy.** Read the current policy (`aws sns get-topic-attributes --topic-arn <topic ARN>` → `Attributes.Policy`). Remove any existing statement with Sid `AllowGlueAutoVersionEventBridge`, append the statement below, keep every other statement unchanged, then `aws sns set-topic-attributes --topic-arn <topic ARN> --attribute-name Policy --attribute-value file://topic-policy.json`.

   ```json
   {
     "Sid": "AllowGlueAutoVersionEventBridge",
     "Effect": "Allow",
     "Principal": { "Service": "events.amazonaws.com" },
     "Action": "sns:Publish",
     "Resource": "arn:<partition>:sns:<region>:<account>:<prefix>-notifications",
     "Condition": {
       "ArnEquals": {
         "aws:SourceArn": [
           "arn:<partition>:events:<region>:<account>:rule/<prefix>-consent-required",
           "arn:<partition>:events:<region>:<account>:rule/<prefix>-upgrade-completed",
           "arn:<partition>:events:<region>:<account>:rule/<prefix>-upgrade-failed",
           "arn:<partition>:events:<region>:<account>:rule/<prefix>-upgrade-stopped"
         ]
       }
     }
   }
   ```

   The condition lists the four exact rule ARNs — never a `rule/*` wildcard.
7. **Subscription.** `aws sns list-subscriptions-by-topic --topic-arn <topic ARN>`; if the address is already subscribed (confirmed or pending), do not subscribe again. Otherwise `aws sns subscribe --topic-arn <topic ARN> --protocol email --notification-endpoint <address>`. Tell the user: AWS sends a confirmation email, and nothing is delivered until the recipient clicks the confirmation link.
8. **Report.** Start with the one thing left for the user: click the confirmation link in the email from AWS Notifications; nothing is delivered until then. Then one line per outcome, for example `Created: KMS key alias/glue-auto-version-notifications, SNS topic glue-auto-version-notifications, 4 EventBridge rules (every auto version job in <region>), email subscription for <address> (pending confirmation).` Use `Updated:` and `Unchanged:` lines the same way, and list any other auto version rules found in step 0 by name. Give the ARNs, rule patterns and policies only when the user asks for details.

## New Jobs

Nothing to do: the rules are account-level, so jobs enabled later are covered automatically. Do not run Phase 3 again for new jobs.

## Delivery Caveats

- Auto version events are best effort and an email can be missed. Tell the user to check status directly (the consent workflow ([auto-version-consent.md](auto-version-consent.md)), or `aws glue get-job` → `Job.AutoUpgradeMetadata`) instead of relying on email alone.
- The `CONSENT_REQUIRED` email shows when the approval request was sent (UTC); the request expires 7 days after that. `get-job-upgrade-analysis` does not return the deadline.
