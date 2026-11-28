# AI handoff to bedrock-migration-assessment

gcp-to-aws does not clarify, design, price, or generate AI workloads itself. When Discover wrote `ai-workload-profile.json`, the bedrock-migration-assessment skill runs those phases in combined mode, and `bma-handoff.py` checks its run and copies its artifacts into `$MIGRATION_DIR`. This file says when each gcp-to-aws phase calls it.

## Paths

- `<GCP_BASE>` is this skill's own directory, the one that holds the gcp-to-aws `SKILL.md`. A skill that runs these files inline uses its own name for that directory: `$GCP_BASE` in agent-advisor, `$ASSESS_BASE` in llm-to-bedrock.
- `HANDOFF` means `python3 <GCP_BASE>/scripts/bma-handoff.py`.
- `<BMA_BASE>` is the absolute `bma_base` path that `HANDOFF probe` prints. Run the probe once at the start of each phase that uses this file, and use that path, never one you build yourself.
- While you follow a bedrock-migration-assessment file, its `<SKILL_BASE>` is `<BMA_BASE>`, and every relative `references/...` or `scripts/...` path in it resolves under `<BMA_BASE>`, never under `<GCP_BASE>` or the skill that called gcp-to-aws.
- `$BMA_DIR` is the assessment's own run directory, `.migration/<assessment_dir>/` beside `$MIGRATION_DIR`, where `assessment_dir` is the value `host-answers` writes into `$MIGRATION_DIR/ai-handoff.json`. `$MIGRATION_DIR` stays this skill's run directory throughout.

## Step 1: Route

Clarify runs this step once, after its infrastructure questions are written to `preferences.json` (or straight away for an AI-only run); § Runs without a handoff record also runs it. Run `HANDOFF probe`, then `HANDOFF route $MIGRATION_DIR`, and follow the row for the printed `route` and `reason` (`—` when there is no `reason`):

| `route`    | `reason`                | What to do |
| ---------- | ----------------------- | ---------- |
| `no_ai`    | —                       | No AI track in this run. Skip the rest of this file in every phase. |
| `delegate` | —                       | Go to Step 2. |
| `defer`    | `bma_absent`            | Show `message`. The AI workloads are deferred: Design, Estimate, and Generate skip the AI track, and each phase summary says the AI workloads are deferred and why. |
| `defer`    | `bma_tampered`          | Show `message`. The AI workloads are deferred, as for `bma_absent`. |
| `defer`    | `user_chose_infra_only` | Show `message`. The AI workloads are deferred at the user's request, as for `bma_absent`. |
| `stop`     | `bma_required`          | Show `message` and stop the run; `phases.clarify` stays `"in_progress"`. After the user installs bedrock-migration-assessment, resuming runs this step again. |
| `stop`     | `bma_tampered`          | Show `message`. When infrastructure moves, ask whether to continue with the infrastructure only; on yes run `HANDOFF route $MIGRATION_DIR --infra-only` and follow its row. Otherwise stop the run, as for `bma_required`. |

The user can also ask to defer the AI workloads at any point before Step 4 accepts Clarify: run `HANDOFF route $MIGRATION_DIR --infra-only` and follow its row.

## Step 2: Scan and convert

1. Load `<BMA_BASE>/references/phases/discover/discover-app-code.md` and follow it against the same code directory this run's Discover read, under the same secret-file rule. Write the profile it builds to `$MIGRATION_DIR/ai-workload-profile.scan.json`, not to `ai-workload-profile.json`, which stays this skill's own profile. When its detection gate exits without a profile, skip the scan.
2. Run `HANDOFF convert $MIGRATION_DIR --scan $MIGRATION_DIR/ai-workload-profile.scan.json`, without `--scan` when step 1 wrote nothing. It adds the Vertex AI models that Terraform or Cloud Monitoring proved and writes `ai-workload-profile.neutral.json`.
3. On `no_ai_sources`, tell the user that nothing the assessment can read proves an AI source, and list `not_converted`. When infrastructure moves, run `HANDOFF route $MIGRATION_DIR --infra-only` and follow its row; otherwise stop the run. On any other error, use § Errors.

## Step 3: Start the assessment

Load `<BMA_BASE>/SKILL.md` in combined mode, with the host identifier `GCP_TO_AWS` and the absolute path of `$MIGRATION_DIR/ai-workload-profile.neutral.json`. It creates `$BMA_DIR`, runs its Discover on that profile (including its usage readers, which ask for their own consent), and returns control here when Discover completes. Do not write into `$BMA_DIR` yourself.

## Step 4: Run one assessment phase

Each gcp-to-aws phase names its `<phase>` in § Phase entry points.

1. Run `HANDOFF host-answers $MIGRATION_DIR $BMA_DIR --stop-after <phase>`. It passes this run's `target_region` and `compliance` answers and opens the handoff.
2. Resume `<BMA_BASE>/SKILL.md` on `$BMA_DIR`. Its Step 0 combined-run rules pick the phase. Relay its questions to the user and its answers back. It stops after `<phase>` and returns control here.
3. Run `HANDOFF accept $MIGRATION_DIR $BMA_DIR --through <phase>`. It re-checks the run with the assessment's `readiness.py` and copies the artifacts below into `$MIGRATION_DIR`, with each file's SHA-256 in `ai-handoff.json`. It also copies each `*-usage-profile.json` the assessment measured, unless this run's Discover already wrote one with that name.

## Phase entry points

