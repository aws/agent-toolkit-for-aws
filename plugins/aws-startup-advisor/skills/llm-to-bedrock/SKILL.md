---
name: llm-to-bedrock
description: "Use when the user wants to migrate code that calls OpenAI, Gemini/Google AI, or the Anthropic API to Amazon Bedrock — a pure model/SDK rewrite. End-to-end: assesses the codebase, rewrites SDK calls, evaluates output quality against Bedrock, and delivers a ready-to-merge git branch. Also has an access-only mode for users who just want to check or enable Bedrock model access for specific models (e.g. 'request access to Claude on Bedrock', 'enable GPT models on Bedrock', 'which models do I turn on') with no code migration — it checks each model and walks the right access step (Marketplace/model access and IAM) for the named models, then stops. Not for agent runtime selection or agent migration planning (use agent-advisor), nor standalone cost estimates or infra-only migration. The full migration REQUIRES gcp-to-aws installed alongside this skill (Assess is delegated to it, no standalone fallback if absent); access-only mode does not need gcp-to-aws."
---

# Migrate to Bedrock (Assess + Execute)

Single-command AI migration: OpenAI / Gemini / Anthropic → Amazon Bedrock.

**Requires the `gcp-to-aws` skill installed alongside this one.** This skill has no
standalone Assess implementation — Phase A below runs Assess by directly reading and
executing `gcp-to-aws`'s own phase instruction files in this same session (the same
inline-execution pattern `agent-advisor` uses for its `migration-plan` phase: no cross-skill
tool call, no turn boundary, and no dependency on your agent supporting a Skill/subagent
dispatch mechanism — reading a file works on any agent). There is no fallback path that
performs Assess itself if `gcp-to-aws` is missing. If you installed this skill on its own
(e.g. a single-skill `npx skills add`), install `gcp-to-aws` too before using it.

The skill base directory is given in the "Base directory for this skill: X" line the harness
emits at load time. Call it `<SKILL_BASE>`. Derived paths:

- `$SCRIPTS` = `<SKILL_BASE>/scripts`
- `$HELPERS` = `<SKILL_BASE>/references/helpers` (the former helper skills, now references)
- `$GCP_BASE` = `<SKILL_BASE>/../gcp-to-aws` — the sibling `gcp-to-aws` skill's own directory.
  Phase A reads its instruction files directly off this path; every relative reference inside
  a `gcp-to-aws` file (`references/shared/...`, `references/phases/...`, etc.) resolves under
  `$GCP_BASE`, exactly as it would if `gcp-to-aws` were running standalone.

---

## Step 0 — Check prerequisites

### 0a. Check that `uv` is available

```bash
uv --version 2>/dev/null || echo "MISSING"
```

If missing: "Install uv first — see the official install guide: https://docs.astral.sh/uv/getting-started/installation/ (e.g. `brew install uv` or `pipx install uv`)". Stop.

### 0a-bis. Route: full migration vs. access-only

This skill has two modes. Decide which the user wants **before** the gcp-to-aws check (0b) —
the access-only mode does not use `gcp-to-aws` at all, so requiring it there would block a user
who only wants access enablement.

Route to **Access-only mode** (jump to the "## Access-only mode" section below, skip 0b and
Steps 1+) when either is true:

- `$ARGUMENTS` contains an explicit access-request phrase — `model access`, `request access`,
  `enable model access`, `just access`, or `preflight` (and no source-code path). Do **not** route
  on the bare words `enable` or `access` alone — "enable the Bedrock rewrite" is a full migration,
  not an access request. When in doubt, use the AskUserQuestion below rather than the keyword. **Or**
- the user's request is about *getting Bedrock model access enabled* rather than rewriting code —
  e.g. "help me request access to Claude on Bedrock", "enable GPT models on Bedrock", "which
  models do I need to turn on", "I just want access, my engineers will do the migration".

If it is ambiguous (the user mentions both a codebase and access), **AskUserQuestion**:

> "Two things I can do — which do you want?
> [Full migration] Rewrite your OpenAI/Gemini/Anthropic calls for Bedrock end-to-end.
> [Just model access] Check and walk you through enabling Bedrock access for specific models,
> no code changes."

`[Just model access]` → Access-only mode. `[Full migration]` → continue to 0b.

Otherwise (a code path / clear rewrite intent) → continue to 0b for the full migration.

### 0b. Check that the gcp-to-aws sibling skill is installed

Phase A below runs Assess by directly reading and executing `gcp-to-aws`'s own phase
instruction files (Discover → Clarify → Design → Estimate, AI-only path) in this same
session — there is no Assess logic in this skill to fall back to. `gcp-to-aws` is a
**separate skill**, not bundled inside this one — a single-skill install (e.g. `npx skills
add ... --skill llm-to-bedrock`) does not bring it along automatically. Check for it now,
before promising the user an Assess phase this deployment cannot run:

```bash
[ -f "<SKILL_BASE>/../gcp-to-aws/SKILL.md" ] && echo GCP_TO_AWS_PRESENT || echo GCP_TO_AWS_MISSING
```

This checks the sibling directory relative to `<SKILL_BASE>` (defined above), which works
under any install path — native plugin install and `npx skills add --skill '*'` both place
`gcp-to-aws` as a sibling of this skill's own directory. It does **not** depend on
`${CLAUDE_PLUGIN_ROOT}`.

- `GCP_TO_AWS_PRESENT` → proceed to Step 1.
- `GCP_TO_AWS_MISSING` → **stop here — do not proceed.** Tell the user:

  > "This migration needs the `gcp-to-aws` skill installed alongside this one — it handles
  > code scanning, AI-workload detection, and Bedrock model design; I can't do that part myself
  > without it. `gcp-to-aws` ships in the same `aws-startup-advisor` plugin as this skill, so if
  > you installed the whole plugin it should already be next to me — it looks like only some of
  > the plugin's skills were installed. Install the pair together with:
  > `npx skills add aws/agent-toolkit-for-aws/plugins/aws-startup-advisor/skills --skill llm-to-bedrock --skill gcp-to-aws`
  > (use the same `--agent` and `--global`/project scope you used for this skill), or run that same
  > `npx skills add` command with `--skill '*'` instead of the two skill names to get every skill at
  > once. Then restart your agent and ask me to migrate again."

  **Do not** perform the Assess phase yourself as a workaround — Phase A below is explicit that
  Assess logic lives only in `gcp-to-aws`; re-implementing it here would drift out of sync with
  that skill's Discover/Clarify/Design logic over time. There is no standalone Assess for this
  skill — this check exists to fail fast and clearly, not to unlock alternate behavior.

Phase A reads `gcp-to-aws`'s files directly off disk rather than invoking it as a skill, so
there is no separate agent-capability requirement here — any agent that can read a file and
run Bash can execute this. (An earlier version of this skill invoked `gcp-to-aws` via a
cross-skill Skill-tool call; that mechanism is Claude-Code-specific and unverified elsewhere,
which is exactly why Phase A no longer uses it.)

---

## Step 1 — Collect source code path

If `$ARGUMENTS` contains a path, use it as `$REPO`. Otherwise use **AskUserQuestion**:
"Where is your source code? Enter a local path or GitHub URL."

If a GitHub URL, `git clone` it to a temp dir; use that path as `$REPO`.

**Checks on $REPO:**

