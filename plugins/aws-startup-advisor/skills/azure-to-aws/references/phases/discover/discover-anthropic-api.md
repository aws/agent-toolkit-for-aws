# Discover Phase: Anthropic Usage API Discovery

> Self-contained Anthropic usage discovery sub-file. Captures real cost and
> token-usage data directly from the Anthropic Admin API — read-only,
> consent-gated — as an alternative to the user exporting billing CSVs by
> hand. Produces `anthropic-usage-profile.json` and, when
> `ai-workload-profile.json` exists, fills its `current_costs` section with
> real spend. Scoped to Claude Console / Claude Platform (API) organizations
> only — Claude Enterprise (claude.ai) orgs use a different Analytics API and
> are out of scope (see Step 1 org-type check). If the user declines consent
> or has no Admin API key, exits cleanly with no output.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Security Contract (applies to every step)

1. **Exact-endpoint allowlist, GET only.** Call ONLY the two endpoints below,
   both `GET` against `https://api.anthropic.com`:
   - `GET /v1/organizations/usage_report/messages`
   - `GET /v1/organizations/cost_report`

   Never any other endpoint, never any other HTTP method. The SAME Admin key
   could technically call Admin (member/workspace/invite management),
   Compliance, Spend Limits, and Rate Limits endpoints — this flow never
   calls them, regardless of what the key is capable of. This is a bigger
   deal than for most providers' keys (same key, broader blast radius) —
   never widen this allowlist, even to a read-only-looking Admin endpoint.
