# Discover: OpenAI Usage API

> Optional, consent-gated, read-only. Measures what the selected OpenAI projects actually used and spent in the last 30 days, writes `openai-usage-profile.json`, and adds the models it saw to `ai-workload-profile.json` with `provenance: "usage_api"`. If the user declines or has no Admin key, exit with no output.

**Execute ALL steps in order. Do not skip or optimize.**

---

## Security Contract (applies to every step)

1. **Read-only, fixed endpoints.** Only `scripts/openai-usage.py` calls the API, and it sends only `GET` requests to the endpoints in the Step 2 Capture Endpoint Table, on `https://api.openai.com`. Never call the API another way, never call another endpoint, and never call management endpoints (projects, users, API keys).
2. **The Admin key never enters this conversation.** Do not ask the user to paste it in chat, and never echo, print, or put its value in a command. If the user pastes a key in chat, do not use it: tell them it is now in the transcript, recommend rotating it, and continue with Step 1.
3. **The key file is a secret file.** `$MIGRATION_DIR/.openai-admin-env` falls under the SKILL.md secret-file rule: never open it with any tool (`Read`, `cat`, `grep`, `sed`, and so on). Only `scripts/openai-usage.py` reads it. The script deletes it after every capture, successful or not, and after a rejected probe. However this flow ends, including when the user skips at any step, finish with `rm -f "$MIGRATION_DIR/.openai-admin-env"`; keep the file only while a retry of Step 2 is in progress.
4. **Scoped, aggregate data only.** The endpoints return bucketed token counts and costs: no prompts, completions, or files. The Step 2a probe is the one read that is not filtered by project: it prints each project's total spend so the user can pick, and writes nothing to disk. Every capture is filtered to the projects the user then selects. Never group by user or API key.
5. **Consent first.** Nothing happens before the user answers `[A]` in Step 0: no key intake, no key file, no API call.

---

## Step 0: Consent Gate

Output exactly, then wait:

```text
─── OpenAI Usage (read-only, optional) ───

I can measure your OpenAI usage directly from the OpenAI Admin API.
A helper script sends GET requests only, to a fixed list of usage
and cost endpoints:

  ✓ First, to help you pick: each project's total spend for the window
    (shown here, not saved).
  ✓ Then, for the OpenAI project(s) YOU select as this application only:
    daily costs by line item; tokens and requests per model (completions,
    embeddings, images, audio), including cached tokens, batch, and
    service tier; and the busiest hour and minute.
  ✗ Never captured: prompts or completions, files, API keys, members,
    per-user or per-key data, or usage of projects you don't select.
    Nothing is created, changed, or deleted in your OpenAI account.

Window: last 30 days. You need an OpenAI ADMIN key with Usage set to
Read. It goes into a chmod-600 file in the gitignored .migration/
folder, is read only by the helper script, and is deleted when capture
ends or you skip.

[A] Measure my OpenAI usage
[B] Skip
```

- **[A]**: continue to Step 1.
- **[B]**: delete any key file an earlier attempt left (`rm -f "$MIGRATION_DIR/.openai-admin-env"`), then exit with no output. Do not offer it again in this run.

## Step 1: Key Intake

1. Tell the user: "This needs an **Admin API key** (`sk-admin-…`); project keys (`sk-proj-…`) cannot read organization usage. Create one at platform.openai.com → Settings → Organization → Admin keys, set **Usage** to **Read**, and leave every other permission off."
2. Check whether the environment has a key, without printing it:

   ```bash
   [ -n "$(printenv OPENAI_ADMIN_KEY)" ] && echo ENV_KEY_PRESENT || echo ENV_KEY_ABSENT
   ```

3. Ask how they want to provide it (offer `[A]` only on `ENV_KEY_PRESENT`). If the key is only in a `.env*` file, use `[B]`: never open that file to find it.
   - **[A] Use `OPENAI_ADMIN_KEY` from my environment:**

     ```bash
     ( umask 077 && rm -f "$MIGRATION_DIR/.openai-admin-env" && printf 'OPENAI_ADMIN_KEY=%s\n' "$(printenv OPENAI_ADMIN_KEY)" > "$MIGRATION_DIR/.openai-admin-env" )
     ```

   - **[B] I'll write the file myself:** give the user this command to run in their own terminal, with the run directory path filled in, and continue when they say it is done:

     ```bash
     read -rs k && ( umask 077 && rm -f "<MIGRATION_DIR>/.openai-admin-env" && printf 'OPENAI_ADMIN_KEY=%s\n' "$k" > "<MIGRATION_DIR>/.openai-admin-env" ) && unset k
     ```

   - **[C] Skip:** exit with no output.
