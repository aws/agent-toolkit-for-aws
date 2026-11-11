# Email notifications

AWS Glue sends an Amazon EventBridge event at each step of an auto upgrade. This setup emails five of them to the user. One setup per account and Region covers every auto upgrade job there, including jobs turned on later.

Set up the emails **before** turning on auto upgrade. A job that runs often can reach the approval request within an hour, and EventBridge doesn't replay events from before a rule exists.

## What the setup creates

| Resource | Name | Why |
|---|---|---|
| Amazon SNS topic | `glue-auto-upgrade-notifications` | Sends the emails |
| Email subscription | the user's address | Delivers after the user confirms |
| Amazon EventBridge rules | one per event, in the following table | Each forwards one event with its own email text |
| Topic policy statement | `AllowGlueAutoUpgradeEventBridgeRule` | Lets only these rules publish to the topic |

Every auto upgrade event has the source `aws.glue-autoversion` and the detail type `Auto Version Job State Change`. Only `detail.state` differs. One input transformer can't change its text by state, so each state gets its own rule.

| Rule | `detail.state` | Email, line 1 | What to do |
|---|---|---|---|
| `glue-auto-upgrade-approval-needed` | `CONSENT_REQUIRED` | `<job>` is ready to upgrade from AWS Glue 4.0 to 6.0. | Review the eligibility summary, then approve or decline within 7 days |
| `glue-auto-upgrade-approval-expired` | `CONSENT_EXPIRED` | The upgrade request for `<job>` expired. The job stays on AWS Glue 4.0 and on auto. | Nothing; the next job runs start a new evaluation |
| `glue-auto-upgrade-failed` | `UPGRADE_FAILED` | AWS Glue didn't upgrade `<job>` to AWS Glue 6.0. Reason, and the version it reverted to | Read the auto upgrade evaluation summary |
| `glue-auto-upgrade-finished` | `UPGRADE_COMPLETED` | `<job>` now runs on AWS Glue 6.0. | Check the output of the next runs |
| `glue-auto-upgrade-stopped` | `UPGRADE_STOPPED` | Auto upgrade stopped for `<job>`. Someone set the job to a specific version, or deleted the job. | Nothing, if planned; to restart, set `GlueVersion` to `auto` |

A decline sends no event, so it sends no email.

Each email ends with the console link, the account, and the Region. Two limits come from AWS, not from the skill:

- Every subject is "AWS Notification Message". EventBridge can't set the Amazon SNS subject.
- Each line is wrapped in double quotes. EventBridge needs quotes around each line of a text template and keeps them.

Only a Lambda function between EventBridge and Amazon SNS can change either. The skill doesn't add one. Sources: [Amazon EventBridge input transformation](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-transform-target-input.html), [Customize the default SNS email for EventBridge rule notifications](https://aws.amazon.com/premiumsupport/knowledge-center/change-sns-email-for-eventbridge/).

## Cost

The replies don't mention cost. If the user asks, answer from this table.

