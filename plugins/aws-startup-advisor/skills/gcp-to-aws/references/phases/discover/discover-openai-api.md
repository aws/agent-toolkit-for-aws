# Discover Phase: OpenAI Usage API Discovery

> Self-contained OpenAI usage discovery sub-file. Captures real cost and
> token-usage data directly from the OpenAI Admin API — read-only, consent-gated,
> aggregate counts only, scoped to the OpenAI projects the user selects — as an
> alternative to the user exporting billing CSVs by hand. Produces
> `openai-usage-profile.json` and, when `ai-workload-profile.json` exists, fills
> its `current_costs` section with real spend. If the user declines consent or
> has no Admin API key, exits cleanly with no output.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Security Contract (applies to every step)

1. **Exact-endpoint allowlist, GET only.** Call ONLY the endpoints in the Step 2
   Capture Endpoint Table. All are `GET` against `https://api.openai.com`. Never
   any other endpoint, never any other HTTP method, never management endpoints
   (`/v1/organization/projects`, users, API keys — those need
   `api.management.read`, which this flow deliberately does not request), never
   endpoints that return request/response content.
2. **The Admin key must never enter this conversation (HARD RULE).** Do not ask
   the user to paste the key in chat, and never echo, cat, or interpolate its
   VALUE into any command, question, or output — the agent only ever handles the
   file path `$MIGRATION_DIR/.openai-admin-env` (`chmod 600`, inside the
   gitignored `.migration/` tree). If the user pastes a key into the chat
   unprompted, do not use it: tell them it is now part of the transcript,
   recommend rotating it, and continue with the Step 1 intake paths. All API
   calls go through a throwaway capture script that reads the key from the
   file. Only a sha256 fingerprint of the file appears in the manifest, and the
   key file is **deleted by default** when capture completes (Step 4).
3. **Scoped, aggregate data only.** The usage endpoints return bucketed token
   counts and cost amounts — no prompts, no completions, no file contents.
   Captures are filtered to the OpenAI projects the user selects in Step 2b —
   never attribute whole-org spend to this application. Do not add
   `group_by=user_id` or `group_by=api_key_id` to any call: model-level
   granularity is all downstream phases need.
4. **Capture to files, not context.** The capture script writes responses under
   `$MIGRATION_DIR/openai-capture/`. Parse capture files with a throwaway
   extraction script if any exceeds ~500 buckets — do NOT Read oversized raw
   captures into context.
5. **Consent first.** Nothing data-touching happens before the user answers
   `[A]` in Step 0 — no key intake, no key file on disk, no API call. The
   Step 0 consent is THE consent gate for this source (the orchestrator's 1e
   check only decides whether to load this file).

---

## Step 0: Consent Gate

Output exactly, then wait for the user's choice:

```
─── OpenAI Usage Discovery (read-only) ───

I can pull your organization's OpenAI cost and usage data directly
from the OpenAI Admin API. This runs GET requests only, against a
fixed list of usage/cost endpoints:

  ✓ Captured: daily cost totals by line item and project, token
    counts per model (completions, embeddings, images, audio), and
    request counts — scoped to the OpenAI project(s) YOU select as
    belonging to this application.
  ✗ Never captured: prompts or completions content, uploaded
    files, API keys, org members, per-user/per-key attribution, or
    data from projects you don't select. No management endpoints.
    No request that creates, changes, or deletes anything will run.

Window: last 30 days. You'll need an OpenAI ADMIN API key with
Usage set to Read (I'll walk you through it — the key
is written to a chmod-600 file inside the gitignored .migration/
directory, never echoed, and deleted when capture completes).

[A] Proceed with OpenAI usage discovery
[B] Skip — use exported billing files only (or none)
```

- **[A]** → continue to Step 1.
- **[B]** → exit cleanly with no output (record the decline for the orchestrator).

## Step 1: Key Intake and Preflight

1. **Runtime available:** `curl --version` (first line) and `python3 --version`
   (fall back to `python`, then `node`). If curl AND all script runtimes are
   missing → tell the user and exit cleanly.
2. **Explain the key requirement** (before asking for anything):
   "OpenAI usage discovery needs an **Admin API key** (`sk-admin-...`) — regular
   project keys (`sk-proj-...`) cannot read org usage. Create one at
   platform.openai.com → Settings → Organization → Admin keys. In the key
   permissions, set **Usage** to **Read** and leave every other permission
   off. (The API reports that as `api.usage.read` — you will not see that
   string in the UI.)"
3. **Check the environment first** (presence only, never the value):

   ```bash
   [ -n "$(printenv OPENAI_ADMIN_KEY)" ] && echo ENV_KEY_PRESENT || echo ENV_KEY_ABSENT
   ```

