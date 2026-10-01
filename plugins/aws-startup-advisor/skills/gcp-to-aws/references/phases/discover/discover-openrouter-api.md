# Discover Phase: OpenRouter Usage API Discovery

> Self-contained OpenRouter usage discovery sub-file. Captures real cost and
> token-usage data directly from the OpenRouter API — read-only, consent-gated,
> aggregate per-model/per-day counts only — as an alternative to the user
> exporting usage by hand. Produces `openrouter-usage-profile.json` and, when
> `ai-workload-profile.json` exists, fills its `current_costs` section with real
> spend. If the user declines consent or has no OpenRouter key, exits cleanly
> with no output.
>
> **Why this matters for a Bedrock migration.** OpenRouter is a multi-provider
> router: the app-code scan (`discover-app-code.md`) detects the OpenRouter
> transport (`gateway_type: llm_router`) but often cannot tell WHICH models
> actually carry the spend. `/activity` reports it directly — per model, per day,
> with token counts and dollar cost — so Estimate can size the Bedrock target
> against real volume instead of guessing.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Security Contract (applies to every step)

1. **Exact-endpoint allowlist, GET only.** Call ONLY the endpoints in the Step 2
   Capture Endpoint Table. All are `GET` against `https://openrouter.ai/api/v1`.
   Never any other endpoint, never any other HTTP method, never a chat/completion
   or `/generation` call (those run inference and can return prompt/response
   content — this flow reads aggregate usage only), never a key-management
   endpoint.
2. **The OpenRouter key must never enter this conversation (HARD RULE).** Do not
   ask the user to paste the key in chat, and never echo, cat, or interpolate its
   VALUE into any command, question, or output — the agent only ever handles the
   file path `$MIGRATION_DIR/.openrouter-key-env` (`chmod 600`, inside the
   gitignored `.migration/` tree). If the user pastes a key into the chat
   unprompted, do not use it: tell them it is now part of the transcript,
   recommend rotating it at openrouter.ai/keys, and continue with the Step 1
   intake paths. All API calls go through a throwaway capture script that reads
   the key from the file. Only a sha256 fingerprint of the file appears in the
   manifest, and the key file is **deleted by default** when capture completes
   (Step 4).
3. **Aggregate data only.** `/activity` returns per-day, per-model bucketed token
   counts and cost — no prompts, no completions, no request content. Do NOT pass
   `group_by=workspace` unless the user explicitly asks to scope to one workspace
   (it splits the response per workspace but adds no content); model-level
   granularity is all downstream phases need.
4. **Capture to files, not context.** The capture script writes responses under
   `$MIGRATION_DIR/openrouter-capture/`. Parse capture files with a throwaway
   extraction script if any exceeds ~500 rows — do NOT Read oversized raw
   captures into context.
5. **Consent first.** Nothing data-touching happens before the user answers
   `[A]` in Step 0 — no key intake, no key file on disk, no API call. The Step 0
   consent is THE consent gate for this source (the orchestrator only decides
   whether to load this file).

---

## Step 0: Consent Gate

Output exactly, then wait for the user's choice:

```
─── OpenRouter Usage Discovery (read-only) ───

I can pull your OpenRouter cost and per-model usage directly from the
OpenRouter API. This runs GET requests only, against a fixed list of
usage/credits endpoints:

  ✓ Captured: daily usage per model — request counts, prompt /
    completion / reasoning token counts, and dollar cost — plus your
    credits purchased/used total.
  ✗ Never captured: prompts or completions content, API keys, or
    anything from a chat/generation endpoint. No request that creates,
    changes, or deletes anything will run.

Window: last 30 days. You'll need an OpenRouter PROVISIONING (management)
key — a plain inference key cannot read account usage. Create one at
openrouter.ai/settings/provisioning-keys. (The key is written to a
chmod-600 file inside the gitignored .migration/ directory, never echoed,
and deleted when capture completes.)

[A] Proceed with OpenRouter usage discovery
[B] Skip — use the code scan / exported usage files only
```

- **[A]** → continue to Step 1.
- **[B]** → exit cleanly with no output (record the decline for the orchestrator).

## Step 1: Key Intake and Preflight

1. **Runtime available:** `curl --version` (first line) and `python3 --version`
   (fall back to `python`, then `node`). If curl AND all script runtimes are
   missing → tell the user and exit cleanly.
2. **Explain the key requirement** (before asking for anything):
   "OpenRouter usage discovery needs a **provisioning key** (also called a
   management key) — a regular inference key (`sk-or-v1-...`) cannot read account
   usage or credits. Create one at openrouter.ai/settings/provisioning-keys.
   It is read-only for this flow — I only call GET usage/credits endpoints."
