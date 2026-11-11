# Discover: Anthropic Usage API

> Optional, consent-gated, read-only. Measures what the selected Anthropic workspaces actually used and spent in the last 30 days, writes `anthropic-usage-profile.json`, and adds the models it saw to `ai-workload-profile.json` with `provenance: "usage_api"`. If the user declines or has no Admin key, exit with no output. Claude Console (Claude Platform) organizations only.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Security Contract (applies to every step)

1. **Read-only, fixed endpoints.** Only `scripts/anthropic-usage.py` calls the API, and it sends only `GET` requests to the two endpoints in the Step 2 Capture Endpoint Table, on `https://api.anthropic.com`. The same Admin key can also manage members, workspaces, API keys, spend limits, and rate limits: never call those or any other endpoint, and never call the API another way.
2. **The Admin key never enters this conversation.** Do not ask the user to paste it in chat, and never echo, print, or put its value in a command. If the user pastes a key in chat, do not use it: tell them it is now in the transcript, recommend rotating it, and continue with Step 1.
3. **The key file is a secret file.** `$MIGRATION_DIR/.anthropic-admin-env` falls under the SKILL.md secret-file rule: never open it with any tool (`Read`, `cat`, `grep`, `sed`, and so on). Only `scripts/anthropic-usage.py` reads it. The script deletes it after every capture, however it ends (including a network error), and after any probe that does not succeed. However this flow ends, including when the user skips at any step, finish with `rm -f "$MIGRATION_DIR/.anthropic-admin-env"`; keep the file only while a retry of Step 2 is in progress.
4. **Scoped, aggregate data only.** The endpoints return bucketed token counts and costs: no prompts, completions, or files. The Step 2a probe is the one read that is not filtered by workspace: it prints each workspace's total spend so the user can pick, and writes nothing to disk. Every capture keeps only the workspaces the user then selects. Never group by user, API key, or service account.
5. **Consent first.** Nothing happens before the user answers `[A]` in Step 0: no key intake, no key file, no API call.

---

## Step 0: Consent Gate

Output exactly, then wait:

```text
─── Anthropic Usage (read-only, optional) ───

I can measure your Claude API usage directly from the Anthropic Admin
API. A helper script sends GET requests only, to two fixed usage and
cost endpoints:

  ✓ First, to help you pick: each workspace's total spend for the
    window (shown here, not saved).
  ✓ Then, for the workspace(s) YOU select as this application only:
    daily costs by line item; tokens per model, service tier, context
    window, inference geo, and speed, including cache reads and cache
    writes; web search requests; and the busiest hour and minute.
    The cost endpoint cannot filter by workspace, and the usage
    endpoint cannot filter to the default workspace, so those replies
    can include other workspaces' rows: the script drops them before
    saving anything.
  ✗ Never captured: prompts or completions, files, API keys, members,
    per-user or per-key data, or usage of workspaces you don't select.
    Nothing is created, changed, or deleted in your Anthropic account.

Window: last 30 days. You need an Anthropic ADMIN key
(sk-ant-admin01-…). Anthropic Admin keys have no narrower usage-only
scope: the same key can manage your organization's members,
workspaces, and keys. The helper script calls only the two endpoints
above. The key goes into a chmod-600 file in the gitignored .migration/
folder, is read only by the helper script, and is deleted when capture
ends or you skip.

Claude Console (Claude Platform) organizations only: Claude Enterprise
and Claude Platform on AWS organizations do not offer these endpoints.

[A] Measure my Anthropic usage
[B] Skip
```

- **[A]**: continue to Step 1.
- **[B]**: delete any key file an earlier attempt left (`rm -f "$MIGRATION_DIR/.anthropic-admin-env"`), then exit with no output. Do not offer it again in this run.

## Step 1: Key Intake

1. Tell the user: "This needs an **Admin API key** (`sk-ant-admin01-…`); regular API keys (`sk-ant-api03-…`) cannot read organization usage. A member with the admin role creates one at platform.claude.com/settings/admin-keys; choose a short expiration, and delete it after this run if you created it for this."
2. Check whether the environment has a key, without printing it:

   ```bash
   [ -n "$(printenv ANTHROPIC_ADMIN_KEY)" ] && echo ENV_KEY_PRESENT || echo ENV_KEY_ABSENT
   ```

3. Ask how they want to provide it (offer `[A]` only on `ENV_KEY_PRESENT`). If the key is only in a `.env*` file, use `[B]`: never open that file to find it.
   - **[A] Use `ANTHROPIC_ADMIN_KEY` from my environment:**

     ```bash
     ( umask 077 && rm -f "$MIGRATION_DIR/.anthropic-admin-env" && printf 'ANTHROPIC_ADMIN_KEY=%s\n' "$(printenv ANTHROPIC_ADMIN_KEY)" > "$MIGRATION_DIR/.anthropic-admin-env" )
     ```

   - **[B] I'll write the file myself:** give the user this command to run in their own terminal, with the run directory path filled in, and continue when they say it is done:

     ```bash
     read -rs k && ( umask 077 && rm -f "<MIGRATION_DIR>/.anthropic-admin-env" && printf 'ANTHROPIC_ADMIN_KEY=%s\n' "$k" > "<MIGRATION_DIR>/.anthropic-admin-env" ) && unset k
     ```

   - **[C] Skip:** exit with no output.