2. **The Admin key must never enter this conversation (HARD RULE).** Do not
   ask the user to paste the key in chat, and never echo, cat, or interpolate
   its VALUE into any command, question, or output — the agent only ever
   handles the file path `$MIGRATION_DIR/.anthropic-admin-env` (`chmod 600`,
   inside the gitignored `.migration/` tree). If the user pastes a key into
   the chat unprompted, do not use it: tell them it is now part of the
   transcript, recommend rotating it, and continue with the Step 1 intake
   paths. All API calls go through a throwaway capture script that reads the
   key from the file and sends it as `x-api-key: <key>` (NOT `Authorization:
   Bearer` — Anthropic's auth header differs from OpenAI's/OpenRouter's).
   Every request also carries a required `anthropic-version: 2023-06-01`
   header — OpenAI's capture script needs no such header; do not drop it.
   Only a sha256 fingerprint of the file appears in the manifest, and the key
   file is **deleted by default** when capture completes (Step 4).
3. **Scoped, aggregate data only; no per-key/per-user grouping; workspace
   scoping required.** The usage/cost endpoints return bucketed token counts
   and cost amounts — no prompts, no completions, no file contents. Captures
   are filtered to the Anthropic workspace(s) the user selects in Step 2b —
   never attribute whole-org spend to this application. Do NOT add
   `group_by=api_key_id` or `group_by=account_id`/`service_account_id` to any
   call: group by `model` on the usage endpoint, and by `description` or
   `workspace_id` on the cost endpoint, only.
4. **Capture to files, not context.** The capture script writes responses
   under `$MIGRATION_DIR/anthropic-capture/`. Parse capture files with a
   throwaway extraction script if any exceeds ~500 buckets — do NOT Read
   oversized raw captures into context.
5. **Consent first.** Nothing data-touching happens before the user answers
   `[A]` in Step 0 — no key intake, no key file on disk, no API call. The
   Step 0 consent is THE consent gate for this source (the orchestrator only
   decides whether to load this file).
6. **Delete the key file at every exit except an explicit pending retry.**
   Every terminal-exit branch in Step 2 (the organization-type fork, an
   all-rows-failed capture, or any other hand-off to the user) deletes
   `$MIGRATION_DIR/.anthropic-admin-env` immediately and tells the user it
   was deleted — except the one documented case: a `KEY_INVALID_MID_RUN`
   abort writes `retry_pending: true` to the manifest and leaves the key
   file in place, because the resume path ("On resume, re-run Step 2 —
   captures overwrite") legitimately needs it. That pending state is
   cleared (file deleted, `retry_pending: false`) the moment the retry
   either succeeds or is itself abandoned. Step 0/1 declines happen before
   the key file exists, so there is nothing to delete there.

---

## Step 0: Consent Gate

Output exactly, then wait for the user's choice:

```
─── Anthropic Usage Discovery (read-only) ───

I can pull your organization's Anthropic (Claude API) cost and usage data
directly from the Anthropic Admin API. This runs GET requests only, against
a fixed list of two usage/cost endpoints:

  ✓ Captured: daily token counts by model (input, output, cache read, cache
    creation), and USD cost by workspace or by model/inference-geo — scoped
    to the workspace(s) YOU select as belonging to this application.
  ✗ Never captured: prompts or completions content, org member data,
    per-key/per-user attribution, or any non-GET request. No request that
    creates, changes, or deletes anything will run — and no Admin,
    Compliance, Spend Limits, or Rate Limits endpoint is ever called, even
    though the same key can reach them. Per-model/per-description DATA from
    workspaces you don't select is never captured — but building the
    workspace picker below (Step 2b) necessarily reads an org-wide,
    per-workspace SPEND TOTAL first, before you choose; that one probe call
    is the single exception to "workspaces you don't select are never read."

Window: last 30 days. You'll need an Anthropic ADMIN API key
(`sk-ant-admin01-...`). Important: Anthropic's Console-tier Admin key has NO
selectable scopes — it is all-or-nothing, and it also grants access to
organization member/workspace management, compliance, spend limits, and rate
limits, not just usage data. There is currently no narrower "usage-only" key
for Console/API organizations (unlike some other providers). I will only call
the two endpoints listed above with it. (The key is written to a chmod-600
file inside the gitignored .migration/ directory, never echoed, and deleted
when capture completes.)

This flow supports Claude Console / Claude Platform (API) organizations only.
Claude Enterprise (claude.ai) orgs use a separate Analytics API that this
flow does not yet support — if you're on Enterprise, skip this and I'll note
it as not yet implemented.

[A] Proceed with Anthropic usage discovery
[B] Skip — use exported billing files only (or none)
```

- **[A]** → continue to Step 1.
- **[B]** → exit cleanly with no output (record the decline for the orchestrator).

## Step 1: Key Intake and Preflight

1. **Runtime available:** `curl --version` (first line) and `python3 --version`
   (fall back to `python`, then `node`). If curl AND all script runtimes are
   missing → tell the user and exit cleanly.
2. **Explain the key requirement** (before asking for anything):
   "Anthropic usage discovery needs an **Admin API key**
   (`sk-ant-admin01-...`), created in the Anthropic Console under
   organization settings. As noted above, this key has no selectable scopes
   — I will only call the two usage/cost endpoints with it, never anything
   else."
3. **Check the environment first** (presence only, never the value):

   ```bash
   [ -n "$(printenv ANTHROPIC_ADMIN_KEY)" ] && echo ENV_KEY_PRESENT || echo ENV_KEY_ABSENT
   ```

4. **Key intake.** Ask: "How would you like to provide the Admin key?" (offer
   `[A]` only on `ENV_KEY_PRESENT`):
   - **[A] Use the `ANTHROPIC_ADMIN_KEY` already in my environment** →
     materialize env var to file in one command — the value never appears in
     the transcript:

     ```bash
     printf 'ANTHROPIC_ADMIN_KEY=%s\n' "$(printenv ANTHROPIC_ADMIN_KEY)" > "$MIGRATION_DIR/.anthropic-admin-env" && chmod 600 "$MIGRATION_DIR/.anthropic-admin-env"
     ```

   - **[B] I'll write it to a file myself** → give the user this command to run
     in THEIR OWN terminal (not through the agent) — `read -rs` collects the key
     without echoing it:

     ```bash
     read -rs k && printf 'ANTHROPIC_ADMIN_KEY=%s\n' "$k" > "<MIGRATION_DIR>/.anthropic-admin-env" && chmod 600 "<MIGRATION_DIR>/.anthropic-admin-env" && unset k
     ```

     Substitute the literal run-directory path when presenting it (the path is
     not a secret). Continue when the user says it's done.
   - **[C] Skip Anthropic usage discovery** → exit cleanly with no output.
5. **Format check** (never prints the key) — Admin keys are
   `sk-ant-admin01-...`; rejecting other prefixes catches a pasted
   regular/non-admin key early:

   ```bash
   grep -qE '^ANTHROPIC_ADMIN_KEY=sk-ant-admin01-.+' "$MIGRATION_DIR/.anthropic-admin-env" && echo KEY_FORMAT_OK || echo KEY_FORMAT_BAD
   ```

   On `KEY_FORMAT_BAD`: tell the user the file does not contain an Admin key
   (`sk-ant-admin01-...`) and re-run intake (do not echo file contents).

**IMPORTANT:** Do NOT rely on the environment variable during capture — env vars
do not persist across Bash tool calls. The capture script reads the file path
above.

## Step 2: Capture

Create `$MIGRATION_DIR/anthropic-capture/`.

**2a. Write the capture script** to `$MIGRATION_DIR/_capture_anthropic.py` (or
`.js` — whatever runtime Step 1 found). The script (and nothing else) touches
the key:

- Reads `ANTHROPIC_ADMIN_KEY` from `$MIGRATION_DIR/.anthropic-admin-env`.
- Sends `x-api-key: <key>` **AND** `anthropic-version: 2023-06-01` on every
  request (this second required header is the OpenAI-vs-Anthropic
  capture-script difference — do not omit it). Never prints the key or any
  header; on HTTP errors it prints ONLY the status code and the response
  `error.message`.
- Computes `starting_at` = now − 30 days (ISO 8601).
- For each requested call: follows pagination (`page` / `next_page` cursor)
  until exhausted, concatenates all pages' data, and writes the result to the
  named file.
- Bucket limits: usage endpoint `bucket_width=1d&limit=31` — **max 31, NOT
  OpenAI's 180** (the `1d` bucket width's default is 7, max is 31; this is a
  copy-paste trap when modeling the script on the OpenAI/OpenRouter capture
  scripts — do not reuse `limit=180`). Cost endpoint `limit=31` (its own
  default is 7, max 31).
- A non-200 on one endpoint records `failed` for that row and continues — a
  missing endpoint or zero usage is normal, never a halt. **Exception: a 401
  AFTER the probe succeeded** means the key was revoked or rotated mid-run —
  abort the remaining calls (keep completed capture files) and exit with a
  distinct `KEY_INVALID_MID_RUN` line so the agent can hand off. This is the
  one exit that keeps the key file: write `retry_pending: true` to the
  manifest and do NOT delete `$MIGRATION_DIR/.anthropic-admin-env` — the
  user may resume by re-running Step 1 (re-intake if needed) then Step 2,
  which overwrites captures. The moment that retry either succeeds or is
  abandoned, delete the key file and set `retry_pending: false`.
- **Org-type fork handling:** if the probe call fails in a way suggesting an
  Enterprise-only org (a 404 on the organizations endpoint path, or an error
  message naming Enterprise/Analytics), tell the user: "This looks like a
  Claude Enterprise organization — Enterprise Analytics API support is not
  yet implemented in this flow", delete `$MIGRATION_DIR/.anthropic-admin-env`
  (this is a terminal exit, not a pending retry — `retry_pending: false`),
  and exit cleanly (not a hard failure, not `KEY_INVALID_MID_RUN`).
- Prints one line per call: `<file> ok|failed|skipped <n_buckets>`.

**2b. Probe and workspace scoping.** The capture script runs the probe call
first (2a rules apply — the agent never invokes curl with the key itself),
using the cost endpoint grouped by `workspace_id` (this directly yields the
per-workspace spend list needed for selection, mirroring the project-scoping
probe pattern used for other providers):

```
GET /v1/organizations/cost_report?starting_at=<t>&group_by=workspace_id&limit=31  →  cost-by-workspace.json
```

- On 401: stop and tell the user: "The key was rejected. Confirm it is an
  **Admin** key (`sk-ant-admin01-...`)." Offer to re-run Step 1 intake or
  skip. On 429, wait 30 seconds and retry once.
- On an Enterprise-shaped failure: apply the org-type-fork exit from 2a.
- On success: sum spend per `workspace_id` and present the list (workspace id
  - window spend, sorted descending). Then ask: "Which of these Anthropic
  workspaces belong to THIS application? List the workspace IDs, or answer
  `all` only if this org serves just this app." Set `$WORKSPACE_IDS` to the
  selection. **Never default to `all`** — org-wide spend attributed to one
  app corrupts the migrate-or-stay numbers downstream. The user may also give
  each selected ID a label (e.g. "wrkspc_abc = production"); record labels in
  the profile.
- **Confirm before capture** (applies equally when the answer was `all`):
  "Selected workspaces account for $X of $Y total org spend in this window.
  Capture these? [Y] Proceed / [N] Re-select". On [N], re-show the list once.

**2c. Capture Endpoint Table.** Row 1 is filtered to the selected workspaces
in a single call via repeated `workspace_ids[]=<id>` query parameters. Row 2
(cost_report) cannot: the API's `group_by` only accepts one dimension per
call, and `description` (needed to recover `model`/`inference_geo` per row)
is a different dimension than `workspace_id` — so row 2 runs **once PER
selected workspace** (loop over `$WORKSPACE_IDS`, one call per iteration,
each still scoped with `workspace_ids[]=<single id>` + `group_by=description`),
and the script attaches that iteration's `workspace_id` to every row of its
response before concatenating all iterations' results into one output file.

| # | Endpoint (GET, `https://api.anthropic.com`) | Query parameters | Output file |
|---|---|---|---|
| 1 | `/v1/organizations/usage_report/messages` | `starting_at`, `bucket_width=1d`, `group_by=model`, `workspace_ids[]…` (all selected, one call), `limit=31` | `usage-messages.json` |
| 2 | `/v1/organizations/cost_report` | `starting_at`, `bucket_width=1d`, `group_by=description`, `workspace_ids[]=<single id>` (one call PER selected workspace), `limit=31` | `cost-report.json` (concatenated across all workspace calls, each row tagged with its `workspace_id`) |

Grouping the cost endpoint by `description` (not `workspace_id`, which is
reserved for the Step 2b probe only) is what parses out `model`/
`inference_geo` fields per-row — Step 3 needs the `description` breakdown
AND the per-call `workspace_id` tag to attribute cost per model per
workspace; without the per-workspace loop, a multi-workspace selection would
aggregate every selected workspace's spend into one `description` bucket
with no way to break it back out. Code-execution costs appear only in
`cost-report.json`, never in `usage-messages.json` — do not assume cost is
derivable from tokens alone.

**2d. Run the script, then delete it.** Record results in
`$MIGRATION_DIR/anthropic-capture/manifest.json`:

```json
{
  "captured_at": "<ISO 8601 UTC>",
  "window_days": 30,
  "admin_key_sha256": "<sha256 of .anthropic-admin-env contents — fingerprint only>",
  "workspace_filter": ["wrkspc_abc"],
  "retry_pending": false,
  "captures": [
    { "endpoint": "<row endpoint>", "file": "<file>", "status": "ok|failed|skipped", "note": null }
  ]
}
```

`retry_pending` is `true` only for the `KEY_INVALID_MID_RUN` exit described in
the Security Contract above (the key file survives that one exit); every
other manifest write — including the one below — sets it `false`.

Every attempted or deliberately skipped call gets an entry. If EVERY row
failed, delete `$MIGRATION_DIR/.anthropic-admin-env`, exit with no output,
and tell the user which scope is missing.

## Step 3: Parse Captures into the Usage Profile

Sum across the window (a throwaway extraction script if captures are large):

- **Usage** (`usage-messages.json`): per model — read `uncached_input_tokens`
  and `output_tokens` directly from each result row and write them to the
  profile's `input_tokens`/`output_tokens` fields (the API's own field is
  named `uncached_input_tokens`, not `input_tokens` — rename on write, do not
  invent an `input_tokens` field that doesn't exist in the response). Read
  `cache_read_input_tokens` directly into `cache_read_tokens`. Compute
  `cache_creation_tokens` as the SUM of `cache_creation.ephemeral_5m_input_tokens`
  and `cache_creation.ephemeral_1h_input_tokens` (two separate sub-fields on
  the response's nested `cache_creation` object — not a single top-level
  field). **These three token pools are mutually exclusive, not nested:**
  Anthropic's own contract is `total prompt tokens = uncached_input_tokens +
  cache_read_input_tokens + cache_creation_input_tokens` — unlike OpenRouter's
  `reasoning_tokens` (already included inside `completion_tokens`), a cache
  token is NEVER double-counted inside `uncached_input_tokens`. Also read
  `num_model_requests` if present in the response shape.
- **Cost** (`cost-report.json`, grouped by `description`, concatenated across
  the per-workspace calls from Step 2c): parse `model`/`inference_geo` out of
  each `description` row, and carry the `workspace_id` each row was tagged
  with during capture through to `costs_by_description[].workspace_id` — this
  is what lets a multi-workspace selection be broken back out per workspace
  instead of aggregating into one `description` bucket. Cost values are
  **decimal strings in cents** — convert to USD dollars (divide by 100, parse
  as decimal, do not treat as already-dollars float) before writing
  `monthly_cost_usd`. `monthly_cost_usd` = the last-30-days ACTUAL total —
  **never scale a partial window up to a month**. If the org's first
  non-zero bucket is < 30 days old, set `partial_window: true` and report the
  actual span in `active_days`.

- **`metadata.cost_status` — cost completeness, independent of `partial_window`.**
  `partial_window` only says whether the USAGE window itself is short; it says
  nothing about whether the dollar figure is known at all. `cost_status` is a
  separate enum covering that:
  - `"cost_unavailable"` — `cost_report` failed or was skipped (any row of the
    per-workspace loop in Step 2c), REGARDLESS of whether `usage_report/messages`
    succeeded fully or partially. Token volume is known; the dollar figure is
    NOT. Set `summary.monthly_cost_usd: null` in this case — **never `0` and
    never a stale/partial figure** — and record the failure in
    `metadata.capture_warnings` as today.
  - `"partial_window"` — `cost_report` succeeded, but the usage window itself is
    short (`partial_window: true`, existing meaning): the dollar figure is a
    real but short-span total, not a monthly baseline.
  - `"complete"` — `cost_report` succeeded AND the usage window is full
    (`partial_window: false`). `summary.monthly_cost_usd` is a normal monthly
    figure.
  Check `cost_report`'s own status first: a `cost_report` failure always sets
  `cost_status: "cost_unavailable"`, even on an otherwise full-window run — do
  not let a successful `usage_report/messages` call mask a failed cost call by
  reporting `partial_window: false` with a stale or zeroed dollar figure.

Write `$MIGRATION_DIR/anthropic-usage-profile.json`:

```json
{
  "metadata": {
    "report_date": "2026-08-21",
    "source": "anthropic_usage_api",
    "captured_at": "<from manifest>",
    "window_days": 30,
    "active_days": 30,
    "partial_window": false,
    "cost_status": "complete",
    "workspaces": [{ "id": "wrkspc_abc", "label": "production" }],
    "capture_warnings": ["cost-report.json failed (403)"]
  },
  "summary": {
    "monthly_cost_usd": 105.03,
    "currency": "USD",
    "models_seen": 3,
    "total_requests": 2856
  },
  "costs_by_description": [
    { "description": "claude-sonnet-5, workspace production", "model": "claude-sonnet-5", "inference_geo": "us", "workspace_id": "wrkspc_abc", "monthly_cost_usd": 41.61 }
  ],
  "usage_by_model": [
    {
      "model": "claude-sonnet-5",
      "input_tokens": 1300000,
      "output_tokens": 145000,
      "cache_read_tokens": 400000,
      "cache_creation_tokens": 20000,
      "num_model_requests": 452
    }
  ]
}
```

`usage_by_model` sorted descending by `input_tokens + cache_read_tokens +
cache_creation_tokens + output_tokens` (total volume, not just the uncached
portion — a prompt-cached model can rank far higher on total volume than its
`input_tokens` field alone would suggest). Include
only models with non-zero usage. `metadata.capture_warnings` carries every
`failed`/`skipped` manifest entry (empty array when all rows succeeded) — the
same convention as the other usage profiles — so downstream phases can tell a
failed usage category (UNKNOWN volume) from a genuinely unused one (zero).
Validate: valid JSON, `summary.monthly_cost_usd` approximately equals the sum
of `costs_by_description[].monthly_cost_usd` (± rounding).

## Step 4: Merge into the AI Workload Profile (if it exists), Then Clean Up

If `$MIGRATION_DIR/ai-workload-profile.json` exists (from app-code or live `az`
discovery), update it — the API data is authoritative for Anthropic spend and
volume:

1. `metadata.sources_analyzed.anthropic_usage_api` = `true`.
2. `current_costs` — provider-aware merge. The API measures **Anthropic**
   spend; an Azure Cost Management export measures **Azure** spend (including
   Azure OpenAI). They are different providers, so never pick one with max():
   - **No existing `current_costs`** → set
     `{ "monthly_ai_spend": <summary.monthly_cost_usd>, "services_detected":
     ["Anthropic Claude API"], "source": "anthropic_usage_api" }`.
   - **Existing Azure-Cost-Management costs for a DIFFERENT provider** (e.g.
     `ai_source` is `both`, the export captured Azure OpenAI spend) → SUM the
     providers: `monthly_ai_spend` = Anthropic + Azure (+ any other provider
     already present), `source: "mixed"`, and record the per-provider split
     in `breakdown[]`:
     `{ "provider": "anthropic", "monthly_spend": X, "source": "anthropic_usage_api" }`
     alongside the other providers' existing entries.
   - **Existing costs for the SAME provider** (an export that already
     contains Anthropic spend, same window) → the API wins (`source:
     "anthropic_usage_api"`); move the displaced figure into
     `current_costs.conflicting_sources[]` — never silently resolved, same
     rule as the other usage-API sources.
3. Append to `detection_signals[]`:
   `{ "method": "anthropic_usage_api", "pattern": "billed usage for <model>",
   "confidence": 0.99, "evidence": "<N> requests, <X> tokens in last 30d" }`
   for each of the top 5 models by usage.
4. **These are two INDEPENDENT checks over every `usage_by_model` entry — run
   both:**

   a. **Model row:** for any `usage_by_model` model absent from `models[]`,
      append `{ "model_id": "<model>", "service": "anthropic_api",
      "detected_via": ["usage_api"], "evidence": [{ "source": "usage_api",
      "pattern": "billed usage in last 30 days" }], "capabilities_used":
      ["text_generation"], "usage_context": "Observed in Anthropic usage
      data — call sites not yet located in code" }` (Anthropic's Messages API
      is text/multimodal generation only — no embeddings/image/audio endpoint
      types to branch on, so this is always `text_generation`). Code-derived
      entries always win on conflict; usage-only entries tell Clarify what
      code analysis missed.
   b. **Workload row:** for any `usage_by_model` model with NO `workloads[]`
      entry whose `model_id` matches it (any `sdk_method`) — append
      `{workload_id: "wl_" + sha256(model_id + "|usage_api|plain")[:6],
      model_id: "<model>", sdk_method: "usage_api", capability:
      "text_generation", capability_confidence: "low", structured_output:
      false, call_sites: [{"file": "<usage_api>", "line": 0}]}` (per
      `schema-discover-ai.md` § workloads[] "Usage-only workloads"). Without
      this, the model can exist in `models[]` with no corresponding
      `workloads[]` entry — Clarify's multi-workload confirmation table and
      Design's per-workload iteration both read `workloads[]`, not
      `models[]`. Before appending, confirm no existing `workloads[]` entry
      already has this exact `workload_id` (the sha256 is deterministic per
      model, so a second merge of the same model naturally collides on it
      instead of duplicating).

   Recompute `summary.total_models_detected` to include any (a) addition.
5. If `summary.ai_source` is `"azure_openai"` or `"openai"` and Anthropic
   usage was found, set it to `"both"` (azure has no `gemini` value; the
   schema's `ai_source` enum is `azure_openai|openai|anthropic|both|other`).

If `ai-workload-profile.json` does NOT exist, Clarify and Estimate read
`anthropic-usage-profile.json` directly for spend and volumes — but it is a
supplement, not an anchor: the run still needs at least one primary artifact
(resource inventory, AI workload profile, or live-capture manifest) to pass
the Discover handoff gate.

**Clean up (default, not optional):** delete
`$MIGRATION_DIR/.anthropic-admin-env` now — the key is no longer needed. Tell
the user it was deleted and that they can also rotate the Admin key at the
Anthropic Console if it was created just for this run.

Report: "Anthropic usage discovery: $X/month across N models (workspaces:
[selected ids]; window: 30 days[, partial: only M active days])."

The parent `discover.md` owns the phase status update — do not touch
`.phase-status.json` here.

---

## Error Handling

| Error | Behavior |
|---|---|
| curl / script runtime missing, or user skips | Exit cleanly with no output (orchestrator falls back to billing files) |
| 401 on probe | Not an Admin key — offer re-intake or skip |
| Probe fails in an Enterprise-org-shaped way | Tell the user Enterprise Analytics API is not yet implemented in this flow; delete the key file (`retry_pending: false`); exit cleanly |
| 401 mid-capture (probe succeeded, key then revoked/rotated) | Script aborts remaining calls, keeping completed files. Tell the user the key stopped working mid-run; offer Step 1 re-intake or skip. `KEY_INVALID_MID_RUN`: write `retry_pending: true` and keep the key file (the ONE exit that does). On resume, re-run Step 2 — captures overwrite; once the retry succeeds or is abandoned, delete the key file and set `retry_pending: false` |
| 429 rate limit | Wait 30s, retry once; second 429 → record `failed`, continue |
| Individual endpoint fails | Record `failed`/`skipped` in manifest, continue — zero usage on an endpoint is normal, never a halt |
| `cost_report` fails or is skipped (any per-workspace row in Step 2c), `usage_report/messages` succeeds (fully or partially) | Still write the profile — usage/token volume is known. Set `metadata.cost_status: "cost_unavailable"` and `summary.monthly_cost_usd: null` (never `0`, never a stale figure) regardless of `partial_window`'s value |
| Both endpoints failed | Delete the key file (`retry_pending: false`); exit with no output; tell the user which scope is missing |
| Selected workspaces have zero usage in the window | Re-show the per-workspace spend list from 2b and let the user re-select once; still zero → write the profile with zeros and `partial_window: true` |
| All buckets zero (new org, no usage yet) | Write the profile with zeros and `partial_window: true`; warn that Estimate will fall back to token-volume tiers |

**Key principle:** partial results are better than no results. Record what failed;
never fabricate what wasn't captured.

## Scope Boundary

**This fragment covers Anthropic usage capture ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or equivalents
- Migration strategies, phases, timelines, cost estimates, or effort estimates
- Any non-GET request, any endpoint not listed in Step 2, any Admin,
  Compliance, Spend Limits, or Rate Limits management endpoint — even though
  the same Admin key can technically call them
- Any per-key, per-user, or per-account grouping
- Unscoped org-wide capture — every Step 2c call carries the user's
  `workspace_ids[]` selection
- Claude Enterprise (claude.ai) Analytics API calls — out of scope for v1
- The Admin key value anywhere outside `.anthropic-admin-env` (no echoes, no
  command args, no artifacts, no context) — and that file is deleted in Step 4

**Your ONLY job: capture what this app spent and used on Anthropic. Nothing else.**