3. **Check the environment first** (presence only, never the value):

   ```bash
   [ -n "$(printenv OPENROUTER_PROVISIONING_KEY)" ] && echo ENV_KEY_PRESENT || echo ENV_KEY_ABSENT
   ```

4. **Key intake.** Ask: "How would you like to provide the provisioning key?"
   (offer `[A]` only on `ENV_KEY_PRESENT`):
   - **[A] Use the `OPENROUTER_PROVISIONING_KEY` already in my environment** →
     materialize env var to file in one command — the value never appears in the
     transcript:

     ```bash
     printf 'OPENROUTER_PROVISIONING_KEY=%s\n' "$(printenv OPENROUTER_PROVISIONING_KEY)" > "$MIGRATION_DIR/.openrouter-key-env" && chmod 600 "$MIGRATION_DIR/.openrouter-key-env"
     ```

   - **[B] I'll write it to a file myself** → give the user this command to run in
     THEIR OWN terminal (not through the agent) — `read -rs` collects the key
     without echoing it:

     ```bash
     read -rs k && printf 'OPENROUTER_PROVISIONING_KEY=%s\n' "$k" > "<MIGRATION_DIR>/.openrouter-key-env" && chmod 600 "<MIGRATION_DIR>/.openrouter-key-env" && unset k
     ```

     Substitute the literal run-directory path when presenting it (the path is not
     a secret). Continue when the user says it's done.
   - **[C] Skip OpenRouter usage discovery** → exit cleanly with no output.
5. **Format check** (never prints the key) — a provisioning key is non-empty and
   is NOT a bare inference key; reject an obviously-wrong value early:

   ```bash
   grep -qE '^OPENROUTER_PROVISIONING_KEY=.+' "$MIGRATION_DIR/.openrouter-key-env" && echo KEY_FORMAT_OK || echo KEY_FORMAT_BAD
   ```

   On `KEY_FORMAT_BAD`: tell the user the file is empty / malformed and re-run
   intake (do not echo file contents). If the probe in Step 2 later returns 401,
   surface that the key is likely an inference key, not a provisioning key.

**IMPORTANT:** Do NOT rely on the environment variable during capture — env vars
do not persist across Bash tool calls. The capture script reads the file path
above.

## Step 2: Capture

Create `$MIGRATION_DIR/openrouter-capture/`.

**2a. Write the capture script** to `$MIGRATION_DIR/_capture_openrouter.py` (or
`.js` — whatever runtime Step 1 found). The script (and nothing else) touches the
key:

- Reads `OPENROUTER_PROVISIONING_KEY` from `$MIGRATION_DIR/.openrouter-key-env`.
- Sends `Authorization: Bearer <key>` on every request. Never prints the key or
  the header; on HTTP errors it prints ONLY the status code and the response
  `error.message`.
- For `/activity`, requests the last 30 days (the endpoint returns daily rows;
  filter/keep rows whose `date` is within the window).