4. Check the format with the script, which prints only `KEY_FORMAT_OK` or `KEY_FORMAT_BAD`:

   ```bash
   python3 <SKILL_BASE>/scripts/anthropic-usage.py check-key --key-file "$MIGRATION_DIR/.anthropic-admin-env"
   ```

   On `KEY_FORMAT_BAD`, tell the user the file does not hold one `ANTHROPIC_ADMIN_KEY=sk-ant-admin01-…` line and repeat intake once.

## Step 2: Capture

**2a. Probe and pick workspaces.**

```bash
python3 <SKILL_BASE>/scripts/anthropic-usage.py probe --key-file "$MIGRATION_DIR/.anthropic-admin-env"
```

It prints one `{"workspace_id", "spend_usd"}` line per workspace, largest first, and writes nothing to disk. The organization's default workspace is listed as `default`. On `KEY_REJECTED` the script has deleted the key file: tell the user the key is not a working Admin key, and offer intake again or skip. On `ORG_NOT_SUPPORTED` the script has deleted the key file: tell the user this organization does not offer the usage and cost endpoints (Claude Enterprise and Claude Platform on AWS do not), and exit with no output.

Show the list and ask: "Which of these Anthropic workspaces belong to THIS application? The API shows workspace IDs, not names (match them in the Claude Console under Settings → Workspaces). List the IDs, or say `all` only if this organization runs nothing else." Never default to `all`. The user may label workspaces (`wrkspc_abc=production`). Then confirm: "These workspaces spent $X of $Y in the window. Capture them? [Y] / [N] re-select."

**2b. Capture.** One command, with one `--workspace` per selected ID (`--workspace default` for the default workspace):

```bash
python3 <SKILL_BASE>/scripts/anthropic-usage.py capture --key-file "$MIGRATION_DIR/.anthropic-admin-env" --out-dir "$MIGRATION_DIR/anthropic-capture" --workspace wrkspc_abc --workspace default
```

The script first deletes capture files and the manifest from any earlier attempt, then calls each row of the Capture Endpoint Table in order, follows `next_page`, retries a `429` once after 30 seconds, keeps only rows of the selected workspaces, writes one file per row and a `manifest.json` whose `result` is `complete`, `key_invalid_mid_run`, or `all_usage_failed`, deletes the key file, and prints `<file> ok|failed|skipped <buckets>`. Row 4 covers only the busiest non-batch UTC day found in row 3, and is `skipped` when there is none.

**Capture Endpoint Table:**

| # | Endpoint (GET, `https://api.anthropic.com`) | Query                                                                                                              | File                         |
| - | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | ---------------------------- |
| 1 | `/v1/organizations/cost_report`             | `bucket_width=1d`, `group_by[]=workspace_id,description`, `limit=31`                                               | `cost-report.json`           |
| 2 | `/v1/organizations/usage_report/messages`   | `bucket_width=1d`, `group_by[]=model,service_tier,context_window,inference_geo,speed,workspace_id`, `limit=31`    | `usage-messages.json`        |
| 3 | `/v1/organizations/usage_report/messages`   | `bucket_width=1h`, same `group_by[]` as row 2, `limit=168`                                                         | `usage-messages-hourly.json` |
| 4 | `/v1/organizations/usage_report/messages`   | `bucket_width=1m`, the busiest non-batch day from row 3, same `group_by[]` as row 2, `limit=1440`                  | `usage-messages-minute.json` |

Every row sends `starting_at` (30 days ago) and the `x-api-key` and `anthropic-version: 2023-06-01` headers. `group_by[]` repeats once per dimension. The cost endpoint has no workspace filter, so its rows are filtered by `workspace_id` in the script. The usage rows also send one `workspace_ids[]` per selected workspace, unless the default workspace is selected: it has no ID the filter accepts, so then the script filters those rows by `workspace_id` too. Rows of unselected workspaces are never written. The Step 2a probe is row 1 grouped by `workspace_id` only. The limits are each endpoint's maximum for that bucket width.

Exit codes: `0` done; `3` `KEY_INVALID_MID_RUN` (the key stopped working: offer Step 1 intake again and re-run 2b, or skip); `4` `ALL_USAGE_FAILED` (row 2 failed: tell the user the key likely cannot read usage, and exit with no usage profile).

## Step 3: Summarize

```bash
python3 <SKILL_BASE>/scripts/anthropic-usage.py summarize --capture-dir "$MIGRATION_DIR/anthropic-capture" --out "$MIGRATION_DIR/anthropic-usage-profile.json" --label wrkspc_abc=production
```

The script reads only files the current manifest records as `ok`, refuses with `CAPTURE_NOT_COMPLETE` unless its `result` is `complete`, writes `anthropic-usage-profile.json`, and prints its `summary`:

- `summary.monthly_cost_usd` is the actual total for the window in USD (the API reports cents), never scaled up from fewer days; `metadata.active_days` and `partial_window` say when the organization has less than 30 days of activity. `summary.total_tokens` is uncached input, cache reads, cache writes, and output, summed.
- `metadata.cost_status` is `cost_unavailable` when the cost request failed: `summary.monthly_cost_usd` is then `null`, never `0`, and token usage is still reported. A cost request that succeeded with no spend is a real `0`. It is `partial_window` when the window is short, or when usage includes a service tier the cost endpoint does not report (it reports only `standard` and `batch`; Priority Tier is billed separately), `metadata.uncosted_service_tiers` names those tiers, and `metadata.capture_warnings` says the total excludes their spend, so later cost comparisons are qualified. Otherwise it is `complete`.
- `usage_by_model[]` has one row per `(model, service_tier, context_window, inference_geo, speed)` with `input_tokens` (uncached input), `output_tokens`, `cache_read_tokens`, `cache_creation_5m_tokens`, `cache_creation_1h_tokens`, their sum `cache_creation_tokens`, `web_search_requests`, and a `peak`: the busiest UTC day, then the busiest hour divided by 60, replaced by the sampled minute only when that minute is higher. The peak's input, the busiest day, and its `day_input_tokens` count uncached input and cache writes, not cache reads. The API reports no request counts.
- `costs_by_description[]` has one row per cost line, with its `model`, `inference_geo`, `workspace_id`, and `cost_type`.
- `metadata.capture_warnings` names every failed or skipped file. A failed hourly or minute file makes only the peak uncertain.

## Step 4: Merge, Validate, and Clean Up

```bash
python3 <SKILL_BASE>/scripts/anthropic-usage.py merge --usage "$MIGRATION_DIR/anthropic-usage-profile.json" --profile "$MIGRATION_DIR/ai-workload-profile.json"
```

It adds each model from `usage_by_model` to the `anthropic`/`anthropic_api` source (creating it if needed) with evidence `{"provenance": "usage_api", "confidence": "high"}`, keeps the model name exactly as reported in `raw_model`, and writes the profile only when the validator accepts it. A usage report can name a model differently from the alias the code uses: keep both. Code evidence is never removed.

- `GATEWAY_UPSTREAM_CONFLICT`: Anthropic is also reached through a gateway in this profile, so the source's models must match that gateway's upstream. The profile is left unchanged; tell the user the usage profile was written but its models were not added.
- `MERGE_INVALID`: the profile is left unchanged; quote the message.

The capture already deleted the key file; run `rm -f "$MIGRATION_DIR/.anthropic-admin-env"` anyway, and tell the user they can also delete the Admin key in the Claude Console if they created it for this run.

Report: "Anthropic usage: $X over the last N days across M models (workspaces: …)." When `cost_status` is `cost_unavailable`, say "spend not available (the cost request failed)" instead of a dollar figure; when `uncosted_service_tiers` is not empty, say those tiers' spend is not included. Keep `anthropic-capture/` and `anthropic-usage-profile.json` in the run directory for later phases.

---

## Error Handling

| Situation                                                   | Behavior                                                                                       |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| User declines or skips at any step, or `python3` is missing | `rm -f` the key file, then exit with no output                                                 |
| `KEY_FORMAT_BAD` or `KEY_REJECTED`                          | Offer intake again once, or skip                                                               |
| `ORG_NOT_SUPPORTED`                                         | Exit with no output; say the organization type does not offer these endpoints                  |
| `KEY_INVALID_MID_RUN`                                       | Offer Step 1 intake again and re-run Step 2b, or skip                                          |
| One row `failed`                                            | Continue; Step 3 lists it in `capture_warnings` and ignores the file                           |
| Cost row `failed`                                           | Continue; `cost_status: "cost_unavailable"`, spend `null`, token usage kept                    |
| `ALL_USAGE_FAILED`                                          | Exit with no usage profile; say the key likely cannot read usage                               |
| The script stops on a network error or timeout              | The script has deleted the key file; offer intake again once, or skip                          |
| Selected workspaces show zero usage                         | Show the workspace list again once; if still zero, write the profile with zeros                |
| Resumed run, `manifest.json` `result` is `complete`         | Start at Step 3; consent and capture already happened                                          |
| Resumed run, `result` is `key_invalid_mid_run`              | Consent was given: start at Step 1 intake, then Step 2                                         |
| Resumed run, `result` is `all_usage_failed`                 | Consent was given: start at Step 1 intake, then Step 2. The next capture replaces these files. |

## Scope Boundary

This file covers Anthropic usage capture only. FORBIDDEN: AWS recommendations or costs; any non-GET request; any endpoint not in the Capture Endpoint Table, including every Admin management endpoint the same key can reach; per-user, per-key, or per-service-account grouping; capture of workspaces the user did not select; and the Admin key value anywhere outside `.anthropic-admin-env`.
