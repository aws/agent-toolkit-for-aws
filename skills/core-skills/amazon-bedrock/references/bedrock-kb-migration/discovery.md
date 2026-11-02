# Discover the Migration Source (Read-Only)

The Discover phase inventories the **source** of a knowledge-base migration using only read-only
access, and produces the normalized source model plus the artifacts the Plan phase consumes. It
never mutates: the KB path only reads the account; the IaC path only reads files or templates and
writes a reference copy to the working directory.

## Contents

- [Purpose](#purpose)
- [Preconditions (from Identify)](#preconditions-from-identify)
- [KB path — a live self-managed Knowledge Base](#kb-path--a-live-self-managed-knowledge-base)
- [IaC path — existing Infrastructure-as-Code](#iac-path--existing-infrastructure-as-code)
- [Cost analysis hook](#cost-analysis-hook)
- [Output shapes](#output-shapes)
- [Phase outcome](#phase-outcome)
- [Common mistakes](#common-mistakes)

## Purpose

Discovery is strictly **read-only** and **provisions nothing**. It branches on the migration
**target type**, which is one of `kb` or `iac`:

| Target type | Discovers | Follow |
|---|---|---|
| `kb` | a live self-managed KB (`VECTOR`; the host skill calls this a Customer-managed KB), read with read-only AWS CLI calls | [KB path](#kb-path--a-live-self-managed-knowledge-base) |
| `iac` | existing Terraform / CloudFormation that declares a self-managed KB | [IaC path](#iac-path--existing-infrastructure-as-code) |

**The path is never inferred.** It is set in Phase 0 and read from the session state
here; if it is unset, the phase ends `NEEDS_INPUT` and asks the user — never guess it. Switching the
target type restarts the flow from Identify for the new type. Read this file's branch for the active
path before reading any source: it defines what counts as source, the field surface to capture, and
the completeness rules, none of which should be reconstructed from memory.

## Preconditions (from Identify)

Before Discover runs, Identify must have established:

- `migration_target_type` is `kb` or `iac` (a chosen value, not inferred).
- A fresh, empty `output_dir` (default `./kb-migration/<timestamp>/` under the working directory) for artifacts.
- The cost gate answer, `cost_analysis: enabled | declined` — never inferred here. If it is unset,
  end `NEEDS_INPUT`.
- A least-privilege **read-only** credential posture — all either path needs. See
  [safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md) for sample read-only policy A,
  the source-immutability rule, and the injection-untrusted-content rule.

Read public AWS docs with `curl` on the `.md` twin of the page, never `web_fetch`, per
[safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md).

## KB path — a live self-managed Knowledge Base

Always pass `--region <REGION>` and `--profile <READ_ONLY_PROFILE>`.

### Exact call set (read-only, pre-approved probes)

Every command here is a **pre-approved read-only probe** — `get-*` / `list-*` / `describe-*` /
`sts get-caller-identity`. Display each labeled READ-ONLY and run it without waiting. The set is
exact: preview issues **zero mutating calls**, and no command outside this set is run "to check".

| Task | Read-only command |
|------|-------------------|
| Identity | `aws sts get-caller-identity --profile <READ_ONLY_PROFILE>` |
| List KBs | `aws bedrock-agent list-knowledge-bases --region <REGION> --profile <READ_ONLY_PROFILE>` |
| Get KB | `aws bedrock-agent get-knowledge-base --knowledge-base-id <KB_ID> --region <REGION> --profile <READ_ONLY_PROFILE>` |
| List DSes | `aws bedrock-agent list-data-sources --knowledge-base-id <KB_ID> --region <REGION> --profile <READ_ONLY_PROFILE>` |
| Get DS | `aws bedrock-agent get-data-source --knowledge-base-id <KB_ID> --data-source-id <DS_ID> --region <REGION> --profile <READ_ONLY_PROFILE>` |
| List jobs | `aws bedrock-agent list-ingestion-jobs --knowledge-base-id <KB_ID> --data-source-id <DS_ID> --region <REGION> --profile <READ_ONLY_PROFILE>` |
| Cost analysis (OCUs, storage, rates) — **only when `cost_analysis: enabled`** | see [cost-analysis](references/bedrock-kb-migration/cost-analysis.md) |
| CFN schema (verify) | `aws cloudformation describe-type …` — commands and shapes in [iac-schema](references/bedrock-kb-migration/iac-schema.md) |

**Never** run a mutating command — no `bedrock-agent create-*` / `update-*` / `delete-*` /
`start-ingestion-job`, no content-returning read (`retrieve` and the others in
[safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md) → "Content-returning reads") without the
customer's explicit yes — and never edit the source KB. The `get-data-source`
/ `get-knowledge-base` / `list-*` probes read **configuration metadata only** (connector type, chunking,
parsing, filters, ARNs) — they **never return corpus content**; only `retrieve` exposes document content,
which is why it is excluded here.

### Steps

1. **Confirm identity and region.** `aws sts get-caller-identity`; confirm the account is the
   expected one and the profile is read-only.
2. **List knowledge bases.** Capture each `knowledgeBaseId` and `name`. If several exist, ask which
   to migrate — one, several, or all.
3. **Get each KB's details.** Extract public fields only: `knowledgeBaseConfiguration.type`, the
   embedding model under `vectorKnowledgeBaseConfiguration.embeddingModelArn`,
   `storageConfiguration.type` (the vector store), `roleArn`, `status`, and any embedding
   dimension / data-type fields.
4. **List and inspect every data source.** Note connector `type`, chunking under
   `vectorIngestionConfiguration.chunkingConfiguration`, and parsing under `...parsingConfiguration`.
   For **auth connectors** (Confluence, SharePoint, OneDrive, Google Drive) also capture the source
   config to mirror later — `credentialsSecretArn` and the addressing fields (`hostUrl`/`hostType`/
   `authType` for Confluence; `tenantId`/`domain`/`siteUrls`/`authType` for SharePoint). Record the
   secret **ARN only**, never the value. Omit auth capture for S3, Web and Custom — they carry no
   credential. Do not classify what kind of content the corpus holds; corpus content type is out of
   scope (corpus *size* is measured in the cost analysis).
5. **Review ingestion history** (required) with `list-ingestion-jobs` for every data source — a KB can be
   `ACTIVE` with every ingestion job failed. Flag a `FAILED` or partial last job (documents failed or
   skipped) in the summary before any retrieval comparison is suggested. Do not start a job. If the
   history cannot be read (the call is denied, or the user runs the commands by hand and does not return
   this one), record `ingestion_history: unavailable: <reason>` in the summary and continue; a missing
   history is a gap to report, never a `BLOCKED` outcome.
6. **Cost analysis** — only when `cost_analysis: enabled`. See the [cost analysis hook](#cost-analysis-hook).
7. **Summarize per KB** — produce the per-KB discovery summary (the [output shape](#output-shapes)
   below).
8. **Emit both CloudFormation templates per selected KB** to `output_dir`:
   - `source-config.yaml` — the discovered `VECTOR` KB as-is (its `StorageConfiguration`, connector
     block, chunking config).
   - `managed-target.yaml` — the equivalent `MANAGED` KB with the validated substitutions from
     [mapping](references/bedrock-kb-migration/mapping.md) (each noted as a YAML comment), **omitting
     `StorageConfiguration`** (auto-provisioned), using the managed connector shape.

   Verify the live schema first — the accepted `Type` values, property names, the
   PascalCase-vs-camelCase note, and the source/managed shapes live in
   [iac-schema](references/bedrock-kb-migration/iac-schema.md). Reference ARNs only (role, KMS,
   `credentialsSecretArn`); never inline a secret; label placeholders for anything not discovered.
   Write each template to `output_dir` (each write approved) and confirm it is on disk. On a bulk
   run, suffix each file with the KB id (`source-config-<kb-id>.yaml` / `managed-target-<kb-id>.yaml`)
   so nothing overwrites.

### Configuration coverage (capture ALL — do not sample-and-skip)

Discovery is **exhaustive**: enumerate **every** KB the user wants migrated and **every** data source
on each — connectors, chunking and parsing often differ per data source. Capture each item present;
explicitly mark any absent or unreadable field as **unknown, never "not present"**. If a `list-*`
call paginates, follow `nextToken` to the end. Capture:

- [ ] KB type (`VECTOR`) and identity (name, description, `roleArn`, `status`).
- [ ] Embedding model ARN, whether FM or inference profile, and `dimensions` / `embeddingDataType`
      if set (FLOAT32/BINARY).
- [ ] Multimodal embedding config (audio/video) if present.
- [ ] Vector store type **and** its per-store config block.
- [ ] Encryption keys (a security read, done whatever the cost gate says): on a `VECTOR` KB the at-rest key
      is on the store (AOSS `batch-get-collection` → `kmsKeyArn`; the S3 Vectors bucket; the RDS cluster)
      and on each data source (`get-data-source` → `serverSideEncryptionConfiguration`). KB-level
      `serverSideEncryptionConfiguration` exists only on `MANAGED` KBs; do not look for it on the source.
- [ ] **Every** data source: connector `type`, per-DS chunking **and** parsing config.
- [ ] Connector auth per auth connector — secret ARN, `siteUrls`/`hostUrl`, `authType`,
      `tenantId`/`domain`; ARN only. Omit for S3, Web, Custom.
- [ ] S3 `inclusionPrefixes` / `exclusionPatterns` (carried over via managed
      `connectorParameters.filterConfiguration`).
- [ ] Custom transformation (Lambda) and context enrichment / GraphRAG (Neptune Analytics) —
      each lacks a managed equivalent; flag it, direct to AWS Support.
      (Salesforce, Zendesk and Confluence Data Center are now native managed connectors — not
      flags; map them like any other connector.) Before flagging any connector as having no managed
      equivalent, follow [plan](references/bedrock-kb-migration/plan.md) → "Before recording a connector
      as blocked".
- [ ] Data-deletion policy (DELETE/RETAIN).
- [ ] Data-source-level SSE if present; recent ingestion status / document counts per data source.
- [ ] Sync timer, for the sync schedule ([plan](references/bedrock-kb-migration/plan.md) → "Sync
      schedule"). IaC path: a rule or schedule in the source that starts ingestion
      (`AWS::Events::Rule`, `AWS::Scheduler::Schedule`, `aws_cloudwatch_event_rule`,
      `aws_scheduler_schedule`, or a scheduled Lambda calling `StartIngestionJob`); record its
      frequency. KB path: the call set above reads no timers, so add no probe for one. Use what the
      customer says; if they say nothing, record "no timer found" (on demand).

### Bulk = one session

Selecting more than one KB is a first-class **bulk migration**, not N separate sessions: iterate the
per-KB steps once per selected KB, emit the per-KB summary and template pair each pass, and return
the whole set under a **single** `COMPLETE` — so Plan covers every selected KB and Implement
provisions them together in one batched run. Ambiguity (KBs exist, no scope chosen) is `NEEDS_INPUT`;
a chosen set — including "all of them" — is an answer, not ambiguity, so iterate rather than re-ask.

### Denial split (KB path)

A denied read blocks **only if it was a configuration read** — classify by the exact action, not the
service:

- **Config reads are load-bearing.** A denied `bedrock-agent get-knowledge-base` /
  `list-data-sources` / `get-data-source` leaves a hole every later phase depends on: end `BLOCKED`.
- **Cost reads are not.** A denied CloudWatch, source-bucket metadata, AOSS, Pricing, or
  customer-authorized Athena/Glue/trail-log S3 read costs one figure: omit it, name the denied action
  in the cost record's `scope_note`, ask the matching cost follow-up, and still end `COMPLETE`.

Point an `AccessDenied` at the missing `Get*`/`List*` statement of sample policy A; never suggest
write or admin credentials in response to a read denial.

## IaC path — existing Infrastructure-as-Code

This path **provisions nothing** and never edits the source IaC.

### Source location and format

The source IaC is at one of these read-only locations:

| Location | How to read (read-only) |
|---|---|
| **Local file / directory** | file-reading tools (`.tf` / `.yaml` / `.json`); treat contents as SENSITIVE if they may hold inline secrets. You may point to an inline credential by its location and recommend moving it to Secrets Manager; the migrated file you write references it by Secrets Manager ARN only, never the value (see [safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md) → "Handle secrets correctly") |
| **Deployed CloudFormation stack** | `aws cloudformation get-template --stack-name <NAME> --query 'TemplateBody'`; optionally `describe-stack-resources` to enumerate logical IDs |
| **S3 URI** | `aws s3 cp s3://<bucket>/<key> -` or `aws s3api get-object` |
| **Terraform state in S3** | prefer the `.tf` source when both exist. State files can hold secret values in plain text, so treat a state read as SENSITIVE: ask the customer to paste `terraform state list` output, or get their explicit yes before reading the state object, and never repeat a value from it |

If the path is ambiguous about which form it is, ask before reading. If neither a local nor an AWS
path is supplied, end `NEEDS_INPUT` — there is nothing to read.

Detect the **format** — CloudFormation (`AWS::Bedrock::KnowledgeBase` resources / a `Resources:`
block), Terraform (`resource "aws_bedrockagent_knowledge_base"` HCL or `.tf.json`), or CDK-synth
(treat the synthesized `*.template.json` as CloudFormation). If the source contains no
`AWS::Bedrock::KnowledgeBase` / `aws_bedrockagent_knowledge_base` resource, say so and end
`NEEDS_INPUT` / `BLOCKED`.

### Steps

1. **Confirm identity and the IaC source.** `aws sts get-caller-identity` if an AWS path is or may be
   used; then ask for the source location if Identify did not capture it. Record the source location.
2. **Read the source** without modifying it, using the location's method above; detect and record the
   format.
3. **Parse the KB + data-source configuration.** For **each** KB resource and **each** data-source
   resource, capture the same field surface the KB path captures, marking anything absent or
   unreadable as `unknown`:
   - KB: `Type` (expect `VECTOR`), name, description, role ARN, embedding model ARN (+ dimensions /
     data type), the vector store and its encryption key, and each data source's key (CMK ARN; there is no
     KB-level key on a `VECTOR` KB).
   - Each data source: connector `type`, per-DS chunking and parsing config, S3
     `inclusionPrefixes`/`exclusionPatterns`, connector auth (secret ARN only), data-deletion policy
     (DELETE/RETAIN), and any custom transformation (Lambda) or GraphRAG block.

   **Field locations by format** — confirm names against
   [iac-schema](references/bedrock-kb-migration/iac-schema.md) and the live schema. CloudFormation is
   PascalCase (`Properties.KnowledgeBaseConfiguration.{Type, VectorKnowledgeBaseConfiguration.EmbeddingModelArn}`,
   `Properties.StorageConfiguration`, each `AWS::Bedrock::DataSource`'s `DataSourceConfiguration` +
   `VectorIngestionConfiguration`). Terraform argument names are **snake_case** — never assume them
   from the CFN PascalCase or the CLI camelCase.
4. **Note the source vector store and deletion policy.** Record them; the managed target drops the
   store and maps the deletion policy — but that translation happens in Plan/Implement.
5. **Produce the source-IaC reference copy.** Write a reference copy to `output_dir` as
   `source-iac.<ext>`: the source unchanged except that it starts with a comment line
   "SOURCE — DO NOT DEPLOY" (for a format with no comments, such as JSON, put the marker in the file name:
   `source-iac.DO-NOT-DEPLOY.json`), and any inline secret is redacted to an ARN/placeholder. It is a copy
   of what you read, never a modification of the user's file.
5a. **Cost signal** — only when `cost_analysis: enabled`. See the [cost analysis hook](#cost-analysis-hook).
5b. **Classify the non-KB resources** in the source (buckets, collections or indexes, vector buckets,
   roles, policies, keys): for each, whether it stays (still used, including a bucket the new data source
   will read), becomes obsolete after cutover, or is untouched. The plan's decommission checklist is built
   from this list.
6. **Summarize per KB** — produce the per-KB IaC discovery summary (the [output shape](#output-shapes) below).

**Whether the IaC is deployed comes from the user or the source, not from a search.**

- **The user says it was never deployed, or the source shows it:** scope that KB out. Say why, and
  write no target file for it.
- **Unknown, and no matching KB in the account you can reach:** that proves nothing. The file may
  deploy into another account or Region than your credentials reach. Say "no matching KB found in
  account `<id>`, `<region>`", ask where it runs, and keep migrating the file. Never report it as
  undeployed on that basis.

### Exhaustive enumeration and loops

Enumerate **every** KB resource and **every** data-source resource; do not stop at the first. Two
things are most often undercounted:

- **Resources generated by a loop.** A CloudFormation `Fn::ForEach` / `AWS::LanguageExtensions` block
  or a Terraform `for_each` / `count` expands to many data sources though it appears once in the file
  — count the collection, not the literal blocks. The real count is what the data-sources-per-KB quota applies to.
- **Values from a variable / parameter** whose concrete value is not in the file are `unknown` — a
  discovery result to report, not a value to invent (e.g. an embedding ARN supplied by a `.tfvars`
  variable or a stack parameter).

Flag every no-managed-path feature found (`custom_transformation` Lambda, GraphRAG / context
enrichment, any connector with no managed equivalent) in
`no_managed_path_flags` — these drive exclusions in planning. (Salesforce, Zendesk and Confluence
Data Center are native managed connectors and are not flagged.)

### Denial split (IaC path)

Classify by the exact action, not the service:

- **Source reads block.** A denied `cloudformation:GetTemplate` or `s3:GetObject` means there is no
  source to parse: end `BLOCKED`.
- **Cost reads degrade.** A denied `cloudwatch:*`, `s3:ListBucket`, `aoss:*`,
  `pricing:GetProducts` or `ce:GetCostAndUsage` costs one figure: record the denied action, omit
  that figure, and still end `COMPLETE`.

Both sides involve S3, so note that `s3:GetObject` is a source read and blocks, while `s3:ListBucket`
is a cost probe and does not — reading "an S3 denial" as one category is how a corpus-sizing failure
gets mistaken for an unreadable template.

## Cost analysis hook

The cost analysis runs **only if the Identify cost gate was enabled** (`cost_analysis: enabled`);
when the gate was `declined`, run no cost probe on either path. The full procedure — the input
checklist, the measurement commands (including vector count and embedding dimension), the plausibility
check of any stated OCU count against AWS's published guidance, the scripted comparison, the fixed output
table and the branch table for missing telemetry — lives in
[cost-analysis](references/bedrock-kb-migration/cost-analysis.md) as Steps 0-9; run them in order
before producing any cost figure and never reason from a remembered price. On the KB path it runs against the live collection
(KB Step 6); on the IaC path it is narrower (IaC Step 5a) — a template declares intent, not usage, so
if the stack is not deployed, do not estimate.

The two denial classes are not symmetric: a **source-read** denial BLOCKS (the source model is
load-bearing), while a **cost-read** denial degrades and the phase stays **COMPLETE** — the cost
figure is omitted, the denied IAM action is named, and nothing downstream depends on it. Neither an
unmeasurable figure, a denied permission, nor a declined gate ever blocks `COMPLETE`.

## Output shapes

These are the outputs the Discover phase produces — the fields the Plan phase consumes, as plain
data per KB. Each unreadable field is the string `unknown`.

**KB path — one discovery summary per KB:**

```yaml
source_kb_id: <id>                      # a live KB has an AWS id
kb_name: <name>
kb_type: VECTOR
kb_status: <status>
role_arn: <arn>
embedding_model_arn: <arn>
embedding_dimensions: <n or model default>   # read the model's default from its Bedrock model page
embedding_data_type: <FLOAT32 | BINARY>
vector_store: <type>
encryption: <aws-owned | cmk-arn>
data_sources:                           # enumerate EVERY data source
  - id: <ds-id>
    name: <name>
    type: <S3 | CONFLUENCE | SHAREPOINT | WEB | CUSTOM | …>
    chunking: <strategy>
    chunking_params: { … }
    parsing: <strategy or DEFAULT>
    inclusion_prefixes: [ … ]           # S3 only; absent otherwise
    connector_auth:                     # auth connectors only; omit for S3/Web/Custom; ARN only
      secret_arn: <arn>
      authType: <type>
      hostUrl | siteUrls | tenantId | domain: <…>
    custom_transformation: <true | false>
    last_ingestion: { status: <…>, documents: <n> }
no_managed_path_flags: [ … ]            # custom_transformation | graphrag; [] when none
migratable: <true | false>
notes: <string, "" when empty>
cfn_source_template: <path to source-config.yaml | source-config-<kb-id>.yaml | inline-only>
cfn_managed_template: <path to managed-target.yaml | managed-target-<kb-id>.yaml | inline-only>
```

**IaC path — one discovery summary per KB** (identified by `logical_id`, never `source_kb_id`, since
a declared template resource has no AWS id):

```yaml
logical_id: <template logical id>
kb_name: <name, may hold a template expression such as ${NameSuffix}>
kb_type: VECTOR
vector_store: <type or unknown>
encryption: <aws-owned | cmk-arn>
embedding_model_arn: <arn or unknown>
embedding_dimensions: <n or unknown>
embedding_data_type: <FLOAT32 | BINARY | unknown>
iac_format: <cloudformation | terraform | cdk-synth>
iac_source_location: <local path | stack:<name> | s3://…>
data_sources:                           # enumerate EVERY data source, expanding loops
  - logical_id: <id>
    type: <connector type>
    chunking: <strategy>
    parsing: <strategy or DEFAULT>
    deletion_policy: <DELETE | RETAIN>
    connector_auth: { secret_arn: <arn> }   # auth connectors only
no_managed_path_flags: [ … ]            # migratable is false exactly when this is non-empty
migratable: <true | false>
declared_cost_shape: { standby_replicas, kms_key_shared_with, embedding_model }  # declared, not measured
source_iac_copy: <path to source-iac.<ext> | inline-only>
notes: <string, "" when empty>
```

The cost figures (when the gate was enabled) are recorded per KB by
[cost-analysis](references/bedrock-kb-migration/cost-analysis.md) and keyed by the same `source_kb_id`
(KB path) or `logical_id` (IaC path); the two must agree.

## Scale and quota

Read these limits live from Service Quotas before stating them, never from memory
([mapping](references/bedrock-kb-migration/mapping.md) §4 has the command and codes):

- Self-managed: data sources per KB (`L-679D8304`) and KBs per account per Region (`L-60DA3E0D`).
- Managed: data sources per KB (`L-F02D918A`) and KBs per account per Region (`L-5C7643AC`).

Preserve topology by default; consolidation is an optional improvement, not something Discover
decides. The exhaustive per-DS count from enumeration (loops expanded) is what a later phase checks
against the managed data-sources-per-KB limit (`L-F02D918A`, read live).

## Phase outcome

The phase ends in one of `COMPLETE | NEEDS_INPUT | BLOCKED | FAILED`:

- **COMPLETE** — the path's required artifacts exist and are non-empty on disk (KB path: both
  templates per selected KB; IaC path: `source-iac.<ext>`), every coverage item is
  captured or marked `unknown`, and the user confirmed. A declined cost gate, an unmeasurable cost
  figure, and a denied *cost* read all still allow COMPLETE.
- **NEEDS_INPUT** — relayed to the user: the target type or cost gate is unset, the source was not
  supplied, or multiple KBs exist and no scope was chosen. A chosen set is not `NEEDS_INPUT`.
- **BLOCKED** — a configuration/source read was denied, or the source has no KB. Stops here.
- **FAILED** — an unexpected failure. (Teardown of owned resources applies only to the Implement
  phase, which is the only phase that creates resources.)

Named outputs the Plan phase needs: the per-KB discovery summary above, and (KB path) `source_kb_id`,
`vector_store`, `embedding_model`, the data-source list, `cfn_source_template` /
`cfn_managed_template`; (IaC path) `logical_id`, `iac_format`, `iac_source_location`,
`no_managed_path_flags`. Plan branches on the same target type.

## Common mistakes

- **Guessing the path or the cost gate** instead of reading the value — `unset` is `NEEDS_INPUT`, not
  an implied yes. Running cost analysis on a declined session spends budget the user turned down;
  skipping it on an enabled one drops the most-requested part of discovery.
- **Running any mutating command** (`start-ingestion-job`, `terraform apply`, `cloudformation deploy`,
  `create-*`) or a content-exposing `retrieve` "to check" — discovery is strictly read-only.
- **Sampling only the first KB / data source** — discovery is exhaustive; enumerate every one. On the
  IaC path, **counting a loop as one resource** is the same error: a `Fn::ForEach` or `for_each` /
  `count` block declares as many data sources as its collection has entries.
- **Filling in a value the source does not contain** — an embedding ARN supplied by a `.tfvars`
  variable or a stack parameter is `unknown`; never substitute a plausible ARN.
- **Reporting COMPLETE with a missing required artifact** — it blocks the whole pipeline; finish it
  or end `NEEDS_INPUT` / `BLOCKED`.
- **Editing or `terraform import`-ing the source, or copying an inline secret into `source-iac.<ext>`**
  — the source is read-only; redact secrets to an ARN/placeholder.
- **Pasting camelCase into CloudFormation, adding `StorageConfiguration`, or hand-writing shapes from
  memory** — follow [iac-schema](references/bedrock-kb-migration/iac-schema.md): CFN is PascalCase,
  the managed store is auto-provisioned, and enums come from the live schema.
- **Dumping full JSON with secrets** — summarize; ARNs only. **Forgetting `--region`** — KBs are
  regional; a missing region yields empty results.
