# Discover

Produces a validated `ai-workload-profile.json` in `$MIGRATION_DIR`, either from a profile the user supplies or by scanning their code.

The SKILL.md secret-file rule applies before Step 1: to see whether the project contains source code, list file names only, and never open `.env*` or other secret files.

## Step 1: Choose the route

- **Profile route:** the user names an existing `ai-workload-profile.json`. Only the provider-neutral contract is accepted: `schema_version` (`1.0` or `1.1`), `ai_sources[]`, and `gateways[]`, plus, in `1.1` only, the optional `integration`, `workloads[]`, `agentic_profile`, and `tool_manifest[]`.
- **Scan route:** the user points at a codebase, or the project root contains source code and no profile was named.
- If both apply, ask which one to use. If neither applies, ask for a profile path or a code directory.

## Step 2a: Profile route

1. Validate the supplied file:

   ```bash
   python3 <SKILL_BASE>/scripts/validate-ai-profile.py <path-to-profile>
   ```

2. If the script exits non-zero, stop without creating a run directory and handle the error as in Step 3.
3. On success, create `$MIGRATION_DIR` (Step 4) and copy the profile byte-for-byte to `$MIGRATION_DIR/ai-workload-profile.json`.

## Step 2b: Scan route

1. Load `references/phases/discover/discover-app-code.md` and follow it against the code directory. Read only that directory; do not read files outside it, and never open its `.env*` or other secret files.
2. If its detection gate exits without a profile, stop without creating a run directory and tell the user what it found.
3. Otherwise create `$MIGRATION_DIR` (Step 4), write the profile to `$MIGRATION_DIR/ai-workload-profile.json`, and validate it:

   ```bash
   python3 <SKILL_BASE>/scripts/validate-ai-profile.py $MIGRATION_DIR/ai-workload-profile.json
   ```

4. If validation fails, the scan wrote an inconsistent profile. Fix the profile from the scan results and validate again. Never pass a profile that fails validation to Clarify.
5. Show the user a short summary of what the scan found: each source, its models, and any gateway, then every agent, call, or endpoint the scan named as not recorded.

## Step 3: Validation errors

| `error`                         | What to tell the user                                                                                                     |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `legacy_profile_rejected`       | The file uses the older GCP-shaped layout. Use gcp-to-aws for that run, or supply a provider-neutral profile.             |
| `confirmed_confidence_rejected` | `confidence: "confirmed"` is not a level. Record user confirmation as provenance `user_confirmed` with confidence `high`. |
| `schema_violation`              | The file does not match the contract; quote the first reported path.                                                      |
| any other value                 | The profile is internally inconsistent; quote `detail`.                                                                   |

## Step 4: Create the run

1. Create `$MIGRATION_DIR`. Add `.migration/.gitignore` containing `*` if it does not exist.
2. Write `$MIGRATION_DIR/.phase-status.json` so it validates against `references/vendored/state/phase-status.schema.json`:

   ```json
   {
     "migration_id": "bma-MMDD-HHMM",
     "run_id": "[random UUID, written once]",
     "last_updated": "[ISO 8601 UTC]",
     "current_phase": "discover",
     "phases": { "discover": "in_progress", "clarify": "pending" }
   }
   ```

   Do not write `owning_skill`: this skill sends no telemetry.

3. Once the profile in `$MIGRATION_DIR` passes validation, set `phases.discover` to `"completed"` and `current_phase` to `"clarify"`, and keep the validator's JSON summary for Clarify.