4. Check the format with the script, which prints only `KEY_FORMAT_OK` or `KEY_FORMAT_BAD`:

   ```bash
   python3 <SKILL_BASE>/scripts/openai-usage.py check-key --key-file "$MIGRATION_DIR/.openai-admin-env"
   ```

   On `KEY_FORMAT_BAD`, tell the user the file does not hold one `OPENAI_ADMIN_KEY=sk-admin-…` line and repeat intake once.

## Step 2: Capture

**2a. Probe and pick projects.**

```bash
python3 <SKILL_BASE>/scripts/openai-usage.py probe --key-file "$MIGRATION_DIR/.openai-admin-env"
```

It prints one `{"project_id", "spend_usd"}` line per project, largest first, and writes nothing to disk. On `KEY_REJECTED` the script has deleted the key file: tell the user the key is not an Admin key with Usage set to Read, and offer intake again or skip.

Show the list and ask: "Which of these OpenAI projects belong to THIS application? The API shows project IDs, not names (match them at platform.openai.com → Settings → Projects). List the IDs, or say `all` only if this organization runs nothing else." Never default to `all`. The user may label projects (`proj_abc=production`). Then confirm: "These projects spent $X of $Y in the window. Capture them? [Y] / [N] re-select."

**2b. Capture.** One command, with one `--project` per selected ID:

```bash
python3 <SKILL_BASE>/scripts/openai-usage.py capture --key-file "$MIGRATION_DIR/.openai-admin-env" --out-dir "$MIGRATION_DIR/openai-capture" --project proj_abc --project proj_def
```

The script first deletes capture files and the manifest from any earlier attempt, then calls each row of the Capture Endpoint Table in order, follows `next_page`, retries a `429` once after 30 seconds, writes one file per row and a `manifest.json` whose `result` is `complete`, `key_invalid_mid_run`, or `all_usage_failed`, deletes the key file, and prints `<file> ok|failed|skipped <buckets>`. Row 8 covers only the busiest on-demand UTC day found in row 7, and is `skipped` when there is none.

**Capture Endpoint Table:**

| # | Endpoint (GET, `https://api.openai.com`)      | Query                                                                                       | File                              |
| - | --------------------------------------------- | ------------------------------------------------------------------------------------------- | --------------------------------- |
| 1 | `/v1/organization/costs`                      | `bucket_width=1d`, `group_by=line_item`, `limit=180`                                        | `costs.json`                      |
| 2 | `/v1/organization/usage/completions`          | `bucket_width=1d`, `group_by=model,batch,service_tier`, `limit=31`                          | `usage-completions.json`          |
| 3 | `/v1/organization/usage/embeddings`           | `bucket_width=1d`, `group_by=model`, `limit=31`                                             | `usage-embeddings.json`           |
| 4 | `/v1/organization/usage/images`               | `bucket_width=1d`, `group_by=model`, `limit=31`                                             | `usage-images.json`               |
| 5 | `/v1/organization/usage/audio_speeches`       | `bucket_width=1d`, `group_by=model`, `limit=31`                                             | `usage-audio-speeches.json`       |
| 6 | `/v1/organization/usage/audio_transcriptions` | `bucket_width=1d`, `group_by=model`, `limit=31`                                             | `usage-audio-transcriptions.json` |
| 7 | `/v1/organization/usage/completions`          | `bucket_width=1h`, `group_by=model,batch,service_tier`, `limit=168`                         | `usage-completions-hourly.json`   |
| 8 | `/v1/organization/usage/completions`          | `bucket_width=1m`, the busiest on-demand day from row 7, `group_by=model,batch,service_tier`, `limit=1440` | `usage-completions-minute.json` |

Every row also sends `start_time` (30 days ago) and one `project_ids` per selected project. The Step 2a probe is row 1 grouped by `project_id`, without `project_ids`. The limits are each endpoint's maximum for that bucket width.

Exit codes: `0` done; `3` `KEY_INVALID_MID_RUN` (the key stopped working: offer Step 1 intake again and re-run 2b, or skip); `4` `ALL_USAGE_FAILED` (tell the user the key likely lacks Usage read, and exit with no usage profile).

