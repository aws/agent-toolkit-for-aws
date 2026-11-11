# Discover: OpenRouter Usage API

> Optional, consent-gated, read-only. Measures what this OpenRouter account (or one selected workspace) actually used and spent in the last 30 completed UTC days, which models carried it, and how much ran on the user's own provider keys (BYOK). Writes `openrouter-usage-profile.json` and, when the gateway's upstreams are observed, adds the models it saw to `ai-workload-profile.json` with `provenance: "usage_api"`. If the user declines or has no management key, exit with no output.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Security Contract (applies to every step)

1. **Read-only, fixed endpoints.** A management key can also create, edit, and delete API keys, workspaces, and guardrails; this flow never calls those endpoints. Only `scripts/openrouter-usage.py` calls the API, on `https://openrouter.ai/api/v1`, and only the endpoints in the Step 2 Capture Endpoint Table: `GET` requests, except one read-only `POST` to `/analytics/query`, an aggregate query whose body only selects metrics, the `model` dimension, an hourly granularity, the time range, and a workspace filter. The script refuses any other body. Never call a chat, completion, or `/generation` endpoint (they run inference or return request content), and never a key, workspace, or other management endpoint that changes anything.
2. **The management key never enters this conversation.** Do not ask the user to paste it in chat, and never echo, print, or put its value in a command. If the user pastes a key in chat, do not use it: tell them it is now in the transcript, recommend rotating it at openrouter.ai/settings/management-keys, and continue with Step 1.
3. **The key file is a secret file.** `$MIGRATION_DIR/.openrouter-key-env` falls under the SKILL.md secret-file rule: never open it with any tool (`Read`, `cat`, `grep`, `sed`, and so on). Only `scripts/openrouter-usage.py` reads it. The script deletes it after every capture, however it ends (including a network error), and after any probe that does not succeed. However this flow ends, including when the user skips at any step, finish with `rm -f "$MIGRATION_DIR/.openrouter-key-env"`; keep the file only while a retry of Step 2 is in progress.
4. **Aggregate data only.** The endpoints return per-day and per-model totals: no prompts, completions, or request content. Never group or filter by API key or user. A workspace choice is honored only by filtering (`workspace_id` on `/activity`, a `workspace` filter on `/analytics/query`), never by grouping.
5. **Consent first.** Nothing happens before the user answers `[A]` in Step 0: no key intake, no key file, no API call.

---

## Step 0: Consent Gate

Output exactly, then wait:

```text
─── OpenRouter Usage (read-only, optional) ───

I can measure your OpenRouter usage directly from the OpenRouter API.
A helper script sends GET requests to a fixed list of usage and
credits endpoints, except one read-only POST to /analytics/query that
returns aggregate per-model totals. Nothing is created, changed, or
deleted in your OpenRouter account:

  ✓ First, to help you pick: your workspace list (shown here, not
    saved), and your lifetime credits purchased and used (account-wide,
    also saved with the capture as context).
  ✓ Then, for the whole account or one workspace YOU select: daily
    requests, tokens (prompt, completion, reasoning, cached), and cost
    per model; how much of each model's cost ran on your own provider
    keys (BYOK) versus OpenRouter credits, and the BYOK fee; request
    counts, p95 latency and throughput, web-search cost, guardrail
    counts, and the busiest hour; and the calling key's spending
    limit (never its name or label).
  ✗ Never captured: prompts or completions, request content, API keys,
    or per-key or per-user data.

Window: the last 30 completed UTC days. You need an OpenRouter
MANAGEMENT key; a regular inference key cannot read usage. Management
keys have no read-only scope: the same key can create, edit, and
delete your API keys. The helper script calls only the endpoints
above; give the key a short expiration. It goes into a chmod-600 file
in the gitignored .migration/ folder, is read only by the helper
script, and is deleted when capture ends or you skip.

[A] Measure my OpenRouter usage
[B] Skip
```

- **[A]**: continue to Step 1.
- **[B]**: delete any key file an earlier attempt left (`rm -f "$MIGRATION_DIR/.openrouter-key-env"`), then exit with no output. Do not offer it again in this run.

## Step 1: Key Intake