4. **Key intake.** Ask: "How would you like to provide the Admin key?" (offer
   `[A]` only on `ENV_KEY_PRESENT`):
   - **[A] Use the `OPENAI_ADMIN_KEY` already in my environment** → materialize
     env var to file in one command — the value never appears in the transcript:

     ```bash
     printf 'OPENAI_ADMIN_KEY=%s\n' "$(printenv OPENAI_ADMIN_KEY)" > "$MIGRATION_DIR/.openai-admin-env" && chmod 600 "$MIGRATION_DIR/.openai-admin-env"
     ```

   - **[B] I'll write it to a file myself** → give the user this command to run
     in THEIR OWN terminal (not through the agent) — `read -rs` collects the key
     without echoing it:

     ```bash
     read -rs k && printf 'OPENAI_ADMIN_KEY=%s\n' "$k" > "<MIGRATION_DIR>/.openai-admin-env" && chmod 600 "<MIGRATION_DIR>/.openai-admin-env" && unset k
     ```

     Substitute the literal run-directory path when presenting it (the path is
     not a secret). Continue when the user says it's done.
   - **[C] Skip OpenAI usage discovery** → exit cleanly with no output.
5. **Format check** (never prints the key) — Admin keys are `sk-admin-...`;
   rejecting other prefixes catches a pasted project key early:

   ```bash
   grep -qE '^OPENAI_ADMIN_KEY=sk-admin-.+' "$MIGRATION_DIR/.openai-admin-env" && echo KEY_FORMAT_OK || echo KEY_FORMAT_BAD
   ```

   On `KEY_FORMAT_BAD`: tell the user the file does not contain an Admin key
   (`sk-admin-...`) and re-run intake (do not echo file contents).

**IMPORTANT:** Do NOT rely on the environment variable during capture — env vars
do not persist across Bash tool calls. The capture script reads the file path
above.

## Step 2: Capture

Create `$MIGRATION_DIR/openai-capture/`.

**2a. Write the capture script** to `$MIGRATION_DIR/_capture_openai.py` (or `.js`
— whatever runtime Step 1 found). The script (and nothing else) touches the key:

- Reads `OPENAI_ADMIN_KEY` from `$MIGRATION_DIR/.openai-admin-env`.
- Sends `Authorization: Bearer <key>` on every request. Never prints the key or
  the header; on HTTP errors it prints ONLY the status code and the response
  `error.message`.
- Computes `start_time` = now − 30 days (Unix seconds).
- For each requested call: follows pagination (`has_more` / `next_page` cursor)
  until exhausted, concatenates all pages' `data` arrays, and writes the result
  to the named file.
- A non-200 on one endpoint records `failed` for that row and continues —
  a missing endpoint or zero usage is normal, never a halt. **Exception: a 401
  AFTER the probe succeeded** means the key was revoked or rotated mid-run —
  abort the remaining calls (keep completed capture files) and exit with a
  distinct `KEY_INVALID_MID_RUN` line so the agent can hand off.
- Prints one line per call: `<file> ok|failed|skipped <n_buckets>`.

**2b. Probe and project scoping.** The capture script runs the probe call first
(2a rules apply — the agent never invokes curl with the key itself):

```
GET /v1/organization/costs?start_time=<t>&bucket_width=1d&group_by=project_id&limit=180  →  costs-by-project.json
```

- On 401: stop and tell the user: "The key was rejected. Confirm it is an
  **Admin** key (`sk-admin-...`) with **Usage** set to **Read** — project keys
  cannot read org usage." Offer to re-run Step 1 intake or skip. On 429, wait
  30 seconds and retry once.
- On success: sum spend per `project_id` and present the list (project id +
  window spend, sorted descending). Then ask: "Which of these OpenAI projects
  belong to THIS application? (The Admin API exposes project IDs, not names —
  check platform.openai.com → Settings → Projects to match IDs if unsure.)
  List the IDs, or answer `all` only if this org serves just this app." Set
  `$PROJECT_IDS` to the selection. **Never default to `all`** — org-wide spend
  attributed to one app corrupts the migrate-or-stay numbers downstream. The
  user may also give each selected ID a label (e.g. "proj_abc = production");
  record labels in the profile.
- **Confirm before capture** (applies equally when the answer was `all`):
  "Selected projects account for $X of $Y total org spend in this window.
  Capture these? [Y] Proceed / [N] Re-select". On [N], re-show the list once.

**2c. Capture Endpoint Table.** Every row is filtered to the selected projects
via repeated `project_ids[]=<id>` query parameters.