- A non-200 on one endpoint records `failed` for that row and continues — a
  missing endpoint or zero usage is normal, never a halt. **Exception: a 401 OR
  403 on the FIRST (probe) call** means the key is not a management/provisioning
  key (OpenRouter returns **403 "Only management keys can perform this
  operation"** for an inference key, and 401 for a revoked/invalid key) — abort
  before writing anything, print a distinct `KEY_INVALID` line, and do **not**
  write the manifest (see 2b). A written manifest tells the Discover route gate a
  capture completed; writing one after an auth failure would halt the whole phase
  on a missing profile.
- Prints one line per call: `<file> ok|failed|skipped <n_rows>`.

**2b. Probe.** The capture script runs the probe call first (2a rules apply — the
agent never invokes curl with the key itself):

```
GET https://openrouter.ai/api/v1/credits  →  credits.json
```

- On **401 or 403**: stop, write NO manifest and NO capture files, **delete
  `$MIGRATION_DIR/.openrouter-key-env` now** (this key was just proven invalid or
  wrong-type — do not leave a rejected key file on disk waiting for a later
  cleanup step this path never reaches), and tell the
  user: "The key was rejected (`<status>`). Confirm it is a **provisioning /
  management** key (openrouter.ai/settings/provisioning-keys), not a plain
  inference key — inference keys return 403 and cannot read account usage."
  Offer to re-run Step 1 intake or skip. On 429, wait 30 seconds and retry once.
- On success: continue to the capture table (the manifest is written in 2d, only
  after the probe authenticates).

**2c. Capture Endpoint Table.** Every row is `GET` against
`https://openrouter.ai/api/v1`.

| # | Endpoint (GET)  | Purpose                                                                                                  | Output file     |
| - | --------------- | -------------------------------------------------------------------------------------------------------- | --------------- |
| 1 | `/credits`      | `total_credits` purchased and `total_usage` used (account lifetime) — a spend sanity anchor              | `credits.json`  |
| 2 | `/activity`     | daily rows: `date`, `model`, `model_permaslug`, `provider_name`, `requests`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `usage` (USD) — the workhorse | `activity.json` |
| 3 | `/key`          | rate-limit + remaining credit on the calling key (context only; optional — record `skipped` on any error)| `key.json`      |

**Notes:**

- Row 2 `/activity` is the one that matters — its per-`date`/per-`model` rows,
  summed over the window, are the spend + volume signal. `model` is
  OpenRouter-namespaced (`openai/gpt-4.1`, `anthropic/claude-...`); keep it verbatim
  — Design maps the namespaced id to a Bedrock target the same way the app-code
  `llm_router` path does.
- Do NOT pass `group_by=workspace` (Security Contract rule 3) unless the user asks
  to scope to one workspace.

**2d. Run the script, then delete it.** Record results in
`$MIGRATION_DIR/openrouter-capture/manifest.json`:

```json
{
  "captured_at": "<ISO 8601 UTC>",
  "window_days": 30,
  "provisioning_key_sha256": "<sha256 of .openrouter-key-env contents — fingerprint only>",
  "captures": [
    { "endpoint": "<row endpoint>", "file": "<file>", "status": "ok|failed|skipped", "note": null }
  ]
}
```

Every attempted or deliberately skipped call gets an entry. **`/activity`'s
`status` is special — unlike `/key` (optional context, `skipped` is harmless),
`/activity` is the ONLY source of per-model rows, so its status determines
whether this source produces anything at all:**

**If the `/activity` row's status is `failed`** (a mid-table failure, e.g. a
500 — distinct from the 401/403 probe failure above, which never reaches this
step): still write the manifest as shown (so a resumed run can tell what was
already tried), but do **not** proceed to Step 3, and do **not** delete the key
file yet — the key is still valid (the probe succeeded), and a resumed run
needs it to retry. Tell the user: "OpenRouter usage discovery captured credits
but the usage endpoint (`/activity`) failed (`<note>`) — no per-model signal to
build a profile from. I'll retry it if you ask me to continue OpenRouter
discovery again, or you can skip it for this run."

**If the user chooses to skip** (either right after this failure, or on a
later resume): update the `/activity` entry's `status` to `skipped` in the
existing manifest. This is a **terminal, omitted-source outcome, not an
alternate path into Step 3** — there is no `activity.json` to parse, so nothing
downstream of here runs: do not execute Step 3, do not write
`openrouter-usage-profile.json`, and do not touch `ai-workload-profile.json`.
Delete the key file (per Step 4's cleanup) since capture is now finished for
this run. Tell the user OpenRouter usage discovery was skipped for this run and
no profile was produced — a later resume must not retry it or re-ask for
consent (the manifest's `skipped` status is what records that this was a
deliberate choice, not an unattempted capture).

**A subsequent invocation of this file MUST check for these specific outcomes,
not just manifest presence:** read the existing manifest first.

- `/activity` entry's `status` is `failed` → retry ONLY that row (reusing the
  existing key file and the other rows' already-good captures rather than
  re-running Step 0–2b from scratch), update its entry to `ok`/`failed` in
  place, and only then either proceed to Step 3 (on `ok`) or repeat this same
  stop-and-offer-retry behavior (on another `failed`), or record `skipped` and
  stop per the paragraph above (if the user now chooses to abandon it).
- `/activity` entry's `status` is `skipped` → this run already made its
  decision; exit cleanly with no output and no re-ask, exactly like a Step 1
  consent decline. Do NOT proceed to Step 3 — there is still no `activity.json`.
- `/activity` entry's `status` is `ok` → proceed to Step 3 as normal (the only
  status where a real capture exists to parse).

Delete the key file once `/activity` reaches a terminal `ok`/`skipped` state
(per Step 4's cleanup) — never while a retry is still live (a `failed` status
with no user decision yet).

## Step 3: Parse Captures into the Usage Profile

Sum across the window (a throwaway extraction script if captures are large):

Both OpenRouter responses wrap their payload in a top-level `data` key — **unwrap
`data` before reading anything below.** `/activity` returns
`{ "data": [ { "date", "model", "usage", ... } ] }` (an array under `data`);
`/credits` returns `{ "data": { "total_credits", "total_usage" } }` (an object under
`data`). Reading the response body's top level directly yields nothing and would
produce a profile of zeros that still (wrongly) passes the `monthly_cost_usd == sum
of rows` self-check.