1. Tell the user: "This needs an OpenRouter **management key**; a regular inference key cannot read account usage. An organization admin creates one at openrouter.ai/settings/management-keys; choose a short expiration, and delete it after this run if you created it for this."
2. Check whether the environment has a key, without printing it:

   ```bash
   [ -n "$(printenv OPENROUTER_PROVISIONING_KEY)" ] && echo ENV_KEY_PRESENT || echo ENV_KEY_ABSENT
   ```

3. Ask how they want to provide it (offer `[A]` only on `ENV_KEY_PRESENT`). If the key is only in a `.env*` file, use `[B]`: never open that file to find it.
   - **[A] Use `OPENROUTER_PROVISIONING_KEY` from my environment:**

     ```bash
     ( umask 077 && rm -f "$MIGRATION_DIR/.openrouter-key-env" && printf 'OPENROUTER_PROVISIONING_KEY=%s\n' "$(printenv OPENROUTER_PROVISIONING_KEY)" > "$MIGRATION_DIR/.openrouter-key-env" )
     ```

   - **[B] I'll write the file myself:** give the user this command to run in their own terminal, with the run directory path filled in, and continue when they say it is done:

     ```bash
     read -rs k && ( umask 077 && rm -f "<MIGRATION_DIR>/.openrouter-key-env" && printf 'OPENROUTER_PROVISIONING_KEY=%s\n' "$k" > "<MIGRATION_DIR>/.openrouter-key-env" ) && unset k
     ```

   - **[C] Skip:** exit with no output.
4. Check the format with the script, which prints only `KEY_FORMAT_OK` or `KEY_FORMAT_BAD`:

   ```bash
   python3 <SKILL_BASE>/scripts/openrouter-usage.py check-key --key-file "$MIGRATION_DIR/.openrouter-key-env"
   ```

   On `KEY_FORMAT_BAD`, tell the user the file does not hold one `OPENROUTER_PROVISIONING_KEY=…` line, and repeat intake once. An inference key passes this check and is rejected by the probe.

## Step 2: Capture

**2a. Probe and pick a workspace.**

```bash
python3 <SKILL_BASE>/scripts/openrouter-usage.py probe --key-file "$MIGRATION_DIR/.openrouter-key-env"
```

It prints one `{"total_credits", "total_usage"}` line (lifetime, account-wide) and one `{"workspace_id", "name", "slug"}` line per workspace, and writes nothing to disk. On `KEY_REJECTED` the script has deleted the key file: tell the user the key is not a working management key (an inference key returns 403), and offer intake again or skip.

With zero or one workspace, capture the whole account and do not ask. With more than one, show the list and ask: "Capture every workspace, or one workspace that belongs to THIS application? [A] All workspaces / [B] Pick one." Never default silently either way. OpenRouter filters by one workspace at a time.

**2b. Capture.** Add `--workspace-id <id> --workspace-name <name>` only when the user picked one:

```bash
python3 <SKILL_BASE>/scripts/openrouter-usage.py capture --key-file "$MIGRATION_DIR/.openrouter-key-env" --out-dir "$MIGRATION_DIR/openrouter-capture"
```

The script first deletes capture files and the manifest from any earlier attempt, then calls each row of the Capture Endpoint Table in order, retries a `429` once after 30 seconds, writes one file per row and a `manifest.json` whose `result` is `complete`, `key_invalid_mid_run`, or `all_usage_failed`, deletes the key file, and prints `<file> ok|failed|skipped <rows>`.

**Capture Endpoint Table:**

