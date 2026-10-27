# AI Track Record Schema

`$MIGRATION_DIR/ai-track.json` records how the Discover preflight resolved the AI track for this run. It is written once by `scripts/resolve-ai-track.py --write-run-dir "$MIGRATION_DIR"` in `discover.md` Step 0, right after `$MIGRATION_DIR` exists, for every run whose first classifier pass returned `AI_CANDIDATE: true` (and for a noncandidate when the agent chooses to record `not_applicable`). Later phases and `scripts/validate-migration-report.py --migration-dir` read this one file instead of re-deriving the sibling state.

The resolver is read-only apart from this record: it never spawns a process and never invokes another skill. Its stdout is the same object as one canonical JSON line.

## ai-track.json

The example below is the **deferred** outcome: AI evidence was found, infrastructure input exists, and the `bedrock-migration-assessment` sibling skill is not installed beside `gcp-to-aws`. The infrastructure migration proceeds; Bedrock model design, estimate, and generation are deferred and are never represented as generated.

```json
{
  "schema_version": 1,
  "ai_track": "deferred",
  "reason": "bedrock_migration_assessment_missing",
  "missing_skill": "bedrock-migration-assessment",
  "infrastructure_evidence": ["terraform"],
  "warning_code": "deferred_shared_ai_engine",
  "install_hint": "npx skills add aws/agent-toolkit-for-aws/plugins/aws-startup-advisor/skills --skill bedrock-migration-assessment",
  "ai_signal_files": ["app/llm.py"]
}
```

| Field                     | Type     | Present when   | Meaning                                                                                                                                             |
| ------------------------- | -------- | -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `schema_version`          | number   | always         | `1`                                                                                                                                                 |
| `ai_track`                | string   | always         | `"deferred"`, `"active"`, or `"not_applicable"`                                                                                                     |
| `reason`                  | string   | always         | `bedrock_migration_assessment_missing` / `bedrock_migration_assessment_present` / `no_ai_evidence`                                                  |
| `missing_skill`           | string   | deferred       | Always `"bedrock-migration-assessment"`                                                                                                             |
| `infrastructure_evidence` | string[] | deferred       | Any of `"terraform"`, `"billing"` (from the classifier `inventory`), `"resume_artifacts"` (the selected resume run holds an inventory, billing profile, or live-capture manifest) |
| `warning_code`            | string   | deferred       | Always `"deferred_shared_ai_engine"` — the code every downstream surface (Discover preview, Assumption Sheet, decision report, migration report) must carry |
| `install_hint`            | string   | deferred       | The exact `npx skills add … --skill bedrock-migration-assessment` command to show the user                                                          |
| `ai_signal_files`         | string[] | deferred       | The classifier's `ai_signal_files` (project-relative paths with AI evidence); may be empty when candidacy came from provider intent, Vertex IaC, or a durable route |
| `bma_base`                | string   | active         | Absolute path of the validated `bedrock-migration-assessment` sibling root                                                                          |

### Active outcome

The sibling `SKILL.md` is a regular file with `name: bedrock-migration-assessment` in its frontmatter. The caller then runs the existing second classifier pass with `--bma-base` exactly as before; a present-but-tampered sibling still stops with `BMA_STANDALONE_CLOSURE_INVALID` — that is never a deferral.

```json
{
  "schema_version": 1,
  "ai_track": "active",
  "reason": "bedrock_migration_assessment_present",
  "bma_base": "/abs/path/to/skills/bedrock-migration-assessment"
}
```

### Not applicable outcome

The first pass returned `AI_CANDIDATE: false`. The resolver never stats the sibling. Downstream phases behave exactly as a GCP-only run.

```json
{
  "schema_version": 1,
  "ai_track": "not_applicable",
  "reason": "no_ai_evidence"
}
```

### AI-only repository with the sibling missing

Not a record state. When the sibling is missing and there is no infrastructure evidence, the resolver writes nothing, prints `AI_TRACK_FAIL | code=bedrock_migration_assessment_missing_ai_only | missing_skill=bedrock-migration-assessment | detail=…` on stderr and exits 1. Stop the run and show the user the detail text (it names the skill and the install command).

## Downstream rules when `ai_track` is `deferred`

- Discover: do not load `discover-app-code.md`, skip the AI profile boundary, expect no AI artifact, and print the `deferred_shared_ai_engine` warning in the preview.
- Clarify: do not load the AI fragment and do not request a `BMA_AI_CLARIFY_RESULT`; the Assumption Sheet carries the row "AI track: deferred (bedrock-migration-assessment not installed)"; `preferences.json` is written without `ai_constraints`.
- Design / Estimate / Generate: never invoke `$BMA_BASE`, never emit an AI artifact, no AI estimate line, no `exec-tco`.
- Decision report: one `deferred_shared_ai_engine` callout inside `exec-assumptions`.
- Migration report: exactly one `<section id="deferred-surfaces">` naming `deferred_shared_ai_engine` and `bedrock-migration-assessment` (`generate-artifacts-report.md`); the validator enforces this from `--migration-dir`.
- `MIGRATION_GUIDE.md` / `README.md`: a "Deferred: AI workloads" subsection naming the skill, the install command, and the `ai-workload-profile.json`-less resume.