| # | Endpoint (GET, `https://api.openai.com`)      | Query parameters                                                                     | Output file                       |
| - | --------------------------------------------- | ------------------------------------------------------------------------------------ | --------------------------------- |
| 1 | `/v1/organization/costs`                      | `start_time`, `bucket_width=1d`, `group_by=line_item`, `project_ids[]…`, `limit=180` | `costs.json`                      |
| 2 | `/v1/organization/usage/completions`          | `start_time`, `bucket_width=1d`, `group_by=model`, `project_ids[]…`, `limit=180`     | `usage-completions.json`          |
| 3 | `/v1/organization/usage/embeddings`           | `start_time`, `bucket_width=1d`, `group_by=model`, `project_ids[]…`, `limit=180`     | `usage-embeddings.json`           |
| 4 | `/v1/organization/usage/images`               | `start_time`, `bucket_width=1d`, `group_by=model`, `project_ids[]…`, `limit=180`     | `usage-images.json`               |
| 5 | `/v1/organization/usage/audio_speeches`       | `start_time`, `bucket_width=1d`, `group_by=model`, `project_ids[]…`, `limit=180`     | `usage-audio-speeches.json`       |
| 6 | `/v1/organization/usage/audio_transcriptions` | `start_time`, `bucket_width=1d`, `group_by=model`, `project_ids[]…`, `limit=180`     | `usage-audio-transcriptions.json` |

**2d. Run the script, then delete it.** Record results in
`$MIGRATION_DIR/openai-capture/manifest.json`:

```json
{
  "captured_at": "<ISO 8601 UTC>",
  "window_days": 30,
  "admin_key_sha256": "<sha256 of .openai-admin-env contents — fingerprint only>",
  "project_filter": ["proj_abc", "proj_def"],
  "captures": [
    { "endpoint": "<row endpoint>", "file": "<file>", "status": "ok|failed|skipped", "note": null }
  ]
}
```

Every attempted or deliberately skipped call gets an entry. If EVERY usage row
failed, exit with no output and tell the user which scope is missing.

## Step 3: Parse Captures into the Usage Profile

Sum across the window (a throwaway extraction script if captures are large):

- **Costs** (`costs.json`): total spend over the window; per-line-item totals
  (line items map to model families and endpoint types). `monthly_cost_usd` =
  the last-30-days ACTUAL total — **never scale a partial window up to a
  month** (extrapolating a few days of spike traffic fabricates a baseline).
  If the org's first non-zero bucket is < 30 days old, set
  `partial_window: true` and report the actual span in `active_days`.
- **Usage** (rows 2–6): per model — `input_tokens`, `output_tokens` (completions
  and embeddings; embeddings have no output tokens), `num_model_requests`,
  images/seconds counts for image/audio endpoints.

Write `$MIGRATION_DIR/openai-usage-profile.json`:

```json
{
  "metadata": {
    "report_date": "2026-08-21",
    "source": "openai_usage_api",
    "captured_at": "<from manifest>",
    "window_days": 30,
    "active_days": 30,
    "partial_window": false,
    "projects": [{ "id": "proj_abc", "label": "production" }],
    "capture_warnings": ["usage-embeddings.json failed (403)"]
  },
  "summary": {
    "monthly_cost_usd": 105.03,
    "currency": "USD",
    "models_seen": 5,
    "total_requests": 2856
  },
  "costs_by_line_item": [
    { "line_item": "gpt-5.6-terra, input", "monthly_cost_usd": 41.61 }
  ],
  "usage_by_model": [
    {
      "model": "gpt-5.6-terra",
      "endpoint_type": "completions|embeddings|images|audio_speeches|audio_transcriptions",
      "input_tokens": 1300000,
      "output_tokens": 145000,
      "num_model_requests": 452
    }
  ]
}
```

`usage_by_model` sorted descending by `input_tokens + output_tokens`. Include
only models with non-zero usage. `metadata.capture_warnings` carries every
`failed`/`skipped` manifest entry (empty array when all rows succeeded) — the
same convention as live discovery's `live_metadata.capture_warnings` — so
downstream phases can tell a failed usage category (UNKNOWN volume) from a
genuinely unused one (zero). Validate: valid JSON, `summary.monthly_cost_usd`
equals the sum of `costs_by_line_item` (± rounding).

## Step 4: Merge into the AI Workload Profile (if it exists), Then Clean Up

If `$MIGRATION_DIR/ai-workload-profile.json` exists (from app-code or IaC
discovery), update it — the API data is authoritative for OpenAI spend and
volume:

