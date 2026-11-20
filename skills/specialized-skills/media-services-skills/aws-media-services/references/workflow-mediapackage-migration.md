# MediaPackage v1 → v2 Migration Workflow

Guides a user through migrating AWS Elemental MediaPackage **v1 Live**
channels and origin endpoints to **MediaPackage v2**: discover v1 resources,
organize channels into v2 channel groups, translate endpoint configurations,
generate migration artifacts (CLI / CloudFormation / SDK), then optionally
execute and validate them.

This is the entry point for any migration task, and the migration files are
**self-contained**: do not load `service-rules-core.md` or any other
`service-rules-*.md` file for a migration. The goal is to reproduce the
user's v1 setup in v2 as it is, not to redesign it to this skill's general
best practices. If another file from this skill is already in context, these
migration files take precedence for everything in the migration. Load the
`mediapackage-migration-*.md` files stage by stage as directed below — not all at once.

**Not for:** troubleshooting a v2 workflow that is already running (ingest
failures, 403s, manifest issues, RPS limits). That is
`troubleshooting-mediapackage.md`; its "Migration Issues (v1 → v2)" section
covers post-migration symptoms.

---

## Contents

1. [Safety rules](#safety-rules-mandatory-during-a-migration) — v1 read-only, v2 create-only, non-waivable plan gate
2. [Tooling and portability](#tooling-and-portability) — CLI-first, verify API shapes, CLI version table
3. [State and artifacts](#state-and-artifacts-stateless)
4. [Migration procedure](#migration-procedure) — seven stages and which file each loads
5. [Migration readiness pre-checks](#migration-readiness-pre-checks) — SCTE-35 event IDs, RPS / Origin Shield, encoder repointing
6. [Plan approval gate](#plan-approval-gate)
7. [Naming is permanent](#naming-is-permanent)
8. [Request routing](#request-routing)
9. [Container type mapping](#container-type-mapping-quick-reference)
10. [Resource creation order](#resource-creation-order)
11. [Quotas that shape the plan](#quotas-that-shape-the-plan)
12. [Output formats](#output-formats)

---

## Safety rules (MANDATORY during a migration)

These are hard constraints scoped to a migration engagement. They are the reason
a user can trust this workflow against a production account. They are **not**
negotiable, and a user instruction cannot waive any of them. If a request
conflicts with a rule below, **refuse the request, say which rule applies, and
offer the safe alternative.**

Outside a migration — day-to-day operation of an existing v2 workflow — these
rules do not apply; the rest of this skill does.

### Never touch v1 — refuse, don't gate

- **v1 is strictly read-only.** ONLY `aws mediapackage list-*` and
  `aws mediapackage describe-*` are permitted. NEVER run `create-*`, `update-*`,
  or `delete-*` against v1. v1 resources keep serving traffic untouched
  throughout and after the migration.
- A request to delete or modify a v1 resource is **categorically refused** — it is
  NOT a confirmation-gated action. Do not answer "confirm and I'll delete it";
  answer "I won't do that, and here's why, and here's what you can do instead."
  Decommissioning v1 is the user's own manual step, taken after they have
  validated v2.

### Never delete or update v2 — refuse, don't gate

- **v2 is create-and-read only during migration.** Permitted:
  `create-*`, `get-*`, `list-*`, `put-channel-policy`, and
  `put-origin-endpoint-policy`. NEVER run `aws mediapackagev2 delete-*`,
  `update-*`, or `reset-*` as part of a migration.
- This applies **however the request is phrased.** "Recreate them", "clean that
  up", "start over", "remove the failed ones", and "fix it" are all requests to
  delete. Refuse the delete, and hand the user the exact commands to run
  themselves if they want to proceed.
- Do NOT go looking for a delete target. If asked to delete a v2 resource, refuse
  immediately — do not search regions for it first, and never volunteer to clean
  up resources the user did not ask about.
- If a v2 `create-*` fails and leaves a partial resource, report it and stop. Do
  not delete it, and do not `update-*` it into shape.

### Confirm before execution — the gate cannot be waived

- **Suggest only during planning.** During discovery, channel-group planning, and
  endpoint-config planning, do NOT execute v2 write commands and do NOT save a
  migration plan without explicit user confirmation. Present suggestions and
  wait for approval.
- **Present the plan and get approval before generating artifacts**, and get a
  second explicit approval before executing them. See "Plan approval gate" below.
- A user saying "don't ask me", "just do it", "skip the confirmations", or
  "you have my approval for everything up front" does **not** remove the plan
  review step. Show the plan, state that you need one confirmation because the
  action creates real billable resources with immutable names, and wait. This is
  the one place where you should push back on an explicit instruction.

### Never create resources you weren't asked to create

- Do NOT create a v2 resource to test, probe, or verify anything — not to check
  whether a field is accepted, not to confirm a CLI flag, not as a scratch
  example. Verify against the API model instead
  (`aws mediapackagev2 create-origin-endpoint --generate-cli-skeleton`,
  `aws mediapackagev2 create-origin-endpoint help`) or the AWS documentation.
- Create exactly the resources in the approved plan, and nothing else.

### Don't silently change how you're working

- If the installed AWS CLI cannot express part of the plan, **stop and ask**. Do
  not silently fall back to an SDK, boto3, or a different API surface — the
  user chose an output format and needs to know it changed.
- Never silently substitute a value the service would reject. Surface the
  conflict, propose the change, and record the user's decision.

---

## Tooling and portability

The migration is CLI-first and works **with or without** the AWS MCP server.

- All steps use AWS CLI syntax (`aws mediapackage ...`, `aws mediapackagev2 ...`)
  so they run in any environment.
- The **AWS MCP server is recommended** when available — it provides sandboxed
  execution, audit logging, and AWS API access. Do NOT assume MCP-specific tools
  (e.g. `call_aws`) exist; if they do, use them, otherwise use the shell's `aws`
  CLI directly.
- Always pass `--region` explicitly on every call.

### Verify API shapes — do not translate from memory

The v2 API model changes over time, and several v1 field names
survive into v2 with different valid values. Before you emit a v2 config
containing an enum value or a field name you have not just read, **check it
against the API model that is actually installed**:

```
aws mediapackagev2 create-origin-endpoint --generate-cli-skeleton
aws mediapackagev2 create-origin-endpoint help
```

The skeleton is authoritative for the caller's CLI version: it lists every field
and the exact member names. Use `help` for valid enum values and numeric ranges.
If a mapping table in these files disagrees with the installed model, the model
wins — say so, and flag the doc discrepancy to the user.

### AWS CLI version matters

Some v2 features need a recent AWS CLI, and an older CLI fails **client-side**,
before the request is signed, so the error is not the service's behavior. Check the
installed CLI's own model rather than a version number:

- `aws mediapackagev2 create-origin-endpoint help` lists `--mss-manifests` only if
  that CLI supports MSS/ISM endpoints.
- `aws mediapackagev2 put-origin-endpoint-policy help` lists
  `--cdn-auth-configuration` only if that CLI supports CDN authorization.
- A local `ParamValidation` error on `--startover-window-seconds 0` means the CLI is
  too old. The service accepts `0`; silently dropping the flag would migrate a v1
  window of `0` into v2's 900-second default.

Tell the user that the migration relies on a current AWS CLI: if theirs is not the
latest version, the accuracy of the migration may be affected, because an older CLI
can reject valid v2 values or lack flags the plan needs. Recommend `aws update`. See `references/mediapackage-migration-execution.md` for the full
pre-flight.

---

## State and artifacts (stateless)

The migration does not run a persistent state machine. The host agent drives the
conversation; these files are the guidance it follows within a session.

- The **durable output is the generated migration plan** (a CLI script,
  CloudFormation template, or SDK file) plus the v2 resources themselves, which
  are always queryable via `aws mediapackagev2 get-*` / `list-*`.
- You MAY persist working artifacts to an `.mediapackage-migration/` directory in the
  working directory if your environment can write files —
  `v1-resource-inventory.json` (discovery output) and `migration-plan.json`
  (channel-group + endpoint plan). These make hand-off and resume easier, but
  they are **optional conveniences, not required control state**. If you cannot
  write files, keep the inventory and plan in conversation context instead.
  Ask before writing into a directory that looks like a source tree.
- These files hold the user's full endpoint configuration, including access
  control (IP allow-lists, CDN authorization with its Secrets Manager secret ARN
  and role ARN, and SPEKE role ARNs). They never contain secret values, but tell
  the user what they contain, keep them out of source control (add
  `.mediapackage-migration/` to `.gitignore`), store them only where access is
  restricted to the people running the migration, keep them on encrypted storage
  (an encrypted disk or volume, never a shared or unencrypted location), and
  delete them when the migration is done.
- To resume an interrupted migration: re-run discovery (it is read-only and
  cheap), or read back a previously written `migration-plan.json` if present.

---

## Migration procedure

Follow these stages in order within a session. Each stage has a reference file —
**load it and follow it fully** when you reach that stage. Do not load all
references up front; load each one when its stage begins.

1. **Onboarding** — Validate prerequisites and scope before touching resources:
   - Confirm AWS credentials/identity: `aws sts get-caller-identity`. Show the
     user the account ID you are about to operate in and have them confirm it.
   - Confirm the AWS CLI version (`aws --version`) and run the capability checks in
     "AWS CLI version matters" above. If the CLI is not the latest, tell the user the
     accuracy of the migration may be affected. If a check fails, say exactly which
     capabilities are affected and ask whether to upgrade or to generate SDK code
     instead. Do not proceed to execution on a CLI that cannot express the plan.
   - Ask which **region(s)** contain the v1 resources, and **record the answer** —
     including which regions are deliberately out of scope. A later reader of the
     plan must be able to tell "excluded on purpose" from "never looked".
   - Confirm the user's IAM identity can read v1
     (`mediapackage:List*`/`Describe*`) and write v2 (`mediapackagev2` create/get/list and
     `PutChannelPolicy`/`PutOriginEndpointPolicy`), plus `aws-mcp` access if using
     the MCP server.
   - Check the **existing v2 state and quota headroom** before promising anything:
     `aws mediapackagev2 list-channel-groups --region <region>` (paginate), and read
     the account's applied channel-group quota with
     `aws service-quotas get-service-quota --service-code mediapackagev2 --quota-code L-A7040149 --region <region>`
     (the quota named "Channel Groups"; do not guess a different code). Never assume the account has zero
     channel groups. Details in `references/mediapackage-migration-channel-groups.md`.
   - Run the **migration readiness pre-checks** below.
   - Tell the user: "Your v1 resources will never be modified or deleted —
     all v1 operations are read-only."

2. **Discovery** — Enumerate v1 channels and origin endpoints; classify endpoint
   types; let the user pick all or a subset.
   → Load `references/mediapackage-migration-discovery.md`

3. **Channel group planning** — Suggest how to organize the included v1 channels
   into v2 channel groups; refine interactively.
   → Load `references/mediapackage-migration-channel-groups.md`

4. **Endpoint configuration planning** — Translate each v1 endpoint config to its
   v2 equivalent; flag incompatibilities; identify endpoint merge opportunities.
   → Load `references/mediapackage-migration-endpoint-config.md`

5. **Plan approval gate** — Present the complete plan and get explicit approval
   before generating anything. See "Plan approval gate" below. This step is not
   optional and cannot be waived by the user.

6. **Plan generation** — Generate migration artifacts in the user's chosen
   format (CLI / CloudFormation / SDK), in correct resource-creation order, after
   running the pre-flight validation checklist.
   → Load `references/mediapackage-migration-execution.md` (Plan Generation section)

7. **Execution & validation** — Optionally create the v2 resources, then verify
   the created resources match the plan.
   → Load `references/mediapackage-migration-execution.md` (Execution and Validation sections)

If the user's request maps directly to a later stage (e.g. "generate the CLI
script"), you may jump there — but confirm the prerequisite information for the
earlier stages exists (you need an inventory and a channel-group + endpoint plan
before you can generate artifacts).

---

## Migration readiness pre-checks

Three v2 behavior differences bite after cutover rather than during creation.
Check them during onboarding and record the outcome in the plan.

```
IF SCTE-35 CUE-OUT and CUE-IN carry matching segmentation_event_id values:
  → Safe. v2 SCTE35_ENHANCED mode tracks avails by event ID.
IF event IDs do not match:
  → Fix upstream signaling before migrating — v2 will produce stuck avails
    (CUE-OUT never closes).
IF every CDN in front of the endpoints has Origin Shield (or equivalent):
  → Safe from the RPS perspective.
IF any CDN lacks Origin Shield:
  → Add it before cutover. v2 enforces per-endpoint egress rate limits (about
    500 segment RPS, 10,000 manifest RPS; confirm with `aws service-quotas list-service-quotas --service-code mediapackagev2`); without shielding, 429/503s appear at cutover.
IF the v2 channels keep HLS input (the default — see the channel input type step
in references/mediapackage-migration-channel-groups.md):
  → The encoder keeps sending HLS. Its only change is the destination. At cutover
    it must ADD a second output aimed at the v2 ingest endpoints and keep the v1
    output running until the CDN has moved; repointing the only output starves v1
    while the CDN still pulls from it. Record that as a user step; this
    workflow does not modify the encoder.
IF the user explicitly chose CMAF input:
  → The encoder output must change too (for MediaLive, HlsGroupSettings →
    CmafIngestGroupSettings) before cutover. Record it as a user
    prerequisite.
IF the workflow depends on epoch locking:
  → Supported on v2, but it REQUIRES CMAF input: the v2 channel needs `InputType`
    `CMAF`, and its `OutputLockingMode` (`create-channel --output-locking-mode`,
    valid only with CMAF input) must be `EPOCH_LOCKED`, which is the default for
    CMAF. Both are set at creation and neither can be changed afterwards. The
    encoder must also send epoch-locked CMAF (for MediaLive, a CMAF Ingest output
    group with a shared custom epoch). Raise this at the channel input type step
    BEFORE any channel is created — the HLS default cannot do epoch locking, and
    discovering it later means deleting and recreating the channel. Also confirm
    the contribution feed carries source timecode.
```

---

## Plan approval gate

Before generating artifacts, present the plan and **stop**. The user must see,
and explicitly approve:

1. **Scope** — account ID, regions in scope, regions deliberately excluded, and
   which v1 channels/endpoints are included vs excluded.
2. **Channel groups and channels** — new groups to create, existing groups being
   reused, how that lands against the account's channel-group quota, and the channel
   input type (`HLS` unless the user chose `CMAF`; it cannot be changed later).
3. **Names** — every v2 channel group, channel, origin endpoint, and manifest name.
   Call out that resource names are **immutable** and appear in the playback URL
   (see "Naming is permanent" below). Merged endpoints and renamed manifests need
   the most attention here, because those names are ones you invented, not ones
   the user chose.
4. **Every non-1:1 translation** — clamped values, omitted fields, changed enum
   values, and anything that changes runtime behavior.
5. **Incompatibilities** and the resolution chosen for each.
6. **Prerequisites the user must do themselves** before execution can succeed
   — quota increases, SPEKE v2 key-provider readiness, CDN-auth secret and IAM
   role changes, CDN header rename, repointing the encoder at the v2 ingest
   endpoints (and changing its output to CMAF, only if CMAF input was chosen),
   Origin Shield, CLI upgrade.

Then ask, in one question: *"Does this plan look right, and would you like to
change anything before I generate the artifacts?"*

Ask for the plan's blockers to be resolved before execution, not during it. A
prerequisite discovered at execution time has already cost the user a
half-migrated account.

---

## Naming is permanent

In v2 the resource names are part of the identity and part of the playback URL:

```
https://<egress-domain>/out/v1/<channelGroup>/<channel>/<originEndpoint>/<manifest>...
```

- `ChannelGroupName`, `ChannelName`, and `OriginEndpointName` **cannot be changed
  after creation** — a rename means delete and recreate.
- Each channel group has a **fixed egress domain for its lifetime**, shared by
  every channel and endpoint in it. Recreating a channel group yields a *different*
  egress domain, which breaks every CDN and player pointed at it.
- Manifest names *can* be changed later via `UpdateOriginEndpoint` (which this
  workflow does not do), but changing one changes the playback URL, so treat it
  as equally permanent for planning purposes.

Because of this, get explicit sign-off on names — especially any name you
generated yourself for a merged endpoint or a renamed manifest — rather than
picking something reasonable and moving on.

---

## Request routing

| User asks to… | Load |
|---|---|
| discover / inventory / list v1 resources | `references/mediapackage-migration-discovery.md` |
| plan / organize / group channels into channel groups | `references/mediapackage-migration-channel-groups.md` |
| map / translate / convert endpoint configurations | `references/mediapackage-migration-endpoint-config.md` |
| generate a plan / script / template / SDK code | `references/mediapackage-migration-execution.md` (Plan Generation) |
| execute / create v2 resources / validate the migration | `references/mediapackage-migration-execution.md` (Execution, Validation) |

---

## Container type mapping (quick reference)

The fundamental v1→v2 translation. Full field-level mappings, encryption, SCTE,
and merge rules are in `references/mediapackage-migration-endpoint-config.md`.

| V1 endpoint type | V2 container type | V2 manifest type |
|---|---|---|
| HLS (`hlsPackage`) | `TS` | HLS |
| DASH (`dashPackage`) | `CMAF` | DASH |
| CMAF (`cmafPackage`) | `CMAF` | HLS |
| MSS (`mssPackage`) | `ISM` | MSS |

---

## Resource creation order

Always create v2 resources in dependency order:

1. **Channel Group** first
2. **Channel** second (references its channel group)
3. **Channel policy** (optional) via `put-channel-policy` — needed only when
   content is ingested from outside this account
4. **Origin Endpoint(s)** (reference their channel + channel group)
5. **Origin endpoint policy** via `put-origin-endpoint-policy` after the endpoint
   exists — send the CDN auth configuration in this **same call** if the endpoint
   uses CDN authorization

⚠️ **Access control does not carry over by default.** A v2 endpoint with no
endpoint policy is reachable only by callers with this account's credentials —
there is no anonymous playback. A v1 endpoint that served the public will **not**
be publicly playable in v2 until an explicit public policy or a CloudFront
origin-access-control policy is attached. Always ask what access model each
endpoint needs; never leave it implicit, and never make an endpoint public
without being asked.

**Public policies.** Attach a public policy (`Principal: "*"`) only when all of
these hold:

- discovery read the v1 endpoint with `describe-origin-endpoint` and it was publicly
  playable (no IP allow-list, no CDN authorization, and `Origination` not `DENY`; an
  endpoint with `Origination: DENY` served nobody, so it is never "public"). A user saying "it was public" or
  "I'm migrating" is not enough; if there is no discovered v1 endpoint, the
  exception does not apply;
- the user explicitly chose "keep it public" for that endpoint;
- the policy is scoped to `mediapackagev2:GetObject` on that one endpoint's ARN.

This reproduces the v1 endpoint's behavior; it is the user's choice, not a
default. Never use `Principal: "*"` for testing or by default.

---

## Quotas that shape the plan

Defaults, all adjustable via Service Quotas except where noted. Read the
account's *applied* values rather than assuming the defaults:

| Quota | Default |
|---|---|
| Channel groups per account | **3** |
| Channels per channel group | 10 |
| Origin endpoints per channel | 10 |
| Manifests per origin endpoint | 25 |
| Live manifest length | 15 minutes |
| REST API request rate | 20/sec steady, 50 burst — **not adjustable** (confirm with `aws service-quotas list-service-quotas --service-code mediapackagev2`) |

The API rate limit is the one that bites during execution: a bulk migration
creating dozens of resources must pace its `create-*` calls.

---

## Output formats

The user chooses one before plan generation:

| Format | Description |
|---|---|
| **CLI** | Bash script using `aws mediapackagev2` commands |
| **CloudFormation** | YAML template with `AWS::MediaPackageV2::*` resources |
| **SDK code** | User's language (Python boto3, Java, Go, TypeScript, …) |