1. **Git-root check** (compare resolved paths — on macOS `/tmp` resolves to `/private/tmp`,
   so a raw string comparison false-positives):

   ```bash
   [ "$(git -C <REPO> rev-parse --show-toplevel 2>/dev/null)" = "$(cd <REPO> && pwd -P)" ] && echo GIT_ROOT_OK || echo GIT_ROOT_MISMATCH
   ```

   - `GIT_ROOT_OK` → proceed.
   - `GIT_ROOT_MISMATCH` and the command errored (not a git repo at all) → tell the user the
     path must be a git repository (the deliverable is a git branch); re-ask.
   - `GIT_ROOT_MISMATCH` but inside a repo (user pointed at a subdirectory) → AskUserQuestion:
     "Use the repo root instead" (recommended) / "Continue with this subdirectory" / "Abort".

2. **Dirty-tree check:**

   ```bash
   git -C <REPO> status --porcelain
   ```

   If uncommitted changes exist, show them and AskUserQuestion: "Continue anyway" or "Let me clean up first".

Record `$REPO` for all subsequent steps.

---

## Phase A — Assess (runs gcp-to-aws's own AI-path files, inline)

**Do NOT read source code, detect AI SDKs, or ask Clarify questions yourself from scratch.**
This phase reads `gcp-to-aws`'s own phase instruction files off disk and follows them exactly
as if `gcp-to-aws` were running standalone — the same content, the same state file, the same
artifacts. The only difference from invoking `gcp-to-aws` as a separate skill is that there is
no tool call and no turn boundary: everything below runs inline, in this session.

**Path resolution.** `gcp-to-aws` instruction files use relative references
(`references/phases/...`, `references/shared/...`, `references/vendored/...`,
`references/design-refs/...`, `shared/...`, `design-refs/...`, `phases/...`,
`data/...` — including the short forms). Resolve every one of them under `$GCP_BASE`
(defined above), exactly the prefix it's written with, e.g. `shared/pricing-cache.md` →
`$GCP_BASE/references/shared/pricing-cache.md`. `$MIGRATION_DIR` is the one path that does
**not** resolve under `$GCP_BASE` — it stays under `$REPO` per gcp-to-aws's own convention
(A1 below). `gcp-to-aws`'s files are **read-only** here — this phase never edits them.

### A1 — Run Discover, Clarify, Design, and Estimate

Tell the user, before starting:

> "I'm now running the Discover → Clarify → Design → Estimate assessment (the same logic
> `gcp-to-aws` uses standalone) to detect your AI workloads and design the Bedrock migration.
> It'll ask you some questions — please answer them."

Then, in order:

1. **Resolve `$MIGRATION_DIR`.** Check for an existing `.migration/` directory at `$REPO`
   exactly as `$GCP_BASE/references/phases/discover/discover.md` Step 0 describes (list
   existing runs and offer Resume/Fresh/Cancel if any exist; otherwise create
   `$REPO/.migration/<MMDD-HHMM>/` with the current timestamp and set `$MIGRATION_DIR` to it).
   **A directory that exists but has no `.phase-status.json` yet is NOT an existing run** —
   treat it as fresh and skip discover.md's Resume/Fresh/Cancel prompt for it (same exception
   `agent-advisor`'s `migration-plan.md` Phase A documents for its own inline gcp-to-aws
   delegation). This matters here because llm-to-bedrock does not pre-create `$MIGRATION_DIR`
   before this step — but a run interrupted after this step creates the directory and before
   discover.md's Step 0 writes `.phase-status.json` would otherwise leave exactly this
   directory (present, but state-less) for a later resume, and discover.md's Resume branch
   would then try to read a `.phase-status.json` that doesn't exist.