1. `metadata.sources_analyzed.openai_usage_api` = `true`.
2. `current_costs` — provider-aware merge. The API measures **OpenAI** spend;
   a GCP billing CSV measures **GCP/Vertex** spend. They are different
   providers, so never pick one with max():
   - **No existing `current_costs`** → set
     `{ "monthly_ai_spend": <summary.monthly_cost_usd>, "services_detected":
     [<distinct endpoint_type values, prefixed "OpenAI ">], "source":
     "openai_usage_api" }`.
   - **Existing billing-CSV costs for a DIFFERENT provider** (e.g. `ai_source`
     is `both`, CSV captured Vertex spend) → SUM the providers:
     `monthly_ai_spend` = OpenAI + GCP, `source: "mixed"`, and record the
     per-provider split in `breakdown[]`:
     `[{ "provider": "openai", "monthly_spend": X, "source": "openai_usage_api" },
     { "provider": "gcp", "monthly_spend": Y, "source": "billing_data" }]`.
   - **Existing costs for the SAME provider** (a billing export that already
     contains OpenAI spend, same window) → the API wins (`source:
     "openai_usage_api"`); move the displaced figure into
     `current_costs.conflicting_sources[]` — never silently resolved,
     same rule as live-discovery drift.
3. Append to `detection_signals[]`:
   `{ "method": "openai_usage_api", "pattern": "billed usage for <model>",
   "confidence": 0.99, "evidence": "<N> requests, <X> tokens in last 30d" }`
   for each of the top 5 models by usage.
4. For any `usage_by_model` model absent from `models[]`: append
   `{ "model_id": "<model>", "service": "openai_api", "detected_via":
   ["usage_api"], "evidence": [{ "source": "usage_api", "pattern": "billed
   usage in last 30 days" }], "capabilities_used": [<from endpoint_type:
   completions→"text_generation", embeddings→"embeddings",
   images→"image_generation", audio_speeches→"speech_generation",
   audio_transcriptions→"transcription">], "usage_context": "Observed in
   OpenAI usage data — call sites not yet located in code" }`. Code-derived
   entries always win on conflict; usage-only entries tell Clarify what code
   analysis missed.
5. If `summary.ai_source` is `"gemini"` and OpenAI usage was found, set it to
   `"both"`.

If `ai-workload-profile.json` does NOT exist, Clarify and Estimate read
`openai-usage-profile.json` directly for spend and volumes — but it is a
supplement, not an anchor: the run still needs at least one primary artifact
(resource inventory, AI workload profile, or billing profile) to pass the
Discover handoff gate.

**Clean up (default, not optional):** delete
`$MIGRATION_DIR/.openai-admin-env` now — the key is no longer needed. Tell the
user it was deleted and that they can also revoke the Admin key at
platform.openai.com if it was created just for this run.

Report: "OpenAI usage discovery: $X/month across N models (projects:
[selected ids]; window: 30 days[, partial: only M active days])."

The parent `discover.md` owns the phase status update — do not touch
`.phase-status.json` here.

---

## Error Handling

| Error                                                       | Behavior                                                                                                                                                                                                                              |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| curl / script runtime missing, or user skips                | Exit cleanly with no output (orchestrator falls back to billing files)                                                                                                                                                                |
| 401 on probe                                                | Not an Admin key or Usage is not set to Read (API error may say `api.usage.read`) — offer re-intake or skip                                                                                                                           |
| 401 mid-capture (probe succeeded, key then revoked/rotated) | Script aborts remaining calls, keeping completed files. Tell the user the key stopped working mid-run; offer Step 1 re-intake ("create/fix the key, then tell me to continue") or skip. On resume, re-run Step 2 — captures overwrite |
| 429 rate limit                                              | Wait 30s, retry once; second 429 → record `failed`, continue                                                                                                                                                                          |
| Individual endpoint fails                                   | Record `failed`/`skipped` in manifest, continue — zero usage on an endpoint is normal, never a halt                                                                                                                                   |
| Every usage endpoint failed                                 | Exit with no output; tell the user which scope is missing                                                                                                                                                                             |
| Selected projects have zero usage in the window             | Re-show the per-project spend list from 2b and let the user re-select once; still zero → write the profile with zeros and `partial_window: true`                                                                                      |
| All buckets zero (new org, no usage yet)                    | Write the profile with zeros and `partial_window: true`; warn that Estimate will fall back to token-volume tiers                                                                                                                      |

**Key principle:** partial results are better than no results. Record what failed;
never fabricate what wasn't captured.

## Scope Boundary

**This sub-file covers OpenAI usage capture ONLY.**

FORBIDDEN — Do NOT include ANY of:

- AWS service names, recommendations, or equivalents
- Migration strategies, phases, timelines, cost estimates, or effort estimates
- Any non-GET request, any endpoint not listed in Step 2, any management
  endpoint, any per-user or per-key grouping
- Unscoped org-wide capture — every Step 2c call carries the user's
  `project_ids[]` selection
- The Admin key value anywhere outside `.openai-admin-env` (no echoes, no
  command args, no artifacts, no context) — and that file is deleted in Step 4

**Your ONLY job: capture what this app spent and used on OpenAI. Nothing else.**
