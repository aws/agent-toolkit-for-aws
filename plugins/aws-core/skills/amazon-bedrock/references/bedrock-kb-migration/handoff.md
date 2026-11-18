# Handoff (Phase 5): what changed and what the customer runs next

The last phase of the [migration guide](references/migrate-knowledge-base-to-managed.md), and it is
read-only. It ends every migration: after a KB-path build, after the IaC path emits its file, and when the
customer stops at the plan. Read this file when you write the handoff reply, even if you read it earlier.

## Contents

- [How to write the handoff](#how-to-write-the-handoff)
- [1. What changed](#1-what-changed)
- [2. The customer-run next steps](#2-the-customer-run-next-steps)
- [3. Monitoring](#3-monitoring)
- [4. Audit trail](#4-audit-trail)
- [5. Security follow-ups](#5-security-follow-ups)
- [6. Rollback](#6-rollback)

## How to write the handoff

Give this handoff **in the reply itself**; the files written to `output_dir` are supporting detail,
never a stand-in for stating what changed and what the customer must do next. Write it as the six labelled
blocks below, in this order. A reply that leaves a block out is not a complete handoff.

**Each customer-run step has three parts, and is labelled as the customer's to run:**

- **The command.** Say what it must do, then write it at run time from the current
  [AWS CLI reference](https://docs.aws.amazon.com/cli/latest/reference/) (for a Terraform deploy, the
  current Terraform CLI documentation), with this migration's IDs and Region filled in. Use the customer's
  own profile that allows the step. When you don't know its name, still give the full handoff in this
  reply: put a named placeholder for the profile in each command (for example `<YOUR_PROFILE>`) and ask
  for the name in the same reply. Never guess it. Never write a step under a profile limited to policy A,
  or to policy A plus policy B ([safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md)):
  policy A is read-only and policy B adds only the create and poll permissions of the agent's own build, so
  neither grants these steps. A step with no AWS command (cut over, the ignore-file step) says what to change
  and how to confirm it, and gets no invented command. This skill stores no command lines for these steps.
  Never run one yourself.
- **Its public doc page**, named below for each step.
- **What "done" looks like**, so the customer can tell the step worked.

If the customer asks you to run the handoff steps yourself, they stay the customer's steps: deploying,
ingesting, cutting over and decommissioning are things this migration does not do ("What this migration
can not do" in the guide). Walk them through the same six items, as steps they run.

**The ending decides blocks 1 and 2.** KB path after a build: the steps start at ingest. IaC path: nothing
was provisioned, and the steps start at deploy. Plan only (the customer stopped at the plan): nothing was
created, and the steps start with the plan's own build steps, which the customer runs. Each uses the doc
link the plan file gives that step, and their "Done" is the same as Deploy's: every KB `ACTIVE` and every
data source `AVAILABLE`.

## 1. What changed

Present what changed. KB path: every created resource with type, id, name, Region and status. IaC path:
every file written and every mapping or exclusion. Plan only: every file written to `output_dir`, and that
nothing was created in the account.

## 2. The customer-run next steps

Give each step that applies, in this order, as a customer-run step, clearly deferred.

- **Deploy (IaC path).** Review the migrated file, then deploy it as a new stack (CloudFormation) or apply
  it from a new root module (Terraform): applying it to the source stack or workspace deletes the original
  KBs, which are the rollback. Pages: for CloudFormation,
  [Create a stack](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/cfn-console-create-stack.html);
  for Terraform, the Terraform Registry pages for
  [`aws_bedrockagent_knowledge_base`](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_knowledge_base)
  and [`aws_bedrockagent_data_source`](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_data_source)
  ([iac-schema](references/bedrock-kb-migration/iac-schema.md) §3).
  Done: the deploy finished, every KB is `ACTIVE` and every data source `AVAILABLE`.
- **Ingest.** The command starts an ingestion job on one new data source, never the original, with a
  client token of at least 33 characters, and then reads the job's status (a `CUSTOM` data source gets no
  ingestion job: it is filled by direct ingestion,
  [managed-kb-api](references/bedrock-kb-migration/managed-kb-api.md) §2d). Run one job per data source at
  a time, and keep the concurrent jobs under the per-KB and per-account ingestion quotas (read them live,
  [mapping](references/bedrock-kb-migration/mapping.md) §4); a `ConflictException` means a job is already
  running on that data source. Say what to expect from the job
  ([managed-kb-api](references/bedrock-kb-migration/managed-kb-api.md) §5). Page:
  [Sync your data](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-data-source-sync-ingest.html).
  Done: every job's status is `COMPLETE`.
- **Validate.** For each of the customer's own questions, the commands send the same question text to
  `Retrieve` on the original KB and on the new one, each with its own search configuration:
  `vectorSearchConfiguration` on the original, `managedSearchConfiguration` on the new one (the Cut over
  step below, and [managed-kb-api](references/bedrock-kb-migration/managed-kb-api.md) §3). The original's
  request body, reused with its `vectorSearchConfiguration`, is rejected by the new KB. Validate retrieval
  on the new KB against the original using `Retrieve` against `Retrieve`, in two passes. First like for
  like: reranking off on the new KB (`rerankingModelType` `NONE` in `managedSearchConfiguration`) when the
  original has no reranker, or the same custom reranker on both when it has one. Then the new KB with its
  default reranking, which is what the callers get after cutover. On an ACL-enabled KB, query as a known
  in-ACL user. Run each metadata filter the callers send as well: a filter the original accepts can be
  rejected by the new KB ([managed-kb-api](references/bedrock-kb-migration/managed-kb-api.md) §3).
  Scores are not comparable across KB types:
  compare ranking and content, and re-tune thresholds. Pages:
  [Query a knowledge base and retrieve data](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-retrieve.html)
  and the [Retrieve API reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html).
  Done: the customer has compared both result lists for each question and is satisfied with the new KB.
- **Cut over.** A code change, with no AWS command. The customer changes the application to call the new
  KB, diffing the caller code against the caller list. Application code changes:
  `managedSearchConfiguration` replaces the `vectorSearchConfiguration` wrapper, `overrideSearchType` does
  not exist on it, and the result URI, metadata keys and score scale change. The full list is in
  [managed-kb-api](references/bedrock-kb-migration/managed-kb-api.md) §3; write the items that apply in the
  reply. Page: "Managed knowledge base considerations" on
  [Query a knowledge base and retrieve data](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-test-retrieve.html).
  Done: every caller on the list calls the new KB, with its changes made.
- **Decommission.** Decommission the original by the plan's resource-level checklist, never by deleting
  the source stack or workspace (it can hold the bucket the new data source reads).
  If the original has a Confluence, SharePoint, Salesforce or Web Crawler data source, deleting it cannot be
  undone: new connectors of these types cannot be created on self-managed (customer-managed) KBs; existing
  ones keep working ([Confluence connector page](https://docs.aws.amazon.com/bedrock/latest/userguide/confluence-data-source-connector.html),
  same notice on the SharePoint, Salesforce and Web Crawler pages). Keep the original until it is no longer
  needed for rollback. Page:
  [Delete an Amazon Bedrock knowledge base](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-delete.html).
  Done: every item on the checklist is removed, and every resource the new KB reads is still there.

Present `AgenticRetrieveStream` as a new optional capability to evaluate on the new KB before or after
cutover, never as a migration step.

## 3. Monitoring

Tell the customer **how to monitor the managed KB after migrating**: Amazon Bedrock publishes runtime metrics
to CloudWatch under the `AWS/Bedrock/KnowledgeBases` namespace (documented metrics: `Invocations`,
`ClientErrors`, `ServerErrors`, `Throttles` for `Retrieve`, plus `RawDataSize`), and you can enable ingestion
log delivery (to CloudWatch Logs, Amazon S3, or Amazon Data Firehose) to track ingestion-job and
per-document status — see
[Observability for managed knowledge bases](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-observability.html).
Name only the metrics the docs name; do not invent metric names.

- **Prerequisite: `cloudwatch:PutMetricData`.** Per that page, metrics are published only if the identity
  is allowed to call `cloudwatch:PutMetricData` for the `AWS/Bedrock/KnowledgeBases` namespace: for
  `Retrieve` that is the KB's service role, and for other operations the identity that calls them. Without
  it the metrics are not published, though the requests still work. Give it as an IAM step the customer
  runs: attach the policy from that page to the KB's service role and to any identity that calls the KB.
- **Ingestion logs.** They can name documents and carry their status, so recommend encryption at rest on
  the destination: a KMS key on the CloudWatch Logs log group, SSE-KMS on the S3 bucket, or server-side
  encryption on the Firehose stream.
- **Alarm.** Recommend a CloudWatch alarm on the new KB's `ServerErrors` and `Throttles`; the customer
  creates it. Page:
  [Create a CloudWatch alarm based on a static threshold](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/ConsoleAlarms.html).

Done: `Invocations` appears under the namespace after the first `Retrieve` made once the
`cloudwatch:PutMetricData` permission is attached; if the customer enabled ingestion log delivery, it shows
as active; and the alarm is listed in CloudWatch.

## 4. Audit trail

Recommend; never create one. Tell the customer two things.

**Where this migration's own calls are.** Every AWS call this migration made (`CreateKnowledgeBase`,
`CreateDataSource`, IAM calls) is a CloudTrail management event, visible in CloudTrail Event history with no
setup ([Event history](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/view-cloudtrail-events.html)
gives its retention and cost). Find them by event source `bedrock.amazonaws.com` or by the user name of the
role used; look in the KB's Region for Bedrock calls and in `us-east-1` for IAM calls. Through the AWS MCP
Server, each tool call is also an `aws-mcp.amazonaws.com` event; its arguments are hidden, so the detail is
in the matching AWS API event. Viewing needs `cloudtrail:LookupEvents`.

**Recommend a data-event trail for retrieval.** Retrieval on the new KB (`Retrieve`, `RetrieveAndGenerate`)
is a data event and is not logged by default: auditing it needs a trail with an advanced event selector for
`AWS::Bedrock::KnowledgeBase`, which carries an extra charge
([data events](https://docs.aws.amazon.com/awscloudtrail/latest/userguide/logging-data-events-with-cloudtrail.html),
[Bedrock CloudTrail](https://docs.aws.amazon.com/bedrock/latest/userguide/logging-using-cloudtrail.html)).
Give it as a customer-run step; turning it on is the customer's decision. Never create or change the trail
yourself. Done: the trail's event selectors log data events for `AWS::Bedrock::KnowledgeBase`.

## 5. Security follow-ups

Give the follow-ups that apply, each as a customer-run step. The trust-policy and `output_dir` items come
from the guide's "Security considerations".

- **Tighten the new KB role's trust policy** to that KB's ARN (`aws:SourceArn`) once the KB exists
  ([safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md) → the `aws:SourceArn` note). Page:
  [Cross-service confused deputy prevention](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-service-confused-deputy-prevention.html).
  Done: the role's trust policy names the new KB's ARN.
- **Remove the build role and the build profile** once the migration is done, if the customer set them up
  for the build. The command deletes the role's inline policies, detaches any managed ones, then deletes the
  role; the customer also removes the profile from their AWS config file. Page:
  [Delete roles or instance profiles](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_manage_delete.html).
  Done: the role no longer exists, and the profile is gone from the config file.
- **Keep `output_dir` out of version control:** add it to the repository's ignore file rather than
  committing it. Done: the ignore file lists `output_dir`, and none of its files is committed.

## 6. Rollback

**Rollback is keeping the untouched original.** The original KB was never changed, so until the customer
decommissions it, the fallback is to keep using it, or point the application back at it.
