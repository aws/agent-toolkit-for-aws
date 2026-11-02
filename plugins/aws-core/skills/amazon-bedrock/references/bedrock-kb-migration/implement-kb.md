# Implement the KB migration (build the new Managed KB via a generated script)

The Implement phase of a KB-path migration. It turns the approved plan into the new
Managed KB (`MANAGED`) and its data sources, **built alongside the source and confirmed
AVAILABLE**. Instead of firing one-at-a-time CLI calls, the agent **generates a Python
provisioning script** that creates the owned resources in rate-limit-aware batches, previews
it with a no-mutation DRY_RUN, and runs it only after explicit approval of that run.

## Contents

- [Purpose and scope](#purpose-and-scope)
- [Hard invariants](#hard-invariants)
- [Preconditions](#preconditions)
- [Build rules and request shapes](#build-rules-and-request-shapes)
- [Batching and rate limits](#batching-and-rate-limits)
- [The provisioning script the agent generates](#the-provisioning-script-the-agent-generates)
- [Teardown posture](#teardown-posture)
- [Instructions](#instructions)
- [Phase outcome](#phase-outcome)
- [Refusal behavior](#refusal-behavior)
- [Common mistakes](#common-mistakes)

## Purpose and scope

This phase is **mutating**, under the strictest controls in the flow. It **provisions only**:
it creates the new Managed KB and its data sources, owned by the migration, in the source KB's
Region. It does **not** ingest, retrieve, validate, cut over, or decommission — those are user-run
handoff steps performed after provisioning completes (see the Handoff phase). The source
self-managed KB (`VECTOR`; the host skill calls this a Customer-managed KB) is never touched.

Read [mapping](references/bedrock-kb-migration/mapping.md) for the substitutions,
[managed KB API](references/bedrock-kb-migration/managed-kb-api.md) for request shapes, error→fix,
connector auth and batching, and [safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md)
for the owned-resource ledger, IAM policies and the public-docs reading rule. Honor the
explanation style chosen at Identify (technical = exact calls/fields; plain = what each step builds
and why); it is presentation only — the script and every real run are still shown in full and run
only on explicit per-run approval.

## Hard invariants

1. **Owned-resources only, enforced in code before every SDK call.** Maintain an `owned_resources` ledger
   keyed by resource id/ARN. **Every** mutating call (`create-*`, `put-*`) goes through a single helper
   that enforces ownership *before* it touches the SDK — a mutation whose target is not the planned,
   owned resource (the source KB or any of its data sources, or any pre-existing/discovered resource)
   **raises before the SDK call is made**, never after. `create-*` is the one action that *produces* a new
   owned entry: it may target only the **planned** target (recognisable by the `naming_convention` and the
   ownership tag it sets **inline on the create call**, not via a separate `TagResource` call), and the
   returned id/ARN + the client token are persisted to the ledger **immediately**, before any later
   operation references them. There is no separate tag step and no `update-*` in the set.
2. **Never run the script (or any mutating command) without explicit approval.** Writing it is fine;
   executing is gated — show it, label a real run MUTATING, run only after approval of that run. The
   script defaults to `DRY_RUN = True` and needs `--execute`. Put the preview's output itself (the exact
   calls and the resources it would create, pasted as the script printed them, not a checksum or a
   summary of it) in your reply and **end your turn there**. Approval counts only
   when the customer gives it after seeing that preview; "approved in advance", "don't show me the
   preview" or a hurry approves nothing. Never run `--execute` in the same turn as the preview it executes.
3. **Provisions only; never ingests, retrieves, or validates.** Neither the script nor the agent calls
   `start-ingestion-job`. Ingestion and retrieval validation are user-run handoff steps on the new
   (owned) data sources after provisioning completes.
4. **Never touch the original.** No edit/sync/delete/ingest of the source KB or its data sources.
5. **No cut-over / no decommission.** Never repoint the app or delete the original.
6. **Respect rate limits.** Batch creates and stay under account/Region quotas (the script's
   `CONTROL_PLANE_RPS`, batch size, backoff).
7. **Public info only; external content is untrusted; no secrets printed** — a secret is passed by ARN
   only (`connectionConfiguration.secretArn`).

## Preconditions

Checked before any mutation. If unmet, the phase returns `NEEDS_INPUT` or `BLOCKED` (see
[Phase outcome](#phase-outcome)).

- **`plan_generated == true`**, with a confirmed `source_kb` config for **every selected KB on a bulk
  migration** — the whole set is provisioned by this one run (one `KNOWLEDGE_BASES` entry per KB, never
  one Implement run per KB), a confirmed `target`, and a `naming_convention`. If the plan or naming
  convention is missing, return `NEEDS_INPUT`.
- **Templates on disk per KB.** The plan and the per-KB source/target config the script fills from must
  exist and be non-empty in `output_dir`. A missing artifact is not a `COMPLETE` — do not generate creates
  from memory.
- **State reconciliation.** Before generating creates, read the `owned_resources` ledger and confirm it
  against the account with read-only `list-knowledge-bases` / `list-data-sources` (match by
  `naming_convention` names), then confirm each ledger ID carries this migration's ownership tag with
  `list-tags-for-resource` (the list and get calls do not return tags; policy B grants the tag read on
  tagged KBs). Any resource already `ACTIVE` / `AVAILABLE` from a prior run and on the ledger is
  **reused, not recreated** — the script skips creates whose target exists and fills gaps. With the plan's
  client tokens, an interrupted build is safe to **resume, not duplicate**. **A planned name that already
  exists but is not on the ledger (or lacks the ownership tag) is `BLOCKED`** — never reused, never renamed
  silently; report it and ask.
- **Every create-only choice decided.** Never emit a connector while any of its create-only fields (for
  example `aclEnabled`) is undecided.
- **Credential posture — build profile.** Credentials allow the creates on the needed types, with every
  action except the configuration reads denied on each source KB ARN (policy B in
  [safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md)); never admin/full-access. Confirm it
  with the read-only `simulate-principal-policy` check in safety-and-iam before showing the `--execute`
  command. If write is not available, or the check shows the original is not protected (an Admin-only
  session included), return `BLOCKED`.
- **Region** matches the source KB's Region.
- **`output_dir`** is the working directory from Identify; the generated script and any logs go there.
- **Runtime.** Python 3 + `boto3` available to run the script; if not, say so and hand the script to the
  user to run (still never run it unapproved). The handoff contains everything it refers to: the plan file
  (or its path and content), the build policy to attach, and the prerequisites that must exist first (for
  example the execution role and its policies), each written out — never "the plan above" when the plan
  was not shown.

## Build rules and request shapes

Verify — do not hallucinate.

- **Apply the validated Managed-KB substitutions** from
  [mapping](references/bedrock-kb-migration/mapping.md) **inside the values written into the script**
  (e.g. `SEMANTIC` / `HIERARCHICAL` chunking → managed default; top-level `CUSTOM` type → `CUSTOM`
  connector). Read it before generating; never re-derive a rule from memory. On a run-time rejection, use
  the [managed KB API](references/bedrock-kb-migration/managed-kb-api.md) error→fix index rather than
  guessing.
- **Confirm every `create-*` shape** against public docs (read per
  [safety-and-iam](references/bedrock-kb-migration/safety-and-iam.md)) and/or
  `aws bedrock-agent <command> --generate-cli-skeleton` before writing it into the script — the template
  bodies are sketches. Do not invent parameter names.
- **Embedding model.** The default `MANAGED` needs no model (omit `embeddingModelArn`; keeps the managed
  reranker; all documents re-embedded). For bring-your-own use `embeddingModelType: CUSTOM` — fetch the
  supported set from the managed-KB docs (do not hardcode a stale list) and confirm Region. A `CUSTOM`
  text model must use the managed **dimension and data type** from the create page (else rejected), **disables
  the managed reranker**, and cannot change
  after creation. Exact shape: [managed KB API](references/bedrock-kb-migration/managed-kb-api.md).
- **Data-source shapes** come from [managed KB API](references/bedrock-kb-migration/managed-kb-api.md)
  (S3, the auth connectors + secret-key table, CUSTOM direct-ingestion). Do not re-derive them from memory;
  reconcile once with `create-data-source --generate-cli-skeleton` for the user's Region before a real run.
- **Managed-connector gotchas** (the top causes of `FAILED`): the managed shape differs from self-managed —
  the secret is `connectionConfiguration.secretArn` (not `credentialsSecretArn`); no
  `accessControlConfiguration` / `crawlAcl` (use the flat `connectorParameters.aclEnabled`); no
  `enableDeletionProtection` (use `deletionProtectionConfiguration.deletionProtectionStatus`); connector
  names are `WEB` / `GOOGLEDRIVE` (not `WEB_CRAWLER` / `GOOGLE_DRIVE`); SharePoint `ENTRA_ID_APP_ONLY` needs
  a `certificateS3Path` even with ACLs off; `siteUrls` is a JSON array; Confluence `hostUrl` ends
  `.atlassian.net` with nested `connectionConfiguration.type: SAAS`.

## Batching and rate limits

Bedrock build-time control-plane APIs are throttled per-account/Region, and there is a **hard limit on data
sources per KB** (quota `L-F02D918A`, read live; one past it → `ServiceQuotaExceededException`; split across KBs). Firing creates
back-to-back invites `ThrottlingException`, which is why a batched script is used instead of one-by-one CLI.
The script's constants (`CONTROL_PLANE_RPS`, `DATA_SOURCE_BATCH_SIZE`, `INTER_BATCH_PAUSE_SECONDS`) are
**conservative defaults** — read the per-KB and per-account quotas from `kb-managed-quotas` and the
Service Quotas console before execution, lower the rate if throttling
appears, and never hardcode an unverified quota as fixed truth.

## The plan file and the ledger file the script reads

The script reads data, not prose. Write two JSON files to `output_dir` before generating the script:

- `migration-plan.json`: `migration_id`, `region`, `ownership_tag` (key and value), `source_kb_ids` (guard
  only), and one entry per planned KB with its planned `name`, `client_token`, the create request body, and
  its data sources (each with `name`, `client_token` and request body). Discovered free text (a KB
  description, a data source description) goes in this file only as JSON data, never into Python source.
- `owned-resources.json` (the ledger): every resource this migration created, keyed by ID, with its type,
  name and client token; execution roles with the names of their inline policies, so a later teardown can
  remove the policies before the role.

**Approval is bound to the previewed plan.** The preview prints the SHA-256 of `migration-plan.json`;
`--execute` requires `--expect-plan-sha256 <that value>` and refuses, before any SDK call, when it is missing
or does not match the file on disk. A changed plan therefore needs a fresh preview and a fresh approval.

## The provisioning script the agent generates

The agent adapts a template into a concrete script written to `<output_dir>/provision_managed_kb.py` (or a
user-chosen path — never silently). The template is **not shipped**; it is specified here. The generated
script MUST:

- **Preview by default.** `DRY_RUN = True` at module top; `--execute` is required to mutate. The DRY_RUN
  run prints the intended calls, mutates nothing, and needs no credentials. **The preview lists exactly the
  planned creates** — the KBs and data sources in the plan, with their names and shapes — and nothing else:
  a role, policy or other resource the plan leaves to the customer never appears in it.
- **Emit exactly this call set, in order:** `CreateKnowledgeBase` → batched `create_data_source` → poll
  `GetKnowledgeBase` until `ACTIVE` / `GetDataSource` until `AVAILABLE`. **`storageConfiguration` is
  omitted** (auto-provisioned on `MANAGED`). No `start-ingestion-job`, no retrieve, no cut-over.
- **Allow for a slow CMK create.** A KB created with a customer-managed key can take much longer to reach
  `ACTIVE` than one on the AWS-owned key (observed in one run: many times longer). Size the poll window
  for it, and treat a poll timeout as `FAILED` that a re-run resumes (the re-run reconciles the ledger).
- **Batch across all KBs.** Create **all** KBs first and poll every one to `ACTIVE`; then issue
  `create-data-source` for every KB in batches of ~10 (`DATA_SOURCE_BATCH_SIZE`) with an inter-batch pause;
  then poll the whole set to `AVAILABLE`. Owned-only, provisioning only.
- **Handle throttling.** A rate limiter capping at ~`CONTROL_PLANE_RPS` plus **bounded exponential backoff with
  random jitter** on `ThrottlingException` / `429`: the wait grows with each attempt, carries a random
  component, and stops after a fixed number of attempts with a clear failure naming the call. Layer it over
  boto3's `adaptive` retries; fixed sleeps between calls are pacing, not backoff.
- **Use stable idempotency tokens.** Mint every `clientToken` once, at plan time, and write it into the plan
  next to the create it belongs to: `mig-<prefix>-<hash>-<seq>`, where `<hash>` is the first 24 hex characters
  of SHA-256 over `<migration_id>|<resource type>|<planned name>`. Letters, digits and hyphens only, **≥33
  chars**. The script reads each token from the plan and never generates one (no `uuid.uuid4()`, no random
  source), so the same create sends the same token on every run: a retry never creates a duplicate and an
  interrupted run resumes cleanly.
- **Pass secret ARN only.** Auth connectors set `connectionConfiguration.secretArn`; a secret value is never
  written or printed.
- **Validate quota before any create.** Check the data-sources-per-KB quota (read live) for **every** KB **before the
  first `CreateKnowledgeBase`**, and report **all** violations at once — so an over-quota KB late in the list
  never strands earlier KBs as `ACTIVE`-but-empty with no rollback path.
- **Name every resource from `naming_convention`** (e.g. `<original>-managed`), not ad-hoc strings — the
  idempotency/reconciliation check keys off these names to avoid recreating a prior run's resource.
- **Fill every placeholder.** `REGION`, `PROFILE`, source KB id (guard/reference only), KB execution role
  ARN, embedding model (per the rule above), and one `KNOWLEDGE_BASES` entry per KB with data sources
  already translated to `MANAGED`-accepted values. An unfilled script with placeholders left in is not
  valid: if a value is unknown (a profile name, a role ARN), ask the customer for it, or do not write the
  script yet. Never write `<FILL_IN_...>` or a similar marker.
- **Degrade gracefully.** On missing tools or credentials, state the runtime requirements plainly rather
  than failing obscurely; the DRY_RUN preview must work without a filled profile.

### Mandatory owned-resource-enforcement structure (generate this shape, not looser code)

The ownership guard is **not advisory prose** — the generated script MUST refuse a non-owned target
**before** the boto3 call and MUST persist each created id/ARN and its client token to the ledger the instant
the create returns. The two creates are **not interchangeable**: `CreateKnowledgeBase` accepts inline `tags`
and returns `knowledgeBase.knowledgeBaseId`; `CreateDataSource` accepts **no** `tags` field and returns
`dataSource.dataSourceId`. Generate **two distinct helpers**, not one generic wrapper (adapt names/values;
keep the control flow):

```python
# ---- Owned-resource ledger: the ONLY record a mutation may target ----
owned_kb_ids = {}      # knowledgeBaseId -> {"name", "client_token"}   (populated as KBs are created)
owned_ds_ids = {}      # dataSourceId    -> {"kb_id", "name", "client_token"}

PLANNED = load_plan(output_dir)                 # planned KB/DS *names* + naming_convention + ownership tag
PLANNED_KB_NAMES = PLANNED.kb_names             # set[str] of planned KB names
PLANNED_DS_NAMES = PLANNED.ds_names             # set[str] of planned data-source names
SOURCE_KB_IDS    = PLANNED.source_kb_ids        # set[str] of source KB *ids*  — never a mutation target
OWNERSHIP_TAG    = PLANNED.ownership_tag         # e.g. {"bedrock-kb-migration-id": "<migration-id>"}

class NotOwned(Exception): ...

def assert_planned_name(name, planned_names):
    # A create may target ONLY a planned, not-yet-created resource named per naming_convention.
    # Names and source IDs are different namespaces — compare a NAME against planned NAMES only.
    if name not in planned_names:
        raise NotOwned(f"{name!r} is not a planned target name — refused")

def assert_owned_kb(kb_id):
    # A data source may attach ONLY to a KB this run created and persisted.
    if kb_id in SOURCE_KB_IDS:      raise NotOwned(f"{kb_id} is a source KB — refused")
    if kb_id not in owned_kb_ids:   raise NotOwned(f"{kb_id} absent from owned-KB ledger — refused")

def create_knowledge_base_owned(name, client_token, **params):
    assert_planned_name(name, PLANNED_KB_NAMES)          # RAISES before any SDK call
    if DRY_RUN:
        kb_id = f"DRYRUN-{name}"                         # placeholder id; can never match a real KB id
        owned_kb_ids[kb_id] = {"name": name, "client_token": client_token}   # in memory only, NOT persisted
        preview("knowledge_base", name, params)
        return kb_id                                     # so the data-source previews pass assert_owned_kb
    resp = client.create_knowledge_base(
        name=name,
        clientToken=client_token,
        tags={**OWNERSHIP_TAG},                          # inline ownership tag — KB create accepts tags
        **params)
    kb_id = resp["knowledgeBase"]["knowledgeBaseId"]
    owned_kb_ids[kb_id] = {"name": name, "client_token": client_token}
    persist_ledger(output_dir, owned_kb_ids, owned_ds_ids)   # PERSIST id + token IMMEDIATELY
    return kb_id

def create_data_source_owned(kb_id, name, client_token, **params):
    assert_owned_kb(kb_id)                               # parent KB must be an owned, persisted id
    assert_planned_name(name, PLANNED_DS_NAMES)          # RAISES before any SDK call
    if DRY_RUN:  return preview("data_source", name, params)
    resp = client.create_data_source(
        knowledgeBaseId=kb_id,
        name=name,
        clientToken=client_token,                        # NO tags field — CreateDataSource does not accept tags
        **params)
    ds_id = resp["dataSource"]["dataSourceId"]
    owned_ds_ids[ds_id] = {"kb_id": kb_id, "name": name, "client_token": client_token}
    persist_ledger(output_dir, owned_kb_ids, owned_ds_ids)   # PERSIST id + token IMMEDIATELY
    return ds_id
```

Rules the structure encodes, each of which the script MUST honor:

- **Ledger-first, SDK-second.** `assert_planned_name` / `assert_owned_kb` raise **before** the boto3 call. A
  create whose name is not a planned target, and any data source whose parent KB is not already an owned,
  persisted id — **especially a source KB** — raises `NotOwned` and never reaches the service.
- **Names and ids are different namespaces.** A planned resource is matched by **name** against the planned
  name set; a source KB is matched by **id** against `SOURCE_KB_IDS`. Never test a name for membership in an
  id set (or vice versa) — they never collide and the check would be vacuous.
- **Two creates, two shapes.** `create_knowledge_base_owned` sends the inline ownership `tags` and reads
  `knowledgeBase.knowledgeBaseId`; `create_data_source_owned` sends **no** `tags` field and reads
  `dataSource.dataSourceId`. Do not route both through one helper that passes `tags` to a data-source create.
- **Persist before use.** The returned id/ARN and the client token are written to the ledger **immediately**
  after each create; a later `create_data_source_owned` resolves its `kb_id` from that persisted ledger, so
  an id that was never persisted cannot be referenced.
- **The DRY_RUN preview runs end to end.** In DRY_RUN the KB helper puts a `DRYRUN-<name>` placeholder in
  the in-memory ledger (never persisted) so every data-source preview passes `assert_owned_kb`, and the
  `Get*` polling is printed, not called. The preview needs no credentials and touches no AWS resource.
- **Tag inline; no separate `TagResource` call.** The ownership tag is set in `create_knowledge_base_owned`'s
  `tags` argument. Applying that inline tag is authorized by the `bedrock:TagResource` **dependent
  permission** of `CreateKnowledgeBase` (policy B grants it for exactly this reason) — but the script issues
  **no standalone `TagResource` call**. `CreateDataSource` takes no `tags` field at all.
- **Exact call set unchanged:** `create_knowledge_base_owned(…)` → `create_data_source_owned(…)` →
  read-only `Get*` polling. No `update-*`, no `start-ingestion-job`, no `retrieve`.

## Teardown posture

The script is **fail-fast up front and has no automatic teardown**. Its only safety is the up-front quota
validation (no KB is created until the whole plan validates) plus the immutable source. There is no teardown
function and none is generated.

- **Rollback for the user = keep the untouched original.** The source KB is never mutated, so at any point
  the fallback is simply to keep using it / point the app back. Nothing of the user's is deleted.
- **On a mid-run failure**, owned resources created before the failure are listed **from the ledger**, and
  the agent **offers an owned-only teardown as a separate, explicitly approved step** — it is not performed
  automatically and never targets anything outside the ledger.

Do not claim the script tears down automatically. State this posture explicitly when reporting a `FAILED`
build. When a build stops with resources already created, say in the reply: what this run created (from the
ledger), that nothing is removed automatically, and that a teardown would delete only those resources, never
the original KB or anything that existed before. Then ask whether they want it.

## Instructions

Build → review → DRY_RUN preview → approve that run → execute → confirm → handoff.

### Step 1 — Provision supporting resources the agent owns (as needed)

If the plan needs an isolation bucket or an execution role for the new KB, ensure they exist first and add
each to `owned_resources` (or hand off to the user if out of scope for the build profile). Never reuse the
source's resources for writes.

### Step 1b — Provision connector authentication (auth connectors only)

S3 / Web / CUSTOM need no secret — skip. Confluence / SharePoint / OneDrive / Google Drive each need a
Secrets Manager secret — the #1 cause of `FAILED` data sources. Before putting such a data source in the
script:

- **The user provisions the secret** (it holds credentials the agent must not see) — present it as a user
  step. It must be in the **KB's Region** with keys matching the connector and managed `authType`.
- **Grant the KB role** `secretsmanager:GetSecretValue` on the ARN (+ `kms:Decrypt` for a CMK; +
  `s3:GetObject` / `s3:ListBucket` on the `.p12` for certificate methods).
- **Precondition gate — do not put speculative auth in the script, do not loop.** Confirm the secret exists
  (right ARN/Region/keys), the role can read it (and the certificate for Entra/App-ID methods), and
  `siteUrls` / `hostUrl` / `tenantId` are correctly shaped **before** the create runs. If anything is unmet
  or unknown, **stop and hand off the secret-creation step — never run the script to "test" auth against the
  live service.**

### Step 2 — Generate and write the script

Produce `provision_managed_kb.py` per
[The provisioning script the agent generates](#the-provisioning-script-the-agent-generates) and write it
(show the write, get approval). It must create **all** KBs first and poll to `ACTIVE`, then issue batched
`create-data-source` calls (each with the validated config and its mapping rationale) across all KBs and
poll to `AVAILABLE` — owned-only, provisioning only.

### Step 3 — Review with the user, then run a DRY_RUN preview

Show the script (or its key sections). Then run the no-mutation preview (note it changes nothing; run after
approval):

```
python3 <output_dir>/provision_managed_kb.py        # DRY_RUN=True: prints intended calls, mutates nothing
```

Use it to confirm request shapes, batch sizing and rate-limit settings before any mutation.

### Step 4 — Get explicit approval of that run, then execute

Show the real command, **label it MUTATING**, and run it **only after approval of that run**:

```
python3 <output_dir>/provision_managed_kb.py --execute     # creates KB + data sources (no ingestion)
```

It creates all KBs, waits for every one `ACTIVE`, then all data sources in rate-limited batches and waits
for every one `AVAILABLE`. On a throttling/validation error, consult the
[managed KB API](references/bedrock-kb-migration/managed-kb-api.md) error→fix index. For a `FAILED` data
source, do **one** diagnosis pass (secret/keys/Region/ARN, role perms, `siteUrls` array), report the
specific missing item, and stop. Do not loop on `FAILED`.

**If the previewed script changed, re-approve.** Any edit to the script or its inputs after the DRY_RUN
invalidates the previous approval — re-run the DRY_RUN preview and get a fresh explicit approval of the new
run before executing. Approval is bound to the exact run that was previewed.

### Step 5 — Confirm everything is ACTIVE / AVAILABLE

Independently confirm with pre-approved read-only checks:

```
aws bedrock-agent get-knowledge-base --region <REGION> --knowledge-base-id <new-owned-kb> --query 'knowledgeBase.status'
aws bedrock-agent list-data-sources  --region <REGION> --knowledge-base-id <new-owned-kb>
aws bedrock-agent get-data-source    --region <REGION> --knowledge-base-id <new-owned-kb> --data-source-id <new-owned-ds> --query 'dataSource.status'
```

Verify each KB `ACTIVE` and **every** data source `AVAILABLE` (or report the error state).

### Step 6 — Confirm provisioning complete, then return for handoff

Hand off **only after all planned KBs are `ACTIVE` and every data source `AVAILABLE`**. Ingestion (per data
source, to `COMPLETE`), retrieval validation, cut-over and decommission are all **user-run** handoff steps —
surface them as the user's next actions, each with a public doc link (verification runs the same
representative queries against the source and new KBs and compares ranking and content, not score magnitude,
`Retrieve` against `Retrieve`; the source is kept until the user is satisfied). Never run them here
(invariant 3).

### Step 7 — Report the phase outcome

Report every owned resource and its readiness, the script path, the naming convention applied, resources
reused from a prior run, and the substitutions applied; then yield to the Handoff phase.

## Phase outcome

The phase ends in one of `COMPLETE | NEEDS_INPUT | BLOCKED | FAILED`.

- `COMPLETE` — all planned KBs `ACTIVE`, all data sources `AVAILABLE`; provisioning script written. Named
  outputs the next phase needs: the new KB id(s) (one per created KB — a bulk run lists them all), the data
  source id(s), `naming_convention`, resources reused, substitutions applied, and the script path.
- `NEEDS_INPUT` — a precondition (plan, naming convention, secret) is missing; relay it to the user.
- `BLOCKED` — credential posture does not permit the build; stop.
- `FAILED` — a mid-run failure. Report the specific cause, list the owned resources created so far **from the
  ledger**, and **offer an owned-only teardown as a separate approved step** (there is no automatic
  teardown; rollback for the user is keeping the untouched original).

Phase completion means the required artifacts are present and non-empty on disk **and** the user confirmed —
confirming a file merely exists is not the same as confirming the build reached `ACTIVE` / `AVAILABLE`.

## Refusal behavior

If asked to **run the script (or any mutating command) without approval of that run**, to
modify/sync/delete/ingest the source KB, to perform cut-over, or to decommission the original — **refuse**,
explain that this phase only writes and (on approval) runs a script provisioning migration-owned resources,
and stop.

## Common mistakes

- **Managed-KB config rejections:** a customer `storageConfiguration`; `HIERARCHICAL` / `DEFAULT` /
  `SEMANTIC` chunking; **any** chunking config (incl. `FIXED_SIZE`/`NONE`) when the KB uses the managed
  embedding model ("A chunking strategy cannot be specified with a managed embedding model" —
  omit it; a chunking config is valid only with a custom embedding model); top-level
  `type: CUSTOM` instead of the `CUSTOM` connector; a self-managed connector
  field (`crawlAcl`, `credentialsSecretArn`, `enableDeletionProtection`, `WEB_CRAWLER` / `GOOGLE_DRIVE`)
  instead of the managed shape.
- **Running the script without approval of that run**, or executing after editing it without re-previewing
  and re-approving.
- **Rate limits:** creates too fast (raise the pause / lower `CONTROL_PLANE_RPS`), more data sources on one
  KB than its quota (split), or hardcoding an unverified quota.
- **Connector/auth** (top `FAILED` cause): wrong `connectionConfiguration.secretArn`, secret keys not
  matching the managed `authType`, SharePoint `ENTRA_ID_APP_ONLY` missing `certificateS3Path`, KB role
  lacking `secretsmanager:GetSecretValue` / `kms:Decrypt` (or S3 cert read), or `siteUrls` as a string
  rather than a JSON array.
- **Others:** leaving template placeholders unfilled, hallucinating a request shape, assuming an unsupported
  embedding model, promising a dimension count, or claiming an automatic teardown that does not exist.