| gcp-to-aws phase | `<phase>`  | Runs                | `accept` copies into `$MIGRATION_DIR` |
| ---------------- | ---------- | ------------------- | ------------------------------------- |
| Clarify          | `clarify`  | Steps 1 to 4        | the AI answers, merged into `preferences.json` (`ai_constraints`, startup answers) |
| Design           | `design`   | Step 4              | `aws-design-ai.json` |
| Estimate         | `estimate` | Step 4              | `estimation-ai.json` |
| Generate         | `generate` | Step 4              | `generation-ai.json` and every `ai-migration/` file it lists |

Design, Estimate, and Generate run Step 4 only when `ai-handoff.json` has a `status` other than `deferred`; with a deferred one, they skip the AI track. When `ai-workload-profile.json` exists and `ai-handoff.json` does not, they follow § Runs without a handoff record first. Generate is opt-in in this skill (`SKILL.md`, Generate is opt-in), so reaching its Step 4 means the user chose to generate; only then write `stop_after` `generate`, which is what lets the assessment run its own Generate.

## Runs without a handoff record

A run that has `ai-workload-profile.json` but no `ai-handoff.json` was started by an earlier version of this skill, which wrote its own AI files, or its handoff was withdrawn and not opened again. Before the phase that sent you here goes on:

1. List the AI files this skill wrote that are present: `aws-design-ai.json`, `estimation-ai.json`, `generation-ai.json`, and `ai-migration/`. When there are any, tell the user that the AI workloads now run in bedrock-migration-assessment, that these files are removed so they are not mixed with its results, and that the infrastructure results stay; suggest copying `ai-migration/` first. Ask them to confirm. When they do not, stop the phase and say that it continues once they confirm.
2. Run Step 1. When it stops the run, stop and keep the listed files.
3. Delete the listed files, as `handoff-gates.md` step 3 does for a route that is no longer supported. They are not copies `accept` recorded, so `route` does not remove them.
4. When Step 1 deferred the AI workloads, the phase skips the AI track. Otherwise run Steps 2 to 4 with `<phase>` `clarify`, as Clarify does, then return to the phase that sent you here. Its own Step 4 has the assessment run the earlier phases it still needs, and `accept` copies their files.

## Errors

Every command prints `{"ok": false, "error": ..., "detail": ...}` on failure. Quote `detail` and follow the row:

| `error` | What to do |
| ------- | ---------- |
| `bma_absent` | bedrock-migration-assessment was removed after Step 1. Run Step 1 again. |
| `bma_tampered` | The assessment skill or its run failed a check. Say its results cannot be used, and run Step 1 again. |
| `assessment_not_ready` | The assessment run has not finished `<phase>` (see `reason`). Resume it as in Step 4.2, then accept again. When `reason` is `host_answers_invalid`, only this skill can fix it: run Step 4.1 again instead. |
| `assessment_profile_mismatch` | `$BMA_DIR` holds another profile. Run Steps 2 to 4 again with a new assessment run. |
| `profile_changed` | Discover changed `ai-workload-profile.json`. Run Steps 1 to 4 again with a new assessment run. |
| `infrastructure_changed` | Whether infrastructure moves changed since convert. Run Steps 1 to 4 again with a new assessment run. |
| `handoff_not_open` | Convert or host-answers did not run. Go back to Step 2, or to Step 4.1. |
| `handoff_mismatch` | `$BMA_DIR` is not the run this handoff opened, or another skill started it. Use the `assessment_dir` in `ai-handoff.json`, or run Steps 2 to 4 again. |
| `handoff_unreadable` | `ai-handoff.json` is damaged. Run Step 1 again; it withdraws the old handoff. |
| `host_answers_stale` | The region or compliance answer changed after the handoff. Run Step 4 again from 4.1 with `<phase>` `clarify`. |
| `host_answers_unreadable` | The `host-answers.json` in `$BMA_DIR` is damaged. Run Step 4.1 again. |
| `accept_regressed` | This handoff already accepted a later phase. Accept that phase or a later one. |
| `preferences_missing` | An infrastructure run reached the handoff before Clarify wrote `preferences.json`. Finish the infrastructure questions first. |
| `preferences_unreadable` | `preferences.json` has a field of the wrong type. Run Clarify again. |
| `inventory_unreadable` | `gcp-resource-inventory.json` cannot be read. Run Discover again. |
| `billing_unreadable` | `billing-profile.json` cannot be read. Run Discover again. |
| `legacy_unreadable` | `ai-workload-profile.json` cannot be read. Run Discover again. |
| `legacy_invalid` | `ai-workload-profile.json` has no `models[]`. Run Discover again. |
| `scan_unreadable` | The scan file cannot be read. Run Step 2 again. |
| `scan_invalid` | The assessment's validator rejected the scan. Fix the scan from its findings and run Step 2.2 again. |
| `convert_invalid` | The converted profile was rejected. Stop and quote `detail`; this is a defect in the handoff. |
| `convert_conflict` | A gateway in the scan already routes to Vertex AI, so the Vertex AI models Terraform or Cloud Monitoring proved cannot be added safely. When infrastructure moves, offer to defer the AI workloads with `HANDOFF route $MIGRATION_DIR --infra-only`; otherwise stop and suggest running bedrock-migration-assessment on its own for this code. |
| `no_ai_sources` | See Step 2.3. |
| `unsafe_destination` | A path under `$MIGRATION_DIR` is a symbolic link. Ask the user to remove it, then accept again. |
| `destination_changed` | The user edited an `ai-migration/` file since the last accept, and the new one differs. Ask the user to copy the named file elsewhere and remove it, then accept again. |