## Step 3: Summarize

```bash
python3 <SKILL_BASE>/scripts/openai-usage.py summarize --capture-dir "$MIGRATION_DIR/openai-capture" --out "$MIGRATION_DIR/openai-usage-profile.json" --label proj_abc=production
```

The script reads only files the current manifest records as `ok`, refuses with `CAPTURE_NOT_COMPLETE` unless its `result` is `complete`, writes `openai-usage-profile.json`, and prints its `summary`:

- `summary.monthly_cost_usd` is the actual total for the window, never scaled up from fewer days; `metadata.active_days` and `partial_window` say when the organization has less than 30 days of spend.
- `metadata.cost_status` is `cost_unavailable` when the Costs request failed: `summary.monthly_cost_usd` is then `null`, never `0`, and token usage is still reported. A Costs request that succeeded with no spend is a real `0`. Otherwise it is `partial_window` or `complete`, as for the Anthropic usage profile.
- `usage_by_model[]` has one row per `(model, endpoint_type, batch, service_tier)` (`batch` and `service_tier` are `null` outside completions), with summed tokens and requests, the completions cache and modality fields, and a `peak`: the busiest UTC day, and for completions the busiest hour divided by 60, replaced by the sampled minute only when that minute is higher.
- `metadata.capture_warnings` names every failed or skipped file. A failed hourly or minute file makes only the peak uncertain.

## Step 4: Merge, Validate, and Clean Up

```bash
python3 <SKILL_BASE>/scripts/openai-usage.py merge --usage "$MIGRATION_DIR/openai-usage-profile.json" --profile "$MIGRATION_DIR/ai-workload-profile.json"
```

It adds each model from `usage_by_model` to the `openai`/`openai_api` source (creating it if needed) with evidence `{"provenance": "usage_api", "confidence": "high"}`, and writes the profile only when the validator accepts it. Usage reports snapshot names as OpenAI bills them (for example `gpt-4o-2024-08-06`), so a model can appear next to the alias the code uses: keep both. Code evidence is never removed.

- `GATEWAY_UPSTREAM_CONFLICT`: OpenAI is also reached through a gateway in this profile, so the source's models must match that gateway's upstream. The profile is left unchanged; tell the user the usage profile was written but its models were not added.
- `MERGE_INVALID`: the profile is left unchanged; quote the message.

The capture already deleted the key file; run `rm -f "$MIGRATION_DIR/.openai-admin-env"` anyway, and tell the user they can also revoke the key if they created it for this run.

Report: "OpenAI usage: $X over the last N days across M models (projects: …)." When `cost_status` is `cost_unavailable`, say "spend not available (the cost request failed)" instead of a dollar figure. Keep `openai-capture/` and `openai-usage-profile.json` in the run directory for later phases.

---

## Error Handling

| Situation                                         | Behavior                                                                                    |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| User declines or skips at any step, or `python3` is missing | `rm -f` the key file, then exit with no output                                    |
| `KEY_FORMAT_BAD` or `KEY_REJECTED`                | Offer intake again once, or skip                                                            |
| `KEY_INVALID_MID_RUN`                             | Offer Step 1 intake again and re-run Step 2b, or skip                                       |
| One row `failed`                                  | Continue; Step 3 lists it in `capture_warnings` and ignores the file                        |
| Costs row `failed`                                | Continue; `cost_status: "cost_unavailable"`, spend `null`, token usage kept                 |
| `ALL_USAGE_FAILED`                                | Exit with no usage profile; say which permission is likely missing                          |
| Selected projects show zero usage                 | Show the project list again once; if still zero, write the profile with zeros               |
| Resumed run, `manifest.json` `result` is `complete` | Start at Step 3; consent and capture already happened                                    |
| Resumed run, `result` is `key_invalid_mid_run`    | Consent was given: start at Step 1 intake, then Step 2                                      |
| Resumed run, `result` is `all_usage_failed`       | Consent was given: start at Step 1 intake, then Step 2. The next capture replaces these files. |

## Scope Boundary

This file covers OpenAI usage capture only. FORBIDDEN: AWS recommendations or costs; any non-GET request; any endpoint not in the Capture Endpoint Table; per-user or per-key grouping; capture of projects the user did not select; and the Admin key value anywhere outside `.openai-admin-env`.