| # | Endpoint                  | Query or body                                                                                                                                                                                                 | File                    |
| - | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| 1 | `GET /credits`            | none; lifetime `total_credits` and `total_usage`, account-wide                                                                                                                                                | `credits.json`          |
| 2 | `GET /activity`           | `workspace_id` when one was picked; daily rows per model with `requests`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `cached_tokens`, `usage`, and `byok_usage_inference`                      | `activity.json`         |
| 3 | `GET /key`                | none; only the calling key's `limit`, `limit_remaining`, `limit_reset`, `include_byok_in_limit`, and `is_free_tier` are kept, for context (`skipped` on any error)                                            | `key.json`              |
| 4 | `GET /analytics/meta`     | none; the metrics the analytics query offers                                                                                                                                                                  | `analytics-meta.json`   |
| 5 | `POST /analytics/query`   | metrics `byok_usage`, `openrouter_usage`; dimension `model`                                                                                                                                                   | `analytics.json`        |
| 6 | `POST /analytics/query`   | metrics `tokens_prompt`, `tokens_completion`, `reasoning_tokens`, `cached_tokens`, `byok_fees`, `byok_request_count`, `request_count`, `p95_latency`, `p95_throughput`, `usage_web`, `guardrail_invoked_count`; dimension `model` | `analytics-volume.json` |
| 7 | `POST /analytics/query`   | metrics `tokens_prompt`, `tokens_completion`, `request_count`; dimension `model`; granularity `hour`                                                                                                          | `analytics-hourly.json` |

Rows 5 to 7 request only the metrics row 4 lists; a row with none of them is `skipped`. They use the same window as `/activity` (`time_range` from 30 days before the last UTC midnight to that midnight) and, when a workspace was picked, a `workspace` filter with its ID. A truncated reply is retried once with `limit` 5000; if it is still truncated, the file is kept and named as truncated. Never add an API key, user, or other per-caller dimension.

Exit codes: `0` done; `3` `KEY_INVALID_MID_RUN` (the key stopped working on row 1 or 2: offer Step 1 intake again and re-run 2b, or skip); `4` `ALL_USAGE_FAILED` (`/activity` failed: there is no per-model usage, so exit with no usage profile). A failed or skipped row 3 to 7 never stops the capture.

## Step 3: Summarize

```bash
python3 <SKILL_BASE>/scripts/openrouter-usage.py summarize --capture-dir "$MIGRATION_DIR/openrouter-capture" --out "$MIGRATION_DIR/openrouter-usage-profile.json"
```

The script reads only files the current manifest records as `ok`, refuses with `CAPTURE_NOT_COMPLETE` unless its `result` is `complete`, writes `openrouter-usage-profile.json`, and prints its `summary`:

- `usage_by_model[]` has one row per OpenRouter model id (for example `openai/gpt-4.1`), summed over the window: `requests`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `cached_tokens` (part of `prompt_tokens`, not added to it), `monthly_cost_usd` (OpenRouter credits spent, from `usage`), and `byok_inference_cost_usd` (inference billed by the user's own provider key, from `byok_usage_inference`). `provider_name` is the serving provider when every row agrees, else `null`.
- `cost_provenance` per model comes from `analytics.json`, joined on each row's `model_permaslug` and rolled up to the model id. With a $0.005 threshold: BYOK cost only is `byok_passthrough`; both is `mixed`; credits only is `no_byok`; neither is `unknown`. Across permaslugs of one model: any `mixed`, or both `byok_passthrough` and `no_byok`, is `mixed`; a classified permaslug next to an `unknown` one is `uncertain`, with a warning. When `analytics.json` is not `ok`, every model is `unknown`. `metadata.cost_provenance` is the single value when all models agree (except `uncertain`), else `mixed`; `unknown` when nothing is classified.
- From `analytics-volume.json`, summed across permaslugs: `byok_fees_usd`, `byok_request_count`, `analytics_request_count` (`requests` stays from `/activity`), `web_search_cost_usd`, and `guardrail_invoked_count`; `p95_latency_ms` is the slowest permaslug's and `p95_throughput_tokens_per_sec` the slowest. These fields are absent when that file is missing or truncated. Never split a mixed model's tokens or dollars by its request share.
- `peak` is the busiest UTC day from `/activity`, and from `analytics-hourly.json` the busiest hour divided by 60 for tokens and requests (`peak_source: "hour"`). When that file is missing or truncated, the per-minute fields are `null` and `peak_source` is `"day"`.
- `summary.monthly_cost_usd` is the credits total for the window, never scaled up from fewer days; `summary.byok_inference_cost_usd` is the BYOK total, and when it is above $0.005 a warning says that spend is billed by the user's provider keys and is not in `monthly_cost_usd`. `metadata.active_days`, `partial_window`, and `cost_status` (`partial_window` or `complete`) describe the window. `metadata.credits_lifetime` is account-wide even when a workspace was picked, and `metadata.workspace_scope` records the pick.
- `metadata.capture_warnings` names every failed, skipped, or truncated file, every `uncertain` model, and an empty `/activity` on an account whose lifetime usage is above zero (spend exists outside the window). A warning for `analytics-hourly.json` makes only the peak uncertain.

## Step 4: Merge, Validate, and Clean Up

```bash
python3 <SKILL_BASE>/scripts/openrouter-usage.py merge --usage "$MIGRATION_DIR/openrouter-usage-profile.json" --profile "$MIGRATION_DIR/ai-workload-profile.json"
```

OpenRouter is a gateway, never a source. The merge applies the scan's OpenRouter rules (`discover-app-code.md`, Step 3) to each usage model: `openai/…` and `anthropic/…` belong to `openai`/`openai_api` and `anthropic`/`anthropic_api`; `google/…` belongs to `google`/`vertex_ai` when `provider_name` is `Google Vertex` and `google`/`gemini_api` when it is `Google AI Studio`. It adds each model to that source with evidence `{"provenance": "usage_api", "confidence": "high"}`, keeps the OpenRouter id in `raw_model`, rebuilds that gateway upstream's model families from the source, and writes the profile only when the validator accepts it. Code evidence is never removed.

- `GATEWAY_NOT_OBSERVED`: the profile has no OpenRouter gateway with observed upstreams. `SOURCE_NOT_ESTABLISHED`: a usage model has another prefix, or a `google/` model's serving provider is not one service. `UPSTREAM_NOT_IN_PROFILE`: a model's source is not an observed upstream. In each case the profile is left unchanged: tell the user the usage profile was written, and name the models usage saw.
- `MERGE_INVALID`: the profile is left unchanged; quote the message.

The capture already deleted the key file; run `rm -f "$MIGRATION_DIR/.openrouter-key-env"` anyway, and tell the user they can also delete the management key at openrouter.ai/settings/management-keys if they created it for this run.

Report: "OpenRouter usage: $X in credits over the last N days across M models[, scoped to workspace '<name>'; lifetime credits are account-wide]." Add "plus $Y of BYOK inference billed by your own provider keys" when `byok_inference_cost_usd` is above zero, and state every `capture_warnings` entry plainly; never let "$0" stand when a warning says spend exists outside the window. Keep `openrouter-capture/` and `openrouter-usage-profile.json` in the run directory for later phases.

---

## Error Handling

| Situation                                                   | Behavior                                                                                       |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| User declines or skips at any step, or `python3` is missing | `rm -f` the key file, then exit with no output                                                 |
| `KEY_FORMAT_BAD` or `KEY_REJECTED`                          | Offer intake again once, or skip                                                               |
| `KEY_INVALID_MID_RUN`                                       | Offer Step 1 intake again and re-run Step 2b, or skip                                          |
| A row 3 to 7 `failed` or `skipped`                          | Continue; Step 3 lists it in `capture_warnings`                                                |
| `analytics.json` `failed` or `skipped`                      | Continue; every model's `cost_provenance` is `unknown`                                         |
| `ALL_USAGE_FAILED`                                          | Exit with no usage profile; say `/activity` could not be read                                  |
| The script stops on a network error or timeout              | The script has deleted the key file; offer intake again once, or skip                          |
| Resumed run, `manifest.json` `result` is `complete`         | Start at Step 3; consent and capture already happened                                          |
| Resumed run, `result` is `key_invalid_mid_run`              | Consent was given: start at Step 1 intake, then Step 2                                         |
| Resumed run, `result` is `all_usage_failed`                 | Consent was given: start at Step 1 intake, then Step 2. The next capture replaces these files. |

## Scope Boundary

This file covers OpenRouter usage capture only. FORBIDDEN: AWS recommendations or costs; any endpoint not in the Capture Endpoint Table; any method other than `GET`, except the one read-only `POST /analytics/query`; chat, completion, or generation calls; per-key or per-user grouping or filtering; and the management key value anywhere outside `.openrouter-key-env`.
