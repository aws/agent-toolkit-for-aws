# Plan the migration (advisory)

The Plan phase turns the discovered source into a clear, **numbered migration plan**. It is
**advisory and read-only**: it never runs a mutating command and provisions nothing. Read-only
schema checks are allowed to ground the plan. The phase branches on the target type set at
Identify — a **KB path** (a live knowledge base) or an **IaC path** (existing infrastructure-as-code).
The default is to **stop once the plan exists**; the Implement phase is opt-in and begins only if
the user explicitly asks the agent to build.

## Contents

- [Preconditions](#preconditions)
- [KB path](#kb-path)
- [IaC path](#iac-path)
- [Persist the plan](#persist-the-plan)
- [Phase outcome](#phase-outcome)
- [Common mistakes](#common-mistakes)

## Preconditions

- **The target type is never inferred here.** It was set at Phase 0. If it is unset, the phase
  ends `NEEDS_INPUT` and asks the user which path applies; it does not guess. Switching the target
  type restarts at Phase 1 (Identify) for the new type.
- The discovered source configuration is on record (vector store, embedding model, chunking, data
  sources, connectors, and any no-managed-path flags).
- An `output_dir` is on record for persisting the plan (see [Persist the plan](#persist-the-plan)).
- Public documentation only. Fill and verify every doc link by reading its `.md` twin with `curl`,
  never `web_fetch` — read the doc per
  [safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md).
- Terminology: **self-managed KB (`VECTOR`; the host skill calls this a Customer-managed KB)** is
  the source; **Managed KB (`MANAGED`)** is the target. **source** / **original** is the user's KB
  and is never mutated.

## KB path

Plans a create-new-then-cut-over migration of a live self-managed KB, where the mutating steps are
written for the **user** to run.

### Core principle — create-new-then-cut-over

A knowledge base's vector store generally **cannot be changed in place**. The safe, publicly
documented pattern is:

1. Stand up the new target (vector store / embedding model / chunking) alongside the original.
2. Create a new Managed KB pointed at the new target.
3. Attach equivalent data sources.
4. Sync/ingest so embeddings are rebuilt in the new store (re-embedding is expected).
5. Validate retrieval quality against the original KB.
6. Cut the application over to the new KB.
7. Decommission the original KB only after validation.

### Compatibility check

Apply the validated substitutions from
[mapping](references/bedrock-kb-migration/mapping.md) — read them **from the file, never from
memory** — and the managed rules a valid target must satisfy from
[managed-kb-api](references/bedrock-kb-migration/managed-kb-api.md). Call out the publicly
documented constraints, for example: embedding output **dimensions** must match the target index;
changing the **embedding model** forces a full re-embed; the target store has prerequisites
(index/table/collection, field mappings, permissions).

When a setting's acceptance is uncertain, name the concrete resolution path — **"validate via
skeleton"** (`--generate-cli-skeleton`) or **"validate via creation"** (a DRY_RUN preview then the
approved create) — rather than a vague "needs verification."

**Before recording a connector as blocked** for "no managed connector", read the Topics list at the bottom
of [kb-managed-connect-ds](https://docs.aws.amazon.com/bedrock/latest/userguide/kb-managed-connect-ds.html)
and the connector's own `kb-managed-ds-*` page. Do not use that page's "Supported type values" sentence: it
lags the Topics list. If a page documents the connector, it is not blocked. If the fetch fails, do not
record it as blocked: mark its shape unverified, give the link, and hand the shape check to the user. This
is a documentation read; never call `create-data-source` to test whether a type exists.

The blocker list is **closed** — exactly a `customTransformationConfiguration` Lambda hook,
context enrichment / GraphRAG, or a connector confirmed absent. Everything
else, including every `adjusted` row, is `READY` and migrates. (Salesforce, Zendesk and Confluence
Data Center are native managed connectors now, so they are not blockers.) **Exclude, never
approximate** a true blocker; and never exclude a KB that an `adjusted` row covers. A plan reporting
`0 READY` for a setting that has an `adjusted` row is wrong and costs the user a support case for nothing.

### The numbered plan (user-executed)

Present mutating commands as steps for the user, each labeled "(user runs)" and paired with a
public doc link. Confirm a **naming convention** first (default `<original-name>-managed` for the
KB, `<original-ds-name>-managed` per data source); record it so every step names resources
consistently.

```
MIGRATION PLAN — <source> -> <target>

Prerequisites (user runs):
  1. Provision the target vector store and its index/table per the public prerequisites doc.
  2. Confirm an IAM role for the KB with the documented permissions for the new store.

Build the new knowledge base (user runs):
  3. aws bedrock-agent create-knowledge-base ...    (user runs; do not run here)
  4. aws bedrock-agent create-data-source ...       (user runs; do not run here)

Populate and validate (user runs):
  5. aws bedrock-agent start-ingestion-job ...      (user runs; do not run here)
  6. Validate retrieval on the new KB and compare results to the original KB.

Cut over and clean up (user runs):
  7. Point the application/retrieve calls at the new knowledge base id.
  8. aws bedrock-agent delete-knowledge-base ...    (user runs; only after validation)
```

**On a bulk migration, one plan covers every discovered KB.** State the shared decisions (target,
naming, cut-over pattern) once, add per-KB rows only where configurations differ, and hand the
whole set to a single Implement run — never a separate plan-and-build cycle per KB.

### Verification and rollback

- **Verification:** run the same representative queries against the original and new KBs. Compare
  **like for like — `Retrieve` against `Retrieve`.** The source `VECTOR` KB has no agentic surface,
  so validating the new KB with `AgenticRetrieveStream` measures a different API and proves nothing
  about the migration. Compare **ranking and content, not score magnitude** (scores move scale).
- **Rollback = keep the original.** Because the original KB is untouched until step 7, rollback is
  simply "keep using the original KB / point the app back." Nothing is deleted until the user is
  confident. If the original has a Confluence, SharePoint, Salesforce or Web Crawler data source, deleting it cannot be
  undone: new connectors of these types cannot be created on self-managed (customer-managed) KBs; existing
  ones keep working ([Confluence connector page](https://docs.aws.amazon.com/bedrock/latest/userguide/confluence-data-source-connector.html),
  same notice on the SharePoint, Salesforce and Web Crawler pages). Keep the original until it is no longer
  needed for rollback.

### Caveats

- Cost and time scale with data volume (all documents are re-embedded).
- Create-new-then-cut-over allows near-zero downtime, since both KBs coexist during validation.
- All resources stay in the source Region unless docs state otherwise.
- Re-confirm every command name and parameter against the public AWS CLI reference.

### 5b. Self-managed → Managed specifics

Consult [mapping](references/bedrock-kb-migration/mapping.md) for the authoritative substitutions;
several managed behaviors are non-obvious and belong in the plan itself:

- **Embedding model & dimensions.** Default `MANAGED` needs no model choice; bring-your-own is
  `embeddingModelType: CUSTOM` at the managed dimension / FLOAT32 only (create page), which disables the managed reranker and
  cannot change after creation. Fetch the supported set from the docs; do not hardcode it or promise
  a configurable dimension.
- **Retrieval surface.** A Managed KB has two: `Retrieve` (one similarity search) and
  `AgenticRetrieveStream` (an FM planning loop that decomposes the query, iterates, and routes
  across several KBs, up to a quota read live). The agentic surface **does not exist on the source `VECTOR` KB at all** —
  plan `Retrieve` as the like-for-like replacement, and present `AgenticRetrieveStream` as a **later
  optional capability** the migration unlocks, never a required step and never something the user
  already had.
- **What callers will see (report every applicable row, every time).** Repointing to the new KB id is
  not sufficient. Take the full list from
  [managed-kb-api](references/bedrock-kb-migration/managed-kb-api.md) §3 "What changes for existing
  `Retrieve` callers" — the wrapper, `overrideSearchType` not existing, score scale and reranking mode,
  the result URI and `documentId`, the metadata keys, the unsupported filter operators, ACL KBs returning
  nothing without a user, and duplicates from overlapping data sources — and put each as an explicit
  caller-side step in the plan.
- **Connector auth prerequisites** (Confluence/SharePoint/OneDrive/Google Drive) are the top cause
  of failed data sources, and the managed shape differs. Plan them as user steps: a Secrets Manager
  secret in the KB's Region with keys matching the managed `authType`, and the KB role granted
  `secretsmanager:GetSecretValue` (plus `kms:Decrypt` / S3 certificate read as needed).
- **Sync schedule (`syncSchedule`) — carried over from the source, not asked.** Managed KBs can
  auto-sync native connectors on a `daily`/`weekly`/`monthly` schedule;
  omitting it means the data source syncs on demand only. A self-managed KB has no sync schedule, so
  the source already shows how it syncs today, and the schedule can be changed later without
  interruption. Carry it over:
  - **No timer found** (syncs are started by hand or by the customer's app): omit `syncSchedule`, so
    the managed data source keeps syncing on demand. Mention scheduled sync once as a managed gain
    (R1) and set one only if the customer asks for it.
  - **A timer found** (an EventBridge rule or scheduled Lambda that calls `StartIngestionJob`): carry its
    frequency when it is daily, weekly on one day, or monthly on a day the schedule accepts (`DayOfMonth` in the API reference) or the last day. If it matches
    none of these (for example hourly), omit `syncSchedule` and tell the customer to keep their own
    timer, pointed at the new data source at cutover; say why, and name the nearest managed schedule
    they could switch to.

  Record the schedule, or "on demand", and where it came from in the plan
  ([managed-kb-api](references/bedrock-kb-migration/managed-kb-api.md) §2).

The default naming convention is `<original-name>-managed`. A bulk migration is **one plan**.

## IaC path

Plans a **file-to-file** translation of the discovered Terraform/CloudFormation into the managed
equivalent. It plans generation only — **nothing is provisioned, deployed, or applied**, and the
agent never deploys. Rollback = keep using the source IaC / the original KB.

### Eligibility (READY / BLOCKED per KB)

For each source KB, decide `READY` or `BLOCKED` using its no-managed-path flags and the closed
blocker list in [mapping](references/bedrock-kb-migration/mapping.md) ("The blocker list is CLOSED"
section, under "Handled differently on managed") — read that section before deciding.

- **BLOCKED (excluded):** a `customTransformationConfiguration` Lambda hook; context enrichment /
  GraphRAG; or a connector confirmed absent (`WEB`, `GOOGLEDRIVE`, `SALESFORCE`, `ZENDESK` and
  `CONFLUENCEONPREM` **are** present). Record the KB id, the blocking feature, and "contact AWS
  Support." The excluded KB and all its resources are omitted from the migrated IaC — no lossy substitute.
- **READY: everything else, including every `adjusted` setting.** An **`adjusted` row is a
  supported migration, so it is never a blocker** — apply the substitution and emit it.
- A setting with no obvious mapping is **not automatically `BLOCKED`.** Check the live resource
  schema and managed connector/API docs first, state what was checked, and only then name a newly
  discovered blocker.

Both error directions fail, and false exclusion is worse: it sends the user to a support queue for a
migration that is supported today. **Exclude never approximate.** If no KB is `READY`, the phase
ends `COMPLETE` with `ready_kbs: 0` and Implement emits nothing.

### Output format and the numbered plan

Confirm the **target** (managed equivalent, same account/Region), the **naming convention**
(default `<original-name>-managed`), and the **output format**, which **defaults to the source
format** (Terraform in → Terraform out; CFN/CDK-synth in → CloudFormation out). The user may
override to exactly one of {CloudFormation, Terraform}. CDK is not an output format: a CDK source is
read through its synthesized CloudFormation, and the output is CloudFormation the customer can deploy
from their CDK app or directly.

**Deploy placement (a plan decision; default: a new stack, or a new Terraform root module).** Applying the
migrated file to the source stack or workspace replaces the KB resources there, which deletes the original
KBs, data sources and indexes — the rollback. Say so in the plan, and record `deploy_placement`.

**Planned names must be free.** Generated files name new resources from the naming convention; before the
plan is final, confirm each planned KB, data source and role name is unused with read-only
`list-knowledge-bases`, `list-data-sources` and `iam get-role`. Where a name is taken, propose a suffixed
name and use it in the plan and the generated files, or omit physical names the format can generate itself
(for example `RoleName`). Then ask the customer to confirm or change the name when they review the plan. Do
not stop before the plan to ask for a name.

For **Terraform output**, plan the provider-support check: if the installed AWS provider version
lacks MANAGED support, the fallback is to emit CloudFormation (confirmed deployable) or pin the
minimum provider version — decided honestly, **never by inventing HCL argument names**.

```
IaC MIGRATION PLAN — <source format> (VECTOR) -> <target format> (MANAGED)

Eligibility:
  - READY:   <kb-a>, <kb-b>
  - BLOCKED: <kb-c> (reason: <feature>; contact AWS Support)   # excluded

Generate the migrated IaC (agent does — provisions nothing):
  1. Emit <target-format> declaring the MANAGED KB(s) named per "<naming convention>".
  2. Emit each data source as the managed connector shape; map chunking, deletion policy, filters.
  3. Validate the emitted template against the live schema; withhold on any violation.

Deploy + cut over (USER runs later, outside this flow):
  4. Review the migrated file, then deploy it yourself as <deploy_placement> (a new stack / root module).
  5. Ingest/sync, validate retrieval, cut the app over.
  6. Decommission per the resource-level checklist below; keep any bucket a new data source reads.
```

Report the caller-visible consequences in the plan (new knowledge base id, re-embedding,
`HYBRID`-only retrieval, relevance scores moving scale, and any split lookup or lost direct index
access). The plan is where the user first sees them, while they can still say no.

**Decommission is a resource-level checklist**, never "delete the source stack". List each source resource
with what happens to it: removed after cutover (KBs, data sources, vector index or collection, vector
bucket, KB role), kept (any bucket a new managed data source reads, anything else still in use), or
untouched. A shared corpus bucket can be removed with the source stack (for example a CDK bucket with
`autoDeleteObjects`), which would empty the new KB's corpus. For a CDK source: edit the app to keep the
bucket, run `cdk diff`, and confirm only the KB, data source, index, vector bucket and role resources go.

### Verification and rollback

- **Verification:** the emitted file is schema-validated before the user sees it; after they deploy
  it, they run representative queries against the new and original KBs and compare.
- **Rollback:** the source IaC and original KB are untouched — rollback is "keep using them." The
  migrated file provisions nothing until the user chooses to deploy it.

## Persist the plan

Writing the plan is an artifact-producing action. Write the full numbered plan to the working
directory (`output_dir`) via `fs_write`, show the write, and get approval. **`plan_generated` is
`true` only when the file exists on disk.** Implement must not begin until it is. Never write secret
values.

## Phase outcome

The Plan phase ends in one of `COMPLETE | NEEDS_INPUT | BLOCKED | FAILED`:

- `NEEDS_INPUT` — the target (KB) or target/format (IaC) is unspecified; relayed to the user.
- `BLOCKED` — the target store/model is unsupported in-Region (KB), or the chosen format can't be
  produced with no acceptable fallback (IaC); stops.
- `FAILED` — a call the phase needed returned an error other than a denied permission; name the call and
  the error.
- `COMPLETE` — the plan is generated. Named outputs the next phase needs: `migration_target_type`,
  the target, the naming convention, `plan_generated`, and the plan file path; on the IaC path also
  `output_format`, `ready_kbs`, and `blocked_kbs`.

On `COMPLETE`, **the default is to stop with the plan** when the user has not chosen. If the request
already states the choice ("emit the migrated file", "stop at the plan"), that is the answer: on the
IaC path proceed to emit `managed-target.<ext>` without re-asking (nothing is provisioned). Otherwise
ask the user: stop with the plan (default), or build it (opt in to the Implement phase).

## Common mistakes

- **Guessing the path** instead of reading the target type — unset is `NEEDS_INPUT`.
- **Running a mutating command or provisioning anything** — planning is advisory/read-only.
- **Changing the store or type in place** — always create-new-then-cut-over / new resources.
- **Approximating a no-managed-path feature** instead of excluding and flagging it — or the
  opposite, excluding a KB an `adjusted` row covers.
- **Restating the substitution list or schema facts from memory** — read
  [mapping](references/bedrock-kb-migration/mapping.md) and
  [iac-schema](references/bedrock-kb-migration/iac-schema.md).
- **Skipping the naming convention** — every new resource name derives from it and must be unique.
- **Skipping re-embedding when changing models** — a full re-ingest is required.
- **Deleting the original KB too early** — keep it until the new KB is validated.
- **Promising Terraform MANAGED support without checking the provider** — plan the provider check
  and the CFN fallback.
- **Planning the template but not the consequences** — name what changes for callers before the
  user commits.