| Item | Charge |
|---|---|
| Amazon EventBridge rules on AWS service events (default event bus) | No charge |
| Amazon SNS email | The first 1,000 emails each month are free. After that, Amazon SNS charges per email. See [Amazon SNS pricing](https://aws.amazon.com/sns/pricing/). |
| AWS KMS key (only if the user adds one) | A monthly charge per key. See [AWS KMS pricing](https://aws.amazon.com/kms/pricing/). |

## Encryption

The default topic has no customer managed key. The emails hold job names, versions, and failure reasons, not job data.

Ask about a key in the same question as the email address, before the topic exists. Adding a key later to an existing topic is a manual change, because the setup never overwrites a topic.

Server-side encryption protects each message while Amazon SNS stores it. Amazon SNS decrypts the message before it sends the email. The email in transit and in the inbox isn't protected by the key. No message flows until the user confirms the subscription.

If the user adds a key, tell them these facts:

- EventBridge can publish to an encrypted topic only when the topic uses a customer managed key. The AWS managed key `alias/aws/sns` doesn't work, because you can't change its key policy.
- A customer managed key has a monthly charge.
- The key policy must let `events.amazonaws.com` use `kms:GenerateDataKey*` and `kms:Decrypt`. Don't add `aws:SourceArn` or `aws:SourceAccount` conditions: Amazon SNS doesn't support them for EventBridge to encrypted topics.

The confirmation email subject is "AWS Notification - Subscription Confirmation" ([Receive notifications on new updates](https://docs.aws.amazon.com/linux/al2023/ug/receive-update-notification.html)). Sources: [Managing Amazon SNS encryption keys and costs](https://docs.aws.amazon.com/sns/latest/dg/sns-key-management.html), [Amazon SNS server-side encryption](https://docs.aws.amazon.com/sns/latest/dg/sns-server-side-encryption.html). Checked 2026-11-09.

Use only the key the user names, in step 2 of "Set up". Never create, edit, or schedule deletion of a key.

## Confirm (stop)

With a turn-on request, the Step 2 reply in [assess-and-turn-on.md](assess-and-turn-on.md) already asks for the address (`proceed, email <address>`). Add `key <key ARN>` only if the user names a key. For an email-only request, reply:

```text
AWS Glue can email you when an upgrade needs approval, expires, fails, finishes, or stops. The emails include job names, AWS Glue versions, and failure reasons for all auto upgrade jobs in <region>.

To send these emails to <address>, enter `yes`. To store the messages encrypted with your own AWS KMS key, enter `yes, key <key ARN>`.
```

## Set up

Use these names, so a later run finds and reuses them. Get `<account>` and `<partition>` from `aws sts get-caller-identity --region <region> --no-cli-pager --query "{Account: Account, Arn: Arn}"`. The partition is the second `:` field of `Arn`.

| Resource | Name or ARN |
|---|---|
| Topic | `arn:<partition>:sns:<region>:<account>:glue-auto-upgrade-notifications` |
| Rules | `glue-auto-upgrade-approval-needed`, `glue-auto-upgrade-approval-expired`, `glue-auto-upgrade-failed`, `glue-auto-upgrade-finished`, `glue-auto-upgrade-stopped` |

Rules for every step:

- **Reuse, never overwrite.** Create only what is missing. Don't change a topic, rule, target, or subscription that already exists.
- **Stop on a conflict.** A topic with different encryption, a rule with a different event pattern, or a rule that is turned off is a conflict. Show it and stop.
- **Partial failure.** If a step fails, stop the email setup. Tell the user what you created in this run, and give the cleanup commands at the end of this section. For an email-only request, stop there. With a turn-on request (`proceed, email <address>`), go on to turn on the confirmed jobs. The email failure doesn't block it ([assess-and-turn-on.md](assess-and-turn-on.md), "Step 4: Turn on").

### 1. Check what exists (read-only)

```bash
aws sns list-topics --region <region> --no-cli-pager --query "Topics[?ends_with(TopicArn, ':glue-auto-upgrade-notifications')].TopicArn" --output text
aws sns get-topic-attributes --region <region> --no-cli-pager --topic-arn <topic ARN> --query "Attributes.KmsMasterKeyId" --output text
aws sns list-subscriptions-by-topic --region <region> --no-cli-pager --topic-arn <topic ARN> --query "Subscriptions[?Protocol=='email'].{Endpoint: Endpoint, Arn: SubscriptionArn}"
```

For each rule:

```bash
aws events describe-rule --region <region> --no-cli-pager --name <rule> --query "{EventPattern: EventPattern, State: State}"
aws events list-targets-by-rule --region <region> --no-cli-pager --rule <rule> --query "Targets[].Arn" --output text
```

`ResourceNotFoundException` means the resource is missing. Any other error stops the setup. A subscription whose `Arn` is `PendingConfirmation` isn't confirmed yet: subscribe again in step 5, so that Amazon SNS resends the confirmation email.

If the topic and all 5 rules exist and match, and `<address>` is a confirmed subscription (its `Arn` isn't `PendingConfirmation`), reply: "Email notifications for auto upgrade are already set up in <region>." Otherwise create only what is missing, and subscribe `<address>` in step 5.

### 2. Create the topic (if missing)

```bash
aws sns create-topic --region <region> --no-cli-pager --name glue-auto-upgrade-notifications
```

If the user named a key, add `--attributes KmsMasterKeyId=<key ARN>`.

### 3. Let the rules publish to the topic

Read the policy. Keep every statement, and add or replace only the statement with `Sid` `AllowGlueAutoUpgradeEventBridgeRule`. A new topic can return no policy: then start from `{"Version": "2008-10-17", "Statement": []}`.

```bash
aws sns get-topic-attributes --region <region> --no-cli-pager --topic-arn <topic ARN> --query "Attributes.Policy" --output text
```

```json
{
  "Sid": "AllowGlueAutoUpgradeEventBridgeRule",
  "Effect": "Allow",
  "Principal": {"Service": "events.amazonaws.com"},
  "Action": "sns:Publish",
  "Resource": "<topic ARN>",
  "Condition": {"ArnEquals": {"aws:SourceArn": [
    "arn:<partition>:events:<region>:<account>:rule/glue-auto-upgrade-approval-expired",
    "arn:<partition>:events:<region>:<account>:rule/glue-auto-upgrade-approval-needed",
    "arn:<partition>:events:<region>:<account>:rule/glue-auto-upgrade-failed",
    "arn:<partition>:events:<region>:<account>:rule/glue-auto-upgrade-finished",
    "arn:<partition>:events:<region>:<account>:rule/glue-auto-upgrade-stopped"
  ]}}
}
```

```bash
(D=$(mktemp -d); trap 'rm -rf "$D"' EXIT; cat > "$D/p.json" <<'JSON'
<full policy JSON>
JSON
aws sns set-topic-attributes --region <region> --no-cli-pager --topic-arn <topic ARN> --attribute-name Policy --attribute-value file://"$D/p.json")
```

### 4. Create each rule and its target (if missing)

Every rule uses this event pattern, with its own `detail.state`:

```json
{"source": ["aws.glue-autoversion"], "detail-type": ["Auto Version Job State Change"], "detail": {"state": ["<state>"]}}
```

```bash
(D=$(mktemp -d); trap 'rm -rf "$D"' EXIT; cat > "$D/e.json" <<'JSON'
<event pattern JSON>
JSON
cat > "$D/t.json" <<'JSON'
[{"Id": "email-topic", "Arn": "<topic ARN>", "InputTransformer": <input transformer JSON>}]
JSON
aws events put-rule --region <region> --no-cli-pager --name <rule> --state ENABLED --event-pattern file://"$D/e.json" --description "Emails AWS Glue auto upgrade events" && aws events put-targets --region <region> --no-cli-pager --rule <rule> --targets file://"$D/t.json" --query "FailedEntryCount")
```

`put-targets` reports a failure in `FailedEntryCount`, not in the exit code. Any value other than `0` is a failure.

In another partition, replace `console.aws.amazon.com` in the link: `aws-us-gov` uses `console.amazonaws-us-gov.com`, and `aws-cn` uses `console.amazonaws.cn`. Use these input transformers exactly:

`glue-auto-upgrade-approval-needed`, `detail.state` `CONSENT_REQUIRED`:

```json
{
  "InputPathsMap": {
    "job": "$.detail.jobName",
    "account": "$.account",
    "region": "$.region",
    "from": "$.detail.currentVersion",
    "to": "$.detail.targetVersion"
  },
  "InputTemplate": "\"<job> is ready to upgrade from AWS Glue <from> to <to>.\"\n\"What to do: review the eligibility summary, then approve or decline within 7 days.\"\n\"https://<region>.console.aws.amazon.com/gluestudio/home?region=<region>#/editor/job/<job>/upgradeAnalysis\"\n\"\"\n\"Account <account>, Region <region>\""
}
```

`glue-auto-upgrade-approval-expired`, `detail.state` `CONSENT_EXPIRED`:

```json
{
  "InputPathsMap": {
    "job": "$.detail.jobName",
    "account": "$.account",
    "region": "$.region",
    "from": "$.detail.currentVersion"
  },
  "InputTemplate": "\"The upgrade request for <job> expired. The job stays on AWS Glue <from> and on auto.\"\n\"What to do: nothing. AWS Glue requests approval again after later runs.\"\n\"https://<region>.console.aws.amazon.com/gluestudio/home?region=<region>#/editor/job/<job>/upgradeAnalysis\"\n\"\"\n\"Account <account>, Region <region>\""
}
```

`glue-auto-upgrade-failed`, `detail.state` `UPGRADE_FAILED`:

```json
{
  "InputPathsMap": {
    "job": "$.detail.jobName",
    "account": "$.account",
    "region": "$.region",
    "to": "$.detail.attemptedVersion",
    "back": "$.detail.rollbackVersion",
    "reason": "$.detail.failureReason"
  },
  "InputTemplate": "\"AWS Glue didn't upgrade <job> to AWS Glue <to>.\"\n\"Reason: <reason>\"\n\"AWS Glue reverted the job to <back>.\"\n\"What to do: read the auto upgrade evaluation summary for the changes to make.\"\n\"https://<region>.console.aws.amazon.com/gluestudio/home?region=<region>#/editor/job/<job>/upgradeAnalysis\"\n\"\"\n\"Account <account>, Region <region>\""
}
```

`glue-auto-upgrade-finished`, `detail.state` `UPGRADE_COMPLETED`:

```json
{
  "InputPathsMap": {
    "job": "$.detail.jobName",
    "account": "$.account",
    "region": "$.region",
    "to": "$.detail.newVersion"
  },
  "InputTemplate": "\"<job> now runs on AWS Glue <to>.\"\n\"What to do: check the output of the next runs.\"\n\"https://<region>.console.aws.amazon.com/gluestudio/home?region=<region>#/editor/job/<job>/upgradeAnalysis\"\n\"\"\n\"Account <account>, Region <region>\""
}
```

`glue-auto-upgrade-stopped`, `detail.state` `UPGRADE_STOPPED`:

```json
{
  "InputPathsMap": {
    "job": "$.detail.jobName",
    "account": "$.account",
    "region": "$.region"
  },
  "InputTemplate": "\"Auto upgrade stopped for <job>. Someone set the job to a specific AWS Glue version, or deleted the job.\"\n\"What to do: nothing, if this was planned. To turn auto upgrade on again, set GlueVersion to auto.\"\n\"https://<region>.console.aws.amazon.com/gluestudio/home?region=<region>#/editor/job/<job>/upgradeAnalysis\"\n\"\"\n\"Account <account>, Region <region>\""
}
```

### 5. Subscribe the email address (if not confirmed)

```bash
aws sns subscribe --region <region> --no-cli-pager --topic-arn <topic ARN> --protocol email --notification-endpoint <address>
```

### 6. Reply

For an email-only request, reply as follows. With a turn-on request, use the combined reply in [assess-and-turn-on.md](assess-and-turn-on.md):

```text
AWS Glue can now email <address> about auto upgrades in <region>. You have one step left.

To start receiving email, open the email titled "AWS Notification - Subscription Confirmation" and choose **Confirm subscription**.

Email delivery is best effort. To check your jobs at any time, enter `Which of my Glue jobs in <region> are waiting for upgrade approval?`
```

### Cleanup after a failed setup

The skill doesn't run cleanup. Give the user these commands, only for the resources you created in this run, and let the user run them:

```bash
aws events remove-targets --region <region> --no-cli-pager --rule <rule> --ids email-topic
aws events delete-rule --region <region> --no-cli-pager --name <rule>
aws sns delete-topic --region <region> --no-cli-pager --topic-arn <topic ARN>
```

Never suggest deleting a resource that existed before this run.
