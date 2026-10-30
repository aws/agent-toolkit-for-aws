---
_fragment: collect
_of_phase: feedback
_contributes:
  - feedback.json
  - trace.json
---

# Collect optional feedback

Ask exactly five optional questions; every question permits `prefer not to answer`:

1. How clear was the migration assessment? (`very_clear`, `clear`, `neutral`, `unclear`, `prefer_not_to_answer`)
2. How useful were the AWS recommendations? (`very_useful`, `useful`, `neutral`, `not_useful`, `prefer_not_to_answer`)
3. How confident are you in the cost estimate? (`high`, `medium`, `low`, `prefer_not_to_answer`)
4. Which phase needs the most improvement? (`discover`, `clarify`, `design`, `estimate`, `generate`, `none`, `prefer_not_to_answer`)
5. Would you use this skill for a production migration? (`yes`, `maybe`, `no`, `prefer_not_to_answer`)

Write `feedback.json` with only `schema_version`, `skill`, `skill_version`, `host`, `answers`, `trace_included`, and timestamp. Answers use question IDs and closed enum values; do not persist free text.

Build `trace.json` only from these allowed fields:

- `schema_version`, `skill`, sanitized `skill_version`, and host in `kiro|claude-code|cursor|unknown`;
- phase outcomes using only phase names and `completed|failed|pending`;
- coarse counts keyed only by canonical Render kind, each count an integer bucket `0`, `1`, `2-5`, `6-20`, or `21+`;
- phase duration buckets `under_1m`, `1_5m`, `5_15m`, `15_60m`, `over_60m`, or `unknown`;
- validation outcome `passed`, `passed_degraded_offline`, `failed`, `not_run`, or `unknown`.

Deny all names and IDs (including migration, source-resource, workspace, project, environment, account, deploy, domain, and service identifiers), paths, domains/URLs, repository data, account/email data, configuration or environment names/values, source snippets, prompts, costs, timestamps from source artifacts, and secrets. Construct the allowlisted object from counts; never copy then redact. Before writing, recursively reject any key outside the allowlist, any string not in a closed enum, and any value matching email, URL/domain, filesystem path, Render/AWS identifier, credential, or private-key patterns.

Write both files atomically. If trace construction fails, write feedback with `trace_included: false` and no trace. If feedback persistence fails, leave no partial file and return the recoverable failure behavior to the assembler. Feedback never changes recommendations, ranking, generated files, `current_phase`, or `run_mode`.