2. **Read and execute** `$GCP_BASE/references/phases/discover/discover.md` in full, exactly
   as written, including its own Step 0 state-file initialization (skip Step 0 if resuming —
   `$MIGRATION_DIR` already has a `.phase-status.json`) and its Step 1 sub-discovery gates
   (1a–1e). Those gates already key off what's actually present in `$REPO` — IaC discovery
   only runs if Terraform files exist there, billing discovery only if billing exports exist,
   and so on; you do not need to steer it. If the source provider is OpenAI, `discover.md`'s
   own Step 1e will offer its OpenAI Admin API usage discovery
   (`discover-openai-api.md` — read-only, consent-gated, needs an Admin key with **Usage**
   set to **Read**) when applicable; accepting it gives Estimate real spend and token volumes
   without manual CSV exports.

   When Discover's Step 0 writes the run's `.phase-status.json`, it must record
   `"initiated_by": "LLM_TO_BEDROCK"` beside `owning_skill` (which stays `GCP_TO_AWS`, per
   `discover.md`'s own instruction for a run started by another skill): this run was started
   by llm-to-bedrock, and that is how telemetry attributes it.

   On `HANDOFF_OK`: at least one of `ai-workload-profile.json`, `gcp-resource-inventory.json`,
   or `billing-profile.json` is present in `$MIGRATION_DIR`.
3. **Read and execute** `$GCP_BASE/references/phases/clarify/clarify.md` in full. It routes
   itself — when `ai-workload-profile.json` is the only discovery artifact, it reads
   `clarify-ai-only.md` and runs that standalone flow; if infra artifacts also exist, it runs
   the fragment/assembler split instead. Either way, follow what it loads exactly.
   On `HANDOFF_OK`: `preferences.json` is present in `$MIGRATION_DIR`.
4. **Read and execute** `$GCP_BASE/references/phases/design/design.md` in full. It routes to
   `design-ai.md` when `ai-workload-profile.json` exists — that is the file this skill's
   Execute phase depends on. On `HANDOFF_OK`: `aws-design-ai.json` is present in
   `$MIGRATION_DIR` (plus `aws-design.json`/`aws-design-billing.json` too, if an infra or
   billing route also ran).
5. **Read and execute** `$GCP_BASE/references/phases/estimate/estimate.md` in full. You do
   **not** need to continue past Estimate — this skill only needs the Assess artifacts
   (`aws-design-ai.json`, `ai-workload-profile.json`, `preferences.json`), so once
   `estimate.md` reaches its post-Estimate decision gate, choosing **not to generate infra**
   (or simply stopping at the decision pack) is enough; you never read anything `generate.md`
   would produce (Terraform, `MIGRATION_GUIDE.md`, `migration-report.html`).

Each file above manages `$MIGRATION_DIR/.phase-status.json` itself, per its own protocol —
do not write to that file yourself, other than the `initiated_by` field named in step 2 above.
If any file's own `_postconditions`/handoff checks fail (`GATE_FAIL`), stop and show the user
exactly what that file reported; do not patch an artifact to force a gate to pass.

### A2 — Confirm Assess is complete

Since Phase A above ran every step through Estimate inline (not across separate
invocations), Assess is complete once step 5 of A1 finishes without a `GATE_FAIL`. This
check exists as a backstop in case the session was interrupted partway through A1 (e.g. the
user stopped mid-Clarify and is resuming later) — re-read `$MIGRATION_DIR/.phase-status.json`
and resume A1 at whichever step in `phases` is not yet `"completed"`, rather than restarting
from Discover.

**Before trusting that re-read, apply `gcp-to-aws/SKILL.md` § State Validation** (the same
contract A1's own phase files rely on when THEY read this state, so this wrapper-level
backstop re-read must not be held to a looser standard). In particular: if
`.phase-status.json` fails to parse (an interrupted write left it invalid — e.g. the session
was interrupted mid-write, not just mid-phase), § State Validation check 2's reconstruction
procedure is the one and only sanctioned way to recover it — infer completed phases from the
artifacts actually present in `$MIGRATION_DIR`, present the inferred status to the user for
confirmation, and rewrite `.phase-status.json` only on that confirmation. This is a narrow,
explicit exception to A1's "do not write to that file yourself" rule: `.phase-status.json`
recovery per this contract is not the same act as a phase file's own state management, and
proceeding here without it would mean this wrapper resumes on state it never validated,
unlike every phase file it delegates to.

**Workshop guard:** if `phases.workshop == "in_progress"`, `design.md`'s inner-workshop path
is actively repricing (`workshop-refresh.md` is rewriting `aws-design-ai.json` between an old
and a new mapping) — finish that loop (it resolves `phases.workshop` back to `"completed"` on
exit or decline) before treating Design as done.

### A3 — Locate Assess output

**Use the SAME `$MIGRATION_DIR` A1/A2 already resolved and confirmed — do NOT re-select a
directory here.** `$MIGRATION_DIR` is already set from A1 step 1 (and re-confirmed, not
replaced, by A2's re-read on a resumed session); re-running a "newest directory" lookup
(`ls -td "$REPO/.migration"/*/ | head -1`) at this point can select a DIFFERENT, newer run
than the one A2 just verified was complete — e.g. a sibling run whose own Design is still
in progress. B1 would then read that sibling's unfinished model map instead of the run this
phase actually assessed, with no error raised (the newer directory can genuinely contain all
three files below, just from a different, incomplete assessment). If `$MIGRATION_DIR` is
somehow unset here (it should never be, given A1/A2 above), that is a bug in this phase's own
state tracking — stop and report it rather than guessing a directory from `ls -td`.

Verify **all three** of these files exist in `$MIGRATION_DIR` (Phase B reads every one):

- `aws-design-ai.json` (model mapping + architecture)
- `ai-workload-profile.json` (detected workloads)
- `preferences.json` (user preferences from Clarify)

If **any** of the three is missing, Assess did not complete the AI path correctly — name the
missing file(s), show the error, and stop. A1 running to completion without a `GATE_FAIL`
should already guarantee this; this step is the backstop that confirms it before Execute
reads them.

**Establish this skill's own run state** (read-merge-write). This skill keeps a thin
run-state file of its own, separate from the delegated run's, so the AI migration appears in
the usage funnel under its own name. It declares its own state shape (phases `assess`,
`execute`); the shared DSL's read-merge-write rule applies. Leave the delegated run's
`.phase-status.json` untouched here: a run created by this invocation already carries
`initiated_by` (A1), and rewriting an older run's file would make its history look like new
work to the telemetry hooks.

1. Set `$BEDROCK_RUN_DIR` = `$REPO/.migration/.bedrock-<id>/`, where `<id>` is the basename
   of `$MIGRATION_DIR` (e.g. `.migration/.bedrock-0910-1100/`). The leading dot keeps it out
   of the `ls -td "$REPO/.migration"/*/` lookup above, so it can never be mistaken for the
   Assess run directory; keying it to the delegated run means a resumed migration reuses it.
   - If `$BEDROCK_RUN_DIR/.phase-status.json` already exists, this migration is being
     resumed: keep the file (including its `run_id`) and continue.
   - Otherwise create the directory and write `.phase-status.json`:

     ```json
     {
       "migration_id": ".bedrock-<id>",
       "last_updated": "<ISO 8601 now>",
       "current_phase": "execute",
       "run_id": "<fresh UUID from uuidgen>",
       "owning_skill": "LLM_TO_BEDROCK",
       "phases": { "assess": "completed", "execute": "in_progress" }
     }
     ```

   The `assess`/`execute` phase names are not in the telemetry API model yet, so only the
   run-level events (`RUN_STARTED`, `RUN_COMPLETED`) leave the machine for this run; the AI
   journey's entry point is already visible through the delegated run's events, which carry
   `initiatingSkill`.

---

## Phase B — Execute Prep

### B1 — Read Assess outputs

Read `$MIGRATION_DIR/aws-design-ai.json` and extract:

- `ai_architecture.bedrock_models[]` → array of `{source_model, aws_model_id, use_case}`
- Collect all `aws_model_id` values into `$TARGET_MODELS` (array). Keep the `use_case` of each:
  the preflight script probes each model by the right API automatically (Converse for chat,
  InvokeModel for embeddings), but the evaluator's quality scoring only applies to chat models —
  embedding targets get format/dimension validation only.

Read `$MIGRATION_DIR/ai-workload-profile.json` and extract:

- `summary.ai_source` → source provider

Read `$MIGRATION_DIR/preferences.json` and extract:

- `design_constraints.target_region` → `$REGION` (default `us-east-1` if absent)

**Validation:** If `aws-design-ai.json` has no `ai_architecture.bedrock_models[]` array, or the
array is empty, STOP: "Assess output incomplete — model mapping missing."

### B2 — AWS identity confirmation

```bash
aws sts get-caller-identity 2>&1
```

**If the command fails** (no credentials, expired SSO token): show the error and tell the user
to run `aws configure` or `aws sso login` (suggest typing `! aws sso login` to run it in this
session), then re-run B2. Do not proceed without a confirmed identity.

On success, show Account, Arn, UserId via **AskUserQuestion**:
"This AWS identity will be used for Bedrock calls. Is this correct?"

Options:

- **Yes, use this identity** → proceed
- **Use a different AWS profile** → ask which profile, record it as `$AWS_PROFILE_CHOICE`,
  re-run B2 as `aws sts get-caller-identity --profile $AWS_PROFILE_CHOICE`, and re-confirm.
  **Do NOT rely on exporting `AWS_PROFILE`** — env vars do not persist across Bash tool calls
  or into workflow subagents (see B3). Instead pass the choice explicitly everywhere:
  `--profile` on every aws CLI call, and prepend `AWS_PROFILE=$AWS_PROFILE_CHOICE` inline on
  the B4 preflight command and inside the workflow args (`awsProfile` field) so subagents can
  do the same.

Also confirm region: "Bedrock region will be `$REGION`. OK or override?"

### B3 — Source API key (optional)

First, create the artifact directory and make it self-ignoring IMMEDIATELY — before any key
exists, so the secret is never sitting in an unignored working tree (even if the user aborts
before the rewriter runs):

```bash
mkdir -p "$REPO/.saws-migrate" && printf '*\n' > "$REPO/.saws-migrate/.gitignore"
```

Determine `$KEY_ENV_VAR` from B1's source provider (this is the env-var name the baseline
skill's parser expects — a bare key without the `NAME=` prefix will NOT be parsed):

- `openai` → `OPENAI_API_KEY`
- `anthropic` → `ANTHROPIC_API_KEY`
- `google` / `gemini` → `GEMINI_API_KEY`

**The key must never enter this conversation (HARD RULE).** Do not ask the user to paste the
key in chat, and never echo, cat, or interpolate its VALUE into any command, question, or
output — the agent only ever handles the file path. If the user pastes a key into the chat
unprompted, do not use it: tell them it is now part of the transcript, recommend rotating it,
and continue with one of the paths below.

First check whether the key is already present in the shell environment (each Bash call
initializes from the user's profile, so a profile-exported key is visible to every call).
POSIX-safe — `printenv` works in bash and zsh alike (`${!VAR}` indirection is bash-only and
zsh errors on it). This prints presence only, never the value:

```bash
[ -n "$(printenv "$KEY_ENV_VAR")" ] && echo ENV_KEY_PRESENT || echo ENV_KEY_ABSENT
```

**AskUserQuestion:** "Do you have an API key for the source model (e.g. OpenAI key for GPT-4o)?
Providing it enables side-by-side quality comparison. Without it, evaluation uses absolute scoring only."

Options (offer the first only on `ENV_KEY_PRESENT`):

- **Use the `$KEY_ENV_VAR` already in my environment** → materialize env var to file in one
  command — the value never appears in the transcript:

  ```bash
  printf '%s=%s\n' "$KEY_ENV_VAR" "$(printenv "$KEY_ENV_VAR")" > "$REPO/.saws-migrate/.source-provider-env" && chmod 600 "$REPO/.saws-migrate/.source-provider-env"
  ```

  Then run the format check below and set `sourceBaselineAvailable = true`,
  `sourceKeyRef = "$REPO/.saws-migrate/.source-provider-env"`.
- **I'll write it to a file myself** → give the user this command to run in THEIR OWN terminal
  (not through the agent; in Claude Code an `!` prefix runs it in-session) — `read -rs` collects
  the key without echoing it:

  ```bash
  read -rs k && printf '%s=%s\n' "<KEY_ENV_VAR>" "$k" > "<REPO>/.saws-migrate/.source-provider-env" && chmod 600 "<REPO>/.saws-migrate/.source-provider-env" && unset k
  ```

  Substitute the literal env-var name and repo path when presenting it (those are not secrets).
  Then run the format check below and set the same flags as above.
- **Skip** → `sourceBaselineAvailable = false`, `sourceKeyRef = ""`.

Whichever path wrote the file, verify the format (never prints the key; catches a value
written without the `NAME=` prefix, which the baseline parser would silently miss):

```bash
grep -qE '^(OPENAI|ANTHROPIC|GEMINI)_API_KEY=.+' "$REPO/.saws-migrate/.source-provider-env" && echo KEY_FORMAT_OK || echo KEY_FORMAT_BAD
```

On `KEY_FORMAT_BAD`, have the same path that wrote the file rewrite it (do not echo its
contents).

(`.saws-migrate/` is already self-ignoring from the first command above; the rewriter
re-asserts this before any commit as a second layer.)

**IMPORTANT:** The file is the handoff mechanism — do NOT rely on `export` to carry the key
into later steps. Shell state set in one Bash call does not persist into other calls or into
workflow subagents; only a profile-exported variable (the `ENV_KEY_PRESENT` path above) is
reliably visible, and even that must be materialized to the file for the baseline runner.

### B4 — Bedrock preflight

```bash
uv run --project $SCRIPTS python $SCRIPTS/preflight_bedrock.py --region $REGION --models <comma-separated $TARGET_MODELS> --dataset-size 200
```

(`--dataset-size 200` matches the golden-dataset cap, so the quota warning reflects the worst case. Prefix with `AWS_PROFILE=$AWS_PROFILE_CHOICE` if B2 chose a non-default profile.)

Parse the JSON output. On failure the TOP LEVEL carries `reason`/`detail` (lifted from the
first failing model) plus `failing_models` (all failing ids); per-model verdicts are in `models[]`:

- `ok == false` + `reason: credentials` → show the detail (configure/refresh credentials), stop; user re-runs after fixing.
- `ok == false` + `reason: model_access` → model access not enabled in the Bedrock console (NOT an IAM problem): point the user at the console Model access page for the failing models, stop; re-run B4 after they enable it.
- `ok == false` + `reason: authz` → IAM denies inference. For a Converse/InvokeModel target the action to grant is `bedrock:InvokeModel`; for a mantle-only `openai.gpt-5*` target it is the `bedrock-mantle:*` set (see B4a). The `detail` names which. Tell the user the action to grant; stop.
- `ok == false` + `reason: mantle_deps_missing` → the pinned scripts environment lacks `openai` / `aws-bedrock-token-generator`, so a mantle-only target could not be probed at all. This is an environment fault, not a Bedrock verdict: tell the user to re-sync (`uv sync --project $SCRIPTS`) and stop. Do NOT proceed — access was never verified.
- `ok == false` + `reason: model_unavailable` → Read the `resolve-bedrock-model-id` reference at `$HELPERS/resolve-bedrock-model-id/resolve-bedrock-model-id.md` and follow its procedure with each ID from `failing_models` + region. AskUserQuestion with the candidates: "Use `<candidate>` (cross-region inference profile)" / "Paste a different model ID" / "Abort". On a choice, replace the ID in `$TARGET_MODELS` and re-run B4.
- `ok == false` + any other `reason` → show `detail` and stop.
- `ok == true` → proceed. Surface any `quota_warning`, and any model whose `reason` is
  `embedding_unprobed` (embedding family the preflight can't probe — remind the user to confirm
  model access in the console).

---

## Phase C — Execute

Phase C dispatches the five plugin agents sequentially via the **Agent tool** (subagent types
`aws-startup-advisor:llm2bedrock-code-analyzer`, `aws-startup-advisor:llm2bedrock-log-ingestor`, `aws-startup-advisor:llm2bedrock-prompt-evaluator`,
`aws-startup-advisor:llm2bedrock-code-rewriter`, `aws-startup-advisor:llm2bedrock-report-generator`). Each agent writes its result to
a file under `$PHASE_DIR = $REPO/.saws-migrate/phase-results/`; you validate every file with
the bundled validator before moving on. There is no workflow runtime — the files ARE the state.

### The validator (used at every step)

```bash
uv run --project $SCRIPTS python $SCRIPTS/validate_result.py --schema <analysis|ingestion|eval|rewrite|delta-decisions> <file>
```

- Exit 0 + `RESULT=valid CONTROL=ok` → phase completed; proceed.
- Exit 0 + `CONTROL=blocked REASON=<r>` → blocked flow (below).
- Exit 0 + `CONTROL=partial COMPLETED=<n> TOTAL=<m>` → partial flow (eval only).
- Exit 1 (`RESULT=invalid` + error lines) or exit 2 (file missing) → **stateless fixer retry**:
  dispatch a FRESH agent of the same type whose prompt is the original context block + the
  file path + the validator's verbatim error output + the instruction "fix ONLY the output
  file at `<path>` so it validates; do not redo the phase's work unless a required field is
  genuinely missing from it". Cap 2 retries per phase; then stop and show the errors.

### The context block (instantiated at every dispatch)

Build this exact line format (agents parse the labels). Omit lines marked optional when empty:

```
Repository: <$REPO>
AWS region: <$REGION>
AWS profile (pass as --profile / AWS_PROFILE= inline on every aws/boto3 invocation): <$AWS_PROFILE_CHOICE — omit line if default>
Target Bedrock model(s): <comma-joined $TARGET_MODELS, with any resolved overrides already applied>
Migration plan dir: <$MIGRATION_DIR>
Resolved target model id: <override for the primary chat model — omit if none>
Scripts directory (pinned uv toolchain): <$SCRIPTS>
Report date suffix: <saved suffix from run-context — C5/C6 dispatches only>
Source baseline available: <true|false>
Source provider env file: <path — omit if none>
User-supplied log files: <comma-joined — omit if none>
Golden dataset cap (max cases the ingestor may emit): 200
Phase results directory: <$PHASE_DIR>
Prior phase results (Read these files): <paths of already-validated phase JSONs>
Confirmed behavior-delta decisions file (Read it): <$PHASE_DIR/delta-decisions.json — C5 only>
<helper-reference lines — inject ONLY the ones this agent needs, per the table below>
```

Prior-phase results are passed as FILE PATHS — never inline their JSON into the prompt.

**Helper references (the former helper skills, now under `$HELPERS`).** Agents no longer
load skills by name; instead the agent Reads a helper reference at an absolute path you
inject. For each dispatch, add ONLY the helper lines that agent uses (per its `# 4` section):

| Agent (dispatch)                                             | Helper-reference lines to add                                                                                                                                                                                                                                                                                    |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1 llm2bedrock-code-analyzer                                 | `behavior-delta-detection reference: $HELPERS/behavior-delta-detection/behavior-delta-detection.md`; `resolve-bedrock-model-id reference: $HELPERS/resolve-bedrock-model-id/resolve-bedrock-model-id.md`                                                                                                         |
| C5 llm2bedrock-code-rewriter                                 | `bedrock-known-fixes reference: $HELPERS/bedrock-known-fixes/bedrock-known-fixes.md`; `behavior-delta-detection reference: $HELPERS/behavior-delta-detection/behavior-delta-detection.md`; `dependency-conflict-resolution reference: $HELPERS/dependency-conflict-resolution/dependency-conflict-resolution.md` |
| C3 llm2bedrock-prompt-evaluator                              | `bedrock-known-fixes reference: $HELPERS/bedrock-known-fixes/bedrock-known-fixes.md`; `resolve-bedrock-model-id reference: $HELPERS/resolve-bedrock-model-id/resolve-bedrock-model-id.md`; `run-source-model-baseline reference: $HELPERS/run-source-model-baseline/run-source-model-baseline.md`                |
| C2 llm2bedrock-log-ingestor, C6 llm2bedrock-report-generator | (none — these agents load no helpers)                                                                                                                                                                                                                                                                            |

Expand `$HELPERS` to its absolute path (you have `<SKILL_BASE>`) so the subagent — where
`${CLAUDE_PLUGIN_ROOT}` is empty — receives a resolvable absolute path.

### C0 — Run-context gate (resume safety)

The Eval phase makes one paid Bedrock call per golden case (and, with a source key, one paid
source-provider call per case). Before any dispatch, tell the user evaluation will invoke
Bedrock at their expense, capped at 200 cases.

1. `mkdir -p $PHASE_DIR`. Build `$PHASE_DIR/current-context.json` with exactly these fields
   (hashes via `shasum -a 256`; key hash is a fingerprint — never store the key value):

```json
{
  "repo_root": "<cd $REPO && pwd -P>",
  "migration_dir": "<$MIGRATION_DIR>",
  "region": "<$REGION>",
  "aws_profile": "<$AWS_PROFILE_CHOICE or \"\">",
  "aws_account": "<Account from B2>",
  "repo_head_sha": "<git -C $REPO rev-parse HEAD>",
  "repo_branch": "<git -C $REPO rev-parse --abbrev-ref HEAD>",
  "repo_dirty_sha256": "<sha256 of: git status --porcelain + git diff + git diff --cached, EACH with pathspecs -- . ':(exclude).saws-migrate' ':(exclude).migration' ':(exclude)MIGRATION_REPORT_*.md'; \"\" when all three are empty>",
  "target_models": [{"source_model": "...", "aws_model_id": "...", "use_case": "..."}],
  "resolved_model_overrides": {},
  "source_provider": "<from B1>",
  "source_baseline_available": <true|false from B3>,
  "source_key_sha256": "<sha256 of .source-provider-env contents, \"\" when absent>",
  "log_files": [{"path": "...", "sha256": "..."}],
  "max_golden_cases": 200,
  "assess_design_sha256": "<sha256 of $MIGRATION_DIR/aws-design-ai.json>",
  "report_date_suffix": "<date +%Y-%m-%d>",
  "schema_version": 1,
  "plugin_version": "<version from <plugin>/.claude-plugin/plugin.json>"
}
```

1. **Stage 0 (post-C5 normalization).** If `$PHASE_DIR/rewrite.json` exists and validates as
   a payload (`CONTROL=ok`), do NOT use live `repo_*` values. Run three integrity checks:
   (1) `rewrite.baseline_parent_sha` equals the SAVED `repo_head_sha`; (2) `git rev-parse
   <rewrite.branch_name>` equals `rewrite.branch_tip_sha`; (3) `git status --porcelain` (with
   the artifact exclusions) is empty. All pass → copy the saved `repo_*` values into
   current-context verbatim, continue to step 3. Check 2 fails (tip moved) → STOP and
   AskUserQuestion: "Keep your commits (regenerate report only, with a mixed-authorship note)"
   / "Reset the branch to the rewriter's tip and regenerate from C6" / "Abort". Check 3 fails
   (dirty tree) → STOP and ask: commit/stash (then re-check) or discard the edits. Check 1
   fails → treat as a full `repo_*` mismatch in step 3.

2. If `$PHASE_DIR/run-context.json` exists, compare:

```bash
uv run --project $SCRIPTS python $SCRIPTS/validate_result.py --check-run-context $PHASE_DIR/run-context.json --current $PHASE_DIR/current-context.json
```

- `RUN_CONTEXT=match` → resume: walk C1→C2→C3→(C4: delta-decisions.json)→C5→(C6: report
  file) in order; a phase counts completed iff its file validates with `CONTROL=ok` (C6:
  iff `MIGRATION_REPORT_<saved suffix>.md` exists while rewrite.json is payload-valid).
  STOP the walk at the first missing/invalid/control-state file — blocked/partial files
  route to their flows below, NEVER count as completed. Offer the user "skip completed
  phases X..Y, resume at Z". Files after an unexplained gap: archive them with the gap.
- `RUN_CONTEXT=mismatch` → scoped invalidation. Map each MISMATCH line through this table,
  archive the named units to `$REPO/.saws-migrate/phase-results-archive/<saved suffix>-$(date +%H%M%S)/`
  (a SIBLING of phase-results/ — never nest it inside), **then immediately overwrite
  run-context.json with current-context.json** (carrying forward the saved
  `report_date_suffix` unless REPORT itself is being invalidated), then re-run the
  invalidated phases in order. Tell the user which fields differed and what re-runs.

| Mismatched field(s)                                                                                                               | Archive (units)                 | Keep      |
| --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- | --------- |
| repo_root, migration_dir, region, aws_profile, aws_account, source_provider, assess_design_sha256, schema_version, plugin_version | everything                      | —         |
| repo_head_sha / repo_branch / repo_dirty_sha256                                                                                   | everything                      | —         |
| target_models / resolved_model_overrides                                                                                          | ANALYSIS, EVAL, REWRITE, REPORT | INGESTION |
| log_files / max_golden_cases                                                                                                      | everything                      | —         |
| source_key_sha256 / source_baseline_available                                                                                     | ANALYSIS, EVAL, REWRITE, REPORT | INGESTION |

Units: ANALYSIS = analysis.json · INGESTION = ingestion.json + `.saws-migrate/golden-dataset/`
· EVAL = eval.json + `.saws-migrate/eval-results/` (minus cost_compare.py) · REWRITE =
rewrite.json + delta-decisions.json · REPORT = `MIGRATION_REPORT_<saved suffix>.md`.

**Post-C5 reruns of C1–C3 need the pre-migration tree.** If rewrite.json was payload-valid
and the table invalidates ANALYSIS/INGESTION/EVAL: confirm with the user that the old
migration branch will be discarded (keep-or-reset flow first if the tip moved), then
`git checkout <saved repo_branch>`, delete the old branch and the `saws-migrate-baseline`
tag, and re-run from C1. If the user declines, stop — re-analyzing a tree that contains
the rewrite produces garbage.

1. No saved run-context → fresh run: write current-context.json as run-context.json, dispatch C1.

### C1 — Analyzer · C2 — Ingestor · C3 — Evaluator

For each phase in order, dispatch the agent with the context block (listing all
prior-phase file paths), then validate its output file:

| Step | agentType                                          | Output file                 | Schema    |
| ---- | -------------------------------------------------- | --------------------------- | --------- |
| C1   | `aws-startup-advisor:llm2bedrock-code-analyzer`    | `$PHASE_DIR/analysis.json`  | analysis  |
| C2   | `aws-startup-advisor:llm2bedrock-log-ingestor`     | `$PHASE_DIR/ingestion.json` | ingestion |
| C3   | `aws-startup-advisor:llm2bedrock-prompt-evaluator` | `$PHASE_DIR/eval.json`      | eval      |

**Blocked flow** (`CONTROL=blocked`): resolve with the user per REASON —

- `model_access` → user enables the model in the Bedrock console (nothing fingerprinted
  changes; re-dispatch the blocked phase only)
- `model_unresolvable` → user picks/pastes an ID → record it in
  `resolved_model_overrides`, fold it into the Target line
- `source_key_auth` → user supplies a new key (re-run B3) or sets baseline unavailable
- `authz` → IAM denies inference. The `detail` names the action set to grant:
  `bedrock:InvokeModel*` for a Converse target, or the `bedrock-mantle:*` actions
  (`CreateInference`, `CallWithBearerToken`) for a mantle-only `openai.gpt-5*` target.
  User fixes IAM; nothing fingerprinted changes, so re-dispatch the blocked phase only.
  Do NOT route this to `model_access` — the console Model access page is the wrong fix
  for an IAM denial and vice versa.
- `mantle_deps_missing` → the pinned scripts environment lacks `openai` /
  `aws-bedrock-token-generator`, so a mantle target could not be probed at all. User
  re-syncs (`uv sync --project $SCRIPTS`); re-dispatch the blocked phase only. Access was
  never verified, so do not treat a previous pass as still valid.
- `assess_output_missing` → re-run Phase A, then restart Phase C at C0

After ANY resolution, re-run the C0 recipe (rebuild current-context, apply the invalidation
table, overwrite run-context) and re-dispatch **from the earliest invalidated phase** — the
table, not the block location, decides where execution resumes.

**Partial flow** (eval only, `CONTROL=partial`): AskUserQuestion —

- **Continue remaining cases** → re-dispatch the evaluator with the extra context line:
  `Resume: raw_results.jsonl already contains completed cases — evaluate only prompts whose
  ids are not present in it, then re-score and overwrite eval.json`
- **Proceed with partial pass rate** → re-dispatch the evaluator with: `Finalize partial: do
  NOT call Bedrock again — score the cases already in raw_results.jsonl and emit the FULL
  eval payload over only those cases, with total_cases = the number scored and a notes prefix
  line 'partial_coverage: <completed>/<total> cases (throttled)'`. Then C4 runs normally.
- **Abort** → stop; the files stay on disk for a later C0 resume.

### C4 — Sidebar (two gates) + persist decisions

**Gate (a) — Quality go/no-go.** Read `$PHASE_DIR/eval.json`. The threshold is
**pass rate >= 0.9 AND `source_baseline_quality != 'poor'`** (with `no_golden_cases: true`
in the notes there is no quality signal — always ask). At or above → proceed silently.
Below, AskUserQuestion:

- **Proceed anyway** → gate (b)
- **Change target model** → record in `resolved_model_overrides`, re-run C0 (the table
  invalidates ANALYSIS/EVAL and execution resumes at C1). Cap: 2 retries.
- **Abort** → stop, no code touched.

**Gate (a.5) — Rewrite strategy (from migration plan).** Read `migration_path` from
`$MIGRATION_DIR/aws-design-ai.json` → `ai_architecture.code_migration.migration_path`.
If the value **starts with** `"mantle"` (`"mantle"`, `"mantle_openai_responses"`), set
`rewrite_strategy = "mantle"`. Otherwise (value is `"converse"`, `"gpt-oss"`, or the field is
absent), set `rewrite_strategy = "converse"`.
No user question needed — the decision was already made during the Assess/Design phase.

Match on the prefix, not on equality: Design writes the more specific
`"mantle_openai_responses"` for a same-model OpenAI migration, and an equality check against
`"mantle"` would silently route those runs down the Converse path — rewriting working
same-model code into a boto3 Converse client against a model that has no Converse surface.

**Gate (b) — Behavior-delta resolution.** For each `analysis.behavior_deltas[]` with
`user_visible == true`, AskUserQuestion with the options from the `behavior-delta-detection`
reference (Read `$HELPERS/behavior-delta-detection/behavior-delta-detection.md`, and the
`source_provider` sub-reference under its `references/` dir).

**Persist:** write the decisions array (entries `{delta_type, location, resolution_chosen,
source}`; `[]` when there were no user-visible deltas) to `$PHASE_DIR/delta-decisions.json`
and validate it (`--schema delta-decisions`). The file must exist before C5 — it is what
makes a C5 retry or a post-crash resume self-sufficient.

### C5 — Rewriter · C6 — Report

| Step | agentType                                          | Output                                            | Schema                                          |
| ---- | -------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------- |
| C5   | `aws-startup-advisor:llm2bedrock-code-rewriter`    | `$PHASE_DIR/rewrite.json`                         | rewrite                                         |
| C6   | `aws-startup-advisor:llm2bedrock-report-generator` | `MIGRATION_REPORT_<saved suffix>.md` in repo root | (none — file existence is the completion check) |

C5's context block includes the `Confirmed behavior-delta decisions file` line and the
`Report date suffix` line (from run-context, NOT today's date on a resume). C6's context
block lists all four phase-result file paths.

When `rewrite_strategy == "mantle"`, C5's context block ALSO includes:

- `Rewrite strategy: mantle` (omit this line entirely for Converse — its absence is the
  signal for the default Converse path)
- `Mantle model map: <source-model> -> <bedrock-model-id>` — sourced from the plan's
  `ai_architecture.bedrock_models[]` entries (each `source_model` → `aws_model_id` pair).
- `Mantle surface: responses` and `Mantle base path: /openai/v1` when any mapped
  `aws_model_id` is a proprietary GPT model (`openai.gpt-5*`). These are served only on the
  `/openai/v1` path via the Responses API — distinct from the `v1` path other mantle models
  use — so the rewriter must not emit a `/v1` base URL or a Chat Completions call for them.
  See `$GCP_BASE/references/shared/openai-on-bedrock.md`.
- `Same model: true` when `bedrock_models[].model_change` is `false`. Signals the rewriter to
  keep model parameters untouched and limit changes to the endpoint, credential, model id, and
  (if the source used Chat Completions) the surface reshape.

### C7 — Render summary

```bash
uv run --project $SCRIPTS python $SCRIPTS/render_report.py --phase-results $PHASE_DIR --repo $REPO --date-suffix <saved suffix>
```

Print the summary. Point the user at `rewrite.branch_name` (usually `bedrock-migration`, but
a collision-suffixed variant like `bedrock-migration-2` when they already had that branch)
and the report file. Tell them how to undo — substitute the ACTUAL branch name from
`rewrite.branch_name`, never a hardcoded one (on a collision run, `bedrock-migration` is the
user's own pre-existing branch and deleting it would destroy their work):

> To discard: `git checkout <your original branch>`, `git branch -D <rewrite.branch_name>`,
> `git tag -d saws-migrate-baseline`, and `rm -rf .saws-migrate .migration` removes all
> migration artifacts (including the API key file).

**Close this skill's run state** (read-merge-write on `$BEDROCK_RUN_DIR/.phase-status.json`):
set `phases.execute` to `"completed"`, `current_phase` to `"complete"`, and update
`last_updated`. This is what marks the AI migration finished in the usage funnel.

---

## Access-only mode

Entered from Step 0a-bis when the user wants Bedrock **model access** checked/enabled for a
named set of models, not a code migration. It reuses the identity check (B2) and the preflight
(B4) but takes its model list from the user, and it never touches `gcp-to-aws`, Assess, the
source key (B3), or Phase C. It answers "which models do I need to turn on, and how" — then
stops. No git branch, no rewrite.

### AC1 — Set expectations (accuracy — say this first)

Tell the user, before collecting models:

> "A few things about 'model access' on Bedrock:
>
> - **Claude, Llama, Nova, Mistral, etc.** are Bedrock foundation models on the `bedrock-runtime` endpoint — inference uses `bedrock:InvokeModel` / `Converse`. In commercial Regions, access is **on by default** once the caller has the AWS Marketplace permissions (`aws-marketplace:Subscribe` / `Unsubscribe` / `ViewSubscriptions`) — the model auto-subscribes on first invoke. The console **Model access** page is the explicit enable/catalog step (and the required flow in GovCloud). **Anthropic** models also need a one-time First-Time-Use form (`PutUseCaseForModelAccess`) per account before invoke — except when reached via `bedrock-mantle`.
> - **OpenAI on Bedrock comes in a few forms, all real** — and which endpoint they use is per-ID, not one blanket rule:
>   - *Open-weight* `gpt-oss` (`openai.gpt-oss-20b-1:0`, `openai.gpt-oss-120b-1:0`) → `bedrock-runtime` via `bedrock:InvokeModel` / `Converse` (its Responses API is also offered on `bedrock-mantle`).
>   - *Bare proprietary* GPT ids (`openai.gpt-5*`, not `gpt-oss`) → probed on the `bedrock-mantle` endpoint (Responses API).
>   - A *GPT-5.6 CRIS profile* id prefixed `us.` / `in.` / `global.` (e.g. `global.openai.gpt-5.6-sol`) → a `bedrock-runtime` target where Converse is supported.
>   - The `bedrock-mantle` path uses a **separate** action set — `bedrock-mantle:*` (e.g. the `AmazonBedrockMantleInferenceAccess` managed policy: `bedrock-mantle:CreateInference` + `CallWithBearerToken`) — distinct from `bedrock:InvokeModel`. The preflight decides per model; don't assume.
> - What is **not** on Bedrock is calling OpenAI's own hosted API at api.openai.com — that stays with OpenAI. 'GPT on Bedrock' means the AWS-served models above, reached through AWS endpoints and IAM.
>
> The preflight probes each model by the right API automatically and reports exactly which access to enable per model; I'll relay that."

### AC2 — Collect requested models and region (do NOT resolve friendly names yet)

- **Models (raw request only):** if `$ARGUMENTS` names model IDs, use them directly — skip
  resolution, they're already IDs. Otherwise **AskUserQuestion**: "Which models do you want
  access to? Give Bedrock model IDs (e.g. `anthropic.claude-sonnet-4-5-v1:0`,
  `openai.gpt-oss-120b-1:0`) or provider + name and I'll resolve the ID." Collect whatever the
  user gave (IDs and/or friendly names) into `$REQUESTED_MODELS` — **do NOT invoke the
  friendly-name resolver here.** The resolver's own commands
  (`aws bedrock list-foundation-models` / `list-inference-profiles`) require a `--region` and
  run under whatever AWS identity is active at call time — resolving before `$REGION`/AC3 are
  set means it can run against the wrong region or the default (not yet confirmed) profile
  and fail for reasons that have nothing to do with the model name.
- **Region:** **AskUserQuestion**: "Which AWS region? (default `us-east-1`)" → `$REGION`.

### AC3 — AWS identity confirmation

Run the **B2** identity-confirmation step exactly as written (including the profile-choice
handling and `$AWS_PROFILE_CHOICE`). Do not proceed without a confirmed identity.

### AC3.5 — Resolve friendly names, now that region + identity are confirmed

For any entry in `$REQUESTED_MODELS` that is not already a Bedrock model ID, resolve it now
(read `$HELPERS/resolve-bedrock-model-id/resolve-bedrock-model-id.md` and follow its
procedure) — using `$REGION` from AC2 and, if AC3 chose a non-default profile, prefixing the
resolver's own AWS CLI calls with `AWS_PROFILE=$AWS_PROFILE_CHOICE` (env vars do not persist
across Bash calls; without the prefix the resolver queries the DEFAULT identity, not the one
just confirmed). Confirm the resolved IDs back to the user. Collect the final IDs (already-ID
entries plus newly-resolved ones) into `$TARGET_MODELS`.

**If the user later changes `$REGION` or the AWS profile** (e.g. after an AC4 `authz`/
`credentials` failure prompts a re-check): re-run this resolution step for any name-based
entry before re-running AC4 — a model ID resolved against the old region/profile may not be
the right ID (or may not exist) in the new one.

### AC4 — Preflight the named models

Run the **B4** preflight against `$TARGET_MODELS` and interpret its verdicts exactly as B4
does, with these mode-specific differences:

```bash
uv run --project $SCRIPTS python $SCRIPTS/preflight_bedrock.py --region $REGION --models <comma-separated $TARGET_MODELS> --dataset-size 0
```

(`--dataset-size 0` — there is no golden dataset in this mode, so no quota-vs-dataset warning is
meaningful; a plain quota note is still surfaced if present. **Prepend
`AWS_PROFILE=$AWS_PROFILE_CHOICE` inline if AC3/B2 chose a non-default profile** — env vars do
not persist across Bash calls, so without the prefix this probes the DEFAULT identity, not the
one the user just confirmed, and a `credentials`/`authz` failure would be about the wrong
account.)

Then, per B4's branch table:

- `reason: model_access` → the model exists but access is not enabled for this account. Name the
  right prerequisite for the failing model(s):
  - **Commercial Regions:** access is on by default once the caller has the AWS Marketplace
    permissions (`aws-marketplace:Subscribe` / `Unsubscribe` / `ViewSubscriptions`) — the model
    auto-subscribes on first invoke. If those permissions are missing, that is the fix.
  - **GovCloud, third-party models (most models — check first):** GovCloud accounts are
    linked one-to-one with a commercial account, and per AWS's own docs, third-party model
    access must be enabled in **both** accounts — enabling it only in GovCloud leaves the
    account blocked. Two steps, in order:
    1. In the linked **commercial** account, in `us-east-1` or `us-west-2` (switch AWS
       identity/profile to that account first), invoke the model once (or enable it via the
       SDK/CLI as in the commercial-Regions bullet above) — this is the same auto-enable
       mechanism, just run against the commercial account rather than GovCloud. Note: entitlement
       can take a few minutes to propagate to the linked GovCloud account after this step.
    2. Switch back to the **GovCloud** identity, then use the console **Model access** page —
       always in **`us-gov-west-1`** specifically (not the inference region — GovCloud's
       Model access console page only exists in that one region, regardless of what `$REGION`
       the user is trying to invoke the model from).
    Confirm which identity/profile is active before each step; a mismatch here (acting in the
    wrong account) looks like the enablement "didn't work."
  - **GovCloud, Amazon-provided models:** only the GovCloud-account step above is needed — no
    linked commercial-account step, since Amazon models aren't third-party AWS Marketplace
    listings.
  - **Anthropic** models additionally need the one-time First-Time-Use form
    (`PutUseCaseForModelAccess`) per account before invoke — except when reached via
    `bedrock-mantle`.
  Point the user at the failing model(s) + the applicable prerequisite, and offer to re-run AC4
  after they enable it. This is the common, expected outcome for a user who came here to "get
  access."
- `reason: authz` → access is enabled but IAM denies inference. Name the action to grant — for a
  standard model `bedrock:InvokeModel`; for a mantle-only `openai.gpt-5*` target (bare proprietary
  GPT, not `gpt-oss`) the `bedrock-mantle:*` set (see **B4a**). The `detail` says which — follow it
  rather than guessing from the ID, since gpt-oss fails on `bedrock:InvokeModel`, not mantle.
- `reason: model_unavailable` → the ID isn't offered in `$REGION`. Use the
  `resolve-bedrock-model-id` procedure to suggest a cross-region inference-profile ID or a
  correct ID, re-confirm, and re-run AC4.
- `reason: credentials` / `mantle_deps_missing` / other → surface `detail` and follow B4's rule
  (fix and re-run; do not claim access is verified when it isn't).
- `ok == true` + `reason: embedding_unprobed` → the model is from an unrecognized embedding
  family, so the preflight could NOT actually invoke it (see `probe_model()` in
  `preflight_bedrock.py`) — this is `ok: true` at the JSON level but **zero requests were
  sent**, so nothing about actual access was observed either way. Do **not** report this as
  "enabled" in any form, verified or not — "enabled" asserts a fact this probe never checked.
  Tell the user **access is unverified** for this model (not "enabled — unverified"): ask
  them to confirm in the Bedrock console or with a manual test invoke before relying on it.
- `ok == true` + `reason: throttled_ok` → the probe reached the service and was throttled
  (`ThrottlingException`/`ServiceQuotaExceededException`/a 429 on mantle) — this proves the
  request was **authorized**, but it is not the same claim as "an invoke succeeded": no
  response was produced, so nothing about the model's actual behavior was observed. Tell the
  user access is **confirmed authorized, but the probe itself was throttled** — a quota
  concern to note, not a reason to distrust the access verdict.
- `ok == true` (any other `reason`, i.e. an actual invoke or InvokeModel call returned a real
  response) → tell the user access is confirmed working in `$REGION` for that ID.

### AC5 — Summarize and stop

Give the user a per-model summary: `<model_id>` → `enabled & working` (a real invoke
succeeded) / `access unverified — no request made` (`embedding_unprobed`; recommend a
manual console/test check) / `authorized (probe throttled)` (`throttled_ok`; access is
confirmed, but no response was observed) / `enable access` (naming the applicable
prerequisite from the `model_access` branch — Marketplace permissions in commercial Regions;
for GovCloud, the linked-commercial-account step (third-party models) plus the
`us-gov-west-1` console Model access page; plus the Anthropic FTU form where it applies) /
`grant <action>` / `not available in <region>, use <candidate>`. Do NOT collapse
`embedding_unprobed` or `throttled_ok` into `enabled & working` — each means something
distinct to the user (no request made / authorized-but-no-response / actually confirmed
working), and even a genuinely successful invoke on a first-time third-party model is not a
permanent guarantee either: AWS auto-enables access in the background on first invoke (up to
~15 minutes to finalize), and a missing prerequisite during that window can make a later
call fail with `AccessDeniedException` even though an earlier call succeeded — mention this
for any model reported as newly working for the first time in this account. Then run
the **Contextual offers (final step)**. Do **not** continue into Assess, rewrite, or any code
change — this mode is complete.

---

## Inline mode (platforms without an Agent/subagent dispatch tool)

If this platform has no subagent dispatch tool, run phases inline ONE AT A TIME, with a
mandatory stop between phases:

1. `Read` exactly ONE agent definition (`<plugin>/agents/<name>.md`) — never load more than
   one phase's definition into context at once.
2. Follow it start-to-finish; write and validate the same phase-result file.
3. STOP. Report the phase outcome (validator CONTROL line + one-line summary) and ask the
   user to confirm before loading the next phase's definition. This sidebar is mandatory:
   it is the context-pressure release valve, and the phase-result file means nothing is lost
   if the user continues in a fresh session instead.

Warn the user up front that inline mode is slower and context-heavier than subagent dispatch,
and that the rewriter phase performs git operations (branch, commits, worktree) directly in
this session.

---

## Failure handling

- An agent dispatch dies (tool error, terminal failure) → the phase file is missing →
  validator exit 2 → the stateless fixer-retry path (which, finding no file to fix, re-runs
  the phase). Do not auto-retry more than the 2-retry cap.
- User aborts at any gate → confirm no SOURCE CODE was modified (C5 never started if aborted
  before then). Note that `.migration/` and `.saws-migrate/` artifacts do exist; show the
  undo commands from C7 if the user wants them gone.
- Assess skill fails → show the error and stop. User can re-run `/aws-startup-advisor:llm-to-bedrock`.

## Contextual offers (final step)

> **Before you finish:** your answer is not complete until you have run the **Contextual offers (final step)** below.

This is a mandatory closing step of every final recommendation — complete it before you consider your answer done. Run this offer check inline yourself; do not depend on loading another skill. The recommendation is decided on merit first; this step never changes, re-ranks, or re-opens it, and the offer is looked up only after the advice is final.

1. Read [`../knowledge-base-for-startups/references/offers.md`](../knowledge-base-for-startups/references/offers.md) — the offer index (Offer · Summary · Keywords), one row per offer.
2. Judge relevance against what the founder actually surfaced this session. Surface an offer only if **one** holds: a **named-product match** (you recommended a specific partner product by name and it has a row); a **direct intent/component match** (an offer's Keywords directly serve a concrete workload, a component in the final recommendation, or a need the founder raised). Keep a high bar — if the match is weak, or you would be inferring an unstated need, append nothing. In this migration, only surface an offer that is a credit on a product the migration already kept or selected (e.g. LangSmith credits when the rewrite keeps their LangChain code); otherwise append none — never an offer that competes with Amazon Bedrock or anything else the rewrite or the gcp-to-aws design selects (e.g. Fireworks AI or another model-inference provider vs Bedrock).
3. If (and only if) one offer clears the bar, open only its detail file `../knowledge-base-for-startups/references/offers/<slug>.md` and append exactly **one** quiet, dismissible italic line — stating the value and condensing eligibility faithfully from that file (drop no qualifying criterion; never fabricate), with the redeem link built from the canonical `source_url` plus a `source` attribution param — append `?source=ide-startupAdvisor-<host>` (or `&source=...` if the url already has a query string), filling `<host>` from your execution environment (Claude Code → `claude`; AWS Startup Advisor IDE extension / VS Code → `vscode`; Cursor → `cursor`; Kiro → `kiro`; Codex → `codex`), or the generic `ide-startupAdvisor` when you cannot tell. Only append the query param; never change the destination. Show one or none, never a list. If none clears the bar, append nothing and do not mention offers, partner alternatives, or why none appeared.

Standard line:

```
***<Offer>** has an exclusive offer via AWS Activate — <value>, <eligibility>. [Redeem →](<source_url>?source=ide-startupAdvisor-<host>)*
```

Caps and control: at most one offer per response and often none; no more than one per five messages and two per session; show a given offer at most once per session and never one already shown, claimed, or dismissed; if the founder has muted offers, skip this step entirely. These per-five-messages, per-session, and already-shown caps are session-state limits; in a fresh session with no prior offers they are non-binding, so do not withhold an otherwise-qualifying offer merely because you cannot verify session history. See [`../contextual-offers-for-startups/SKILL.md`](../contextual-offers-for-startups/SKILL.md) for the full rules — but perform the check inline; it must not depend on that skill being loaded.