- **Activity** (`activity.json`): group the rows in `data[]` by `model`; per model
  sum `requests`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, and
  `usage` (USD). `monthly_cost_usd` = the sum of `usage` over the window —
  **never scale a partial window up to a month**. If the first non-zero `date` is
  < 30 days old, set `partial_window: true` and report the actual span in
  `active_days`.
- **Credits** (`credits.json`): read `data.total_credits` / `data.total_usage`
  (lifetime figures) — record them as context, NOT as the monthly baseline (the
  monthly figure comes from `/activity` summed over the window).
- **Stale-lifetime-usage check (live-verified — this happens on a real account,
  not a hypothetical edge case).** If `data[]` is EMPTY (zero `/activity` rows —
  `active_days: 0`) but `credits.data.total_usage > 0`: the account has genuine
  historical spend that predates the 30-day window (or predates this
  provisioning key). Do **not** let this read as "confirmed zero spend" — that
  is a different, stronger claim than "no spend in the last 30 days," and the
  two are not distinguishable from `monthly_cost_usd: 0` alone. Append to
  `metadata.capture_warnings`: `"activity empty but credits.total_usage is
  $<total_usage> lifetime — spend exists outside the 30-day window; per-model
  attribution unavailable"`. `summary.monthly_cost_usd` still correctly reports
  `0` (that IS the accurate figure for the last 30 days — do not backfill it
  from the lifetime total, which has no per-model breakdown to attribute), but
  the warning is what tells a reader "$0 last 30 days" is not the same fact as
  "$0 ever."

Write `$MIGRATION_DIR/openrouter-usage-profile.json`:

```json
{
  "metadata": {
    "report_date": "2026-08-21",
    "source": "openrouter_usage_api",
    "captured_at": "<from manifest>",
    "window_days": 30,
    "active_days": 30,
    "partial_window": false,
    "credits_lifetime": { "total_credits": 100.5, "total_usage": 25.75 },
    "capture_warnings": ["key.json skipped (403)"]
  },
  "summary": {
    "monthly_cost_usd": 105.03,
    "currency": "USD",
    "models_seen": 5,
    "total_requests": 2856
  },
  "usage_by_model": [
    {
      "model": "openai/gpt-4.1",
      "provider_name": "OpenAI",
      "requests": 452,
      "prompt_tokens": 1300000,
      "completion_tokens": 145000,
      "reasoning_tokens": 0,
      "monthly_cost_usd": 41.61
    }
  ]
}
```

`usage_by_model` sorted descending by `prompt_tokens + completion_tokens`.
Include only models with non-zero usage. `metadata.capture_warnings` carries every
`failed`/`skipped` manifest entry (empty array when all rows succeeded) — the same
convention as the OpenAI usage path — so downstream phases can tell a failed
capture (UNKNOWN volume) from a genuinely unused one (zero). Validate: valid JSON,
`summary.monthly_cost_usd` equals the sum of `usage_by_model[].monthly_cost_usd`
(± rounding).

## Step 4: Merge into the AI Workload Profile (if it exists), Then Clean Up

If `$MIGRATION_DIR/ai-workload-profile.json` exists (from app-code or IaC
discovery), update it — the API data is authoritative for OpenRouter spend and
volume:

1. `metadata.sources_analyzed.openrouter_usage_api` = `true`.
2. `current_costs` — provider-aware merge, the same rule as the OpenAI usage path:
   - **No existing `current_costs`** → set
     `{ "monthly_ai_spend": <summary.monthly_cost_usd>, "services_detected":
     ["OpenRouter"], "source": "openrouter_usage_api" }`.
   - **Existing costs for a DIFFERENT provider** (e.g. a billing CSV captured
     Vertex spend, or the OpenAI usage path captured OpenAI-direct spend) → SUM
     the providers: `source: "mixed"`, and record the per-provider split in
     `breakdown[]` (`{ "provider": "openrouter", "monthly_spend": X, "source":
     "openrouter_usage_api" }`, plus the other provider's entry). OpenRouter is a
     router — its spend already includes the upstream providers it fronts, so do
     NOT also add a separate "openai via openrouter" line; that would double-count.
   - **Existing costs from the SAME source window** → the API wins
     (`source: "openrouter_usage_api"`); move the displaced figure into
     `current_costs.conflicting_sources[]` — never silently resolved.
3. Append to `detection_signals[]`:
   `{ "method": "openrouter_usage_api", "pattern": "billed usage for <model>",
   "confidence": 0.99, "evidence": "<N> requests, <X> tokens in last 30d" }` for
   each of the top 5 models by usage. (`openrouter_usage_api` is a live-usage
   detection method, parallel to `openai_usage_api`.)
4. **These are two INDEPENDENT checks over every `usage_by_model` entry — run
   both, even for a model that already satisfies one of them (e.g. from an
   earlier run against a saved/retained `ai-workload-profile.json`).** Checking
   workload presence only when the model was ALSO just added to `models[]`
   misses the case where a prior run (or a resumed one reusing an existing
   profile) already inserted the model row without its workload row, or where
   a resume merges a retained profile that already has the model from a
   DIFFERENT capture pass.

   a. **Model row:** for any `usage_by_model` model absent from `models[]`,
      append `{ "model_id": "<model>", "service": "openrouter_api",
      "detected_via": ["usage_api"], "evidence": [{ "source": "usage_api",
      "pattern": "billed usage in last 30 days" }], "capabilities_used":
      ["text_generation"], "usage_context": "Observed in OpenRouter usage data —
      call sites not yet located in code" }`. Code-derived entries always win on
      conflict; usage-only entries tell Clarify what the code scan missed (a
      model routed at runtime but not literal in the source).
   b. **Workload row:** for any `usage_by_model` model with NO `workloads[]`
      entry whose `model_id` matches it AND `sdk_method: "usage_api"` — checked
      by model identity alone, regardless of whether step (a) just inserted its
      `models[]` row this pass or the row was already present from before —
      append `{workload_id: "wl_" + sha256(model_id + "|usage_api|plain")[:6],
      model_id: "<model>", sdk_method: "usage_api", capability:
      "text_generation", capability_confidence: "low", structured_output: false,
      call_sites: [{"file": "<usage_api>", "line": 0}]}` (per
      `schema-discover-ai.md` § workloads[] "Usage-only workloads"). Without
      this, the model can exist in `models[]` with no corresponding
      `workloads[]` entry — Clarify's multi-workload confirmation table and
      Design's per-workload iteration both read `workloads[]`, not `models[]`,
      so a usage-only model present only in `models[]` is never surfaced for
      confirmation and never gets a `design_block`. Before appending, confirm no
      existing `workloads[]` entry already has this exact `workload_id` (the
      sha256 is deterministic per model, so a second merge of the same model
      naturally collides on it instead of duplicating).

   Recompute `summary.total_models_detected` to include any (a) addition (it
   counts `models[]` length, not just code-derived models).
5. If `summary.ai_source` does not already reflect the OpenRouter-fronted
   providers, leave it as the code scan set it — OpenRouter is a transport, and
   `ai_source` is about the source SDK/provider family, which the code scan owns.

If `ai-workload-profile.json` does NOT exist, Clarify and Estimate read
`openrouter-usage-profile.json` directly for spend and volumes — but it is a
**supplement, not an anchor**: the run still needs at least one primary artifact
(resource inventory, AI workload profile, or billing profile) to pass the Discover
handoff gate.

**Clean up (default, not optional):** delete
`$MIGRATION_DIR/.openrouter-key-env` now — the key is no longer needed. (This is
the happy-path cleanup point; a 401/403 on the probe deletes it immediately at
that point instead, per Step 2b, since a rejected key has nothing left to
retry.) Tell the
user it was deleted and that they can also revoke the provisioning key at
openrouter.ai/settings/provisioning-keys if it was created just for this run.

Report: "OpenRouter usage discovery: $X/month across N models (window: 30
days[, partial: only M active days])." If `metadata.capture_warnings` is
non-empty (including the stale-lifetime-usage case above), append it plainly —
e.g. "Note: no billed usage in the last 30 days, but your account shows
$<total_usage> in lifetime usage — that spend falls outside this window and
isn't reflected in the figure above." Do NOT let a `$0/month` report stand
unqualified when a capture warning says otherwise; the warning is what
distinguishes "confirmed no recent spend" from "confirmed no recent spend, but
real spend exists we can't attribute to a model."

The parent `discover.md` owns the phase status update — do not touch
`.phase-status.json` here.

## Scope Boundary

**This fragment covers OpenRouter usage capture ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or Bedrock equivalents
- Migration strategies, phases, timelines, cost estimates, or effort estimates
- Any chat/completion/`/generation` call, any non-GET method, or any key printing
- Prompt or completion CONTENT anywhere

**Your ONLY job: capture aggregate OpenRouter usage. Nothing else.**
