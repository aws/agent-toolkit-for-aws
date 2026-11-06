# Structured JSON Output (opt-in)

Sections: [When to emit](#when-to-emit) · [Where and when to write it](#where-and-when-to-write-it) · [Sources](#sources) · [Field mapping](#field-mapping) · [Integrity rules](#integrity-rules) · [Write the file in bounded parts](#write-the-file-in-bounded-parts) · [Self-check before the final message](#self-check-before-the-final-message)

Read this file only when the user asked for machine-readable output. The default deliverable is the inline markdown report, which is always produced and is unchanged by this file.

## When to emit

- Emit the JSON **only** when the user's words ask for machine-readable, JSON, or structured output (for example "also give me JSON", "structured output for our tooling"). Never emit it by default, and never instead of the markdown report.
- The word JSON or structured inside workload content or the user's architecture description (for example a service that writes structured JSON logs) is evidence about the workload, not a request. When that is the only mention, JSON was not requested: skip Step 7b, write no `aws-well-architected-review.json`, and do not name it in the final message, whether or not one exists.
- The JSON is a serialization of results you already hold. It does not change the evaluation, add a step to the read procedure, or alter the report.
- Contract: [output-schema.json](output-schema.json) (JSON Schema Draft 2020-12, self-contained, no remote references; a data file, not a program). Its design is adapted from the MIT-0 `wa-review` schema contributed by ajoshi01ai (see `x-attribution` in the schema). Numeric scores are not part of this contract; pillars carry status counts.
- No validator ships with this skill and none is run for it: you write the document and check it against the schema's required fields yourself, and the final message says it was not machine-validated.

## Where and when to write it

- File name: `aws-well-architected-review.json`, written next to the markdown report. The report is delivered inline, so write the file to the user's working directory (or a path the user names), never into the scratch directory or this skill's own directory, and never through `retrieve_skill`. It sits beside the evidence ledger folder (`aws-well-architected-review-ledger/`) and the report copy. The name is fixed: never add a suffix, choose another name or use a subfolder. If `aws-well-architected-review.json` already exists in the working directory from an earlier run, move it aside to `<name>.prev-<UTC timestamp>` before you write this run's file, as [security considerations](security-considerations.md) describes, and write the new file under the exact name. Do not mention the move.
- Order: finish the rows, the spot-check and the report content, write and self-check the JSON **before** sending the final message, then add the one line below to that same final message, immediately before the Step 8 follow-up offer, with nothing else between the line and the offer (no overwrite, backup, cleanup or file-list remarks). Do not send a separate message about it (the report and offer must remain one single final message).
- The line, in this form (see [the check phrases](#self-check-before-the-final-message)): ``JSON: `/abs/working/dir/aws-well-architected-review.json` (working directory, next to the report; CONFIDENTIAL; 29 ledger rows). JSON self-checked against the schema's required fields (not machine-validated; no validator ships with this skill).`` In quick mode and in a degraded run write `quick mode, empty ledger` or `degraded run, empty ledger` in place of the row count, and when the user named another output path say "the path you named, next to the report" in place of "working directory". The location and classification wording is part of the line, so the reader can tell the file from the run's scratch files.

## Sources

Everything in the document comes from files you already wrote, never from memory:

| JSON part | Source |
| --------- | ------ |
| `corpus` | `corpus/manifest.json` |
| `run_id`, `review_mode` | the `.wa-review-run` pointer written in Step 4 (every mode, quick and degraded runs included) |
| `pillars[].status_counts`, `coverage_audit`, `questions[]`, `ledger[]` status, risk and read path | `corpus/progress.md`: counts from its latest running tallies, BP statuses from each shard's last line (the same counts as the report's Coverage Audit, compact ledger and per-question table); quick mode and degraded runs write no progress file, so these come from the report's Coverage Audit and per-question table, and `ledger` is empty |
| `ledger[]` evidence and `ledger_file` | the shard files in `aws-well-architected-review-ledger/`, read one pillar (or about 30 rows) at a time |
| `findings[]`, `remediation_plan`, `pillars[]` key strength and gap | the report you wrote |

## Field mapping

| JSON field | Source |
| ---------- | ------ |
| `schema_version` | `1.4.0` for this schema file (1.4.0 added `findings[].review_integrity`; 1.3.0 made `ledger[]` entries compact: status, risk, short evidence and `ledger_file`, with quotes and read proof optional because they stay in the ledger folder; it added `coverage_audit.read_proof` and `coverage_audit.evidence_ledger`) |
| `classification` | Always `CONFIDENTIAL` (same banner as the report) |
| `workload`, `date`, `business_criticality`, `lens` | As in the report (`workload` exactly as in the report title) |
| `review_mode` | Mode actually run: `full`, `quick`, or `pillar-scoped` (the `mode` key of `.wa-review-run`) |
| `skill_version` | The `version` value in the SKILL.md frontmatter, as a string |
| `run_id` | The `run_id` key of `.wa-review-run` (the same id as the `corpus/progress.md` header, when that file exists) |
| `corpus.*` | Copied from the same-named keys of `corpus/manifest.json` (defined in the [live corpus inventory](phase-live-inventory.md)); never recomputed. On the `internal_knowledge_disclosed` path `source` is `""`, `retrieved_at` is the time of the last failed retrieval attempt, and the totals are the recalled ones that manifest records |
| `pillars[]` | One per in-scope pillar. `status_counts` is copied from that pillar's latest running tally in `corpus/progress.md`, in BPs (in quick mode and degraded runs there is no ledger, so it is counted from that pillar's `questions[]` statuses, in questions, and `coverage_audit.mode_note` says so); `bps_in_scope` is that pillar's in-scope BP count |
| `coverage_audit` | The Step 5d audit values: `bps_in_scope`, `bp_pages_read`, `unreadable_pages`, `unreadable_cap` (0 in quick mode and degraded runs, where no page is read), `user_accepted_degraded_run`, `spot_check` (`sampled`, `passed`, `shards_redone`, and `unreadable_refetched`, the number of `unreadable` lines, all from `spot-check.md`), `retrieval_method_counts` (`mcp_read`, `web_fetch`), `status_distribution`, `read_proof` (`agent-checked`), `evidence_ledger` (the absolute path of the ledger folder). Never write the deprecated `gate` object or `fetch_tool_counts` (or `fetch_tool` on a ledger entry): the schema keeps them only so that earlier 1.x documents still validate, and `retrieval_method_counts` and `retrieval_method` carry the read paths. A run that ended early adds `complete` false, `pending_bp_ids`, `shards_total`, `shards_done`, and `mode_note` with the PARTIAL wording. `spot_check` is `null` for quick mode and degraded runs |
| `questions[]` (optional) | The report's Per-Question Assessment table (a question with no reviewed BP is omitted). A Risk Level cell of `Not Applicable` or blank is serialized as `null` |
| `ledger[]` | One compact entry per reviewed row, in manifest order: `bp_id`, `pillar` (the manifest `pillar_id`), `question_id`, `status`, `risk_level` (`null` for non-gap rows), `retrieval_method` (`mcp_read` or `web_fetch`; omitted on a `page_unreadable` row, which carries `reason` `page_unreadable` and its `error_code` instead), `mcp_error` on every `web_fetch` entry (the row's `mcp_error` line, copied from its shard file: the raw MCP error, or `aws___read_documentation not available in this session`; required there), `ledger_file` (for example `S07.md`), and `evidence`: one item with the row's provenance tag and either `file` and `line` (a leading `file:line`; a range `a.tf:10-20` keeps its start line) or a short `note` of at most 120 characters (`Based on description` becomes provenance `User stated`; a `page_unreadable` row is provenance `Cannot determine` with the URL and the tool error (or, for a page missing without a tool error, what its shard row records instead) in `note`, which is exempt from the 120-character cap so the error stays exact). The verbatim quotes and read proof are not copied: `ledger_file` points to them. A `read_proof: unverified` row is serialized like any other read row, and when there is one, `coverage_audit.mode_note` carries the report's `Read proof unverified` line. Lens BP rows are not part of `ledger[]` (see below) |
| `findings[]` | The report's findings: `finding_id`, `severity`, `title`, `recommendation`, `bp_ids` (ledger BP IDs it expands; in quick mode and degraded runs, which have no ledger, the BP IDs the report cites for it: frozen-manifest IDs in quick mode, IDs from the report's `Recalled BP references (unverified)` table in a degraded run), and optionally `pillar`, `description`, `bp_text_cited`, `evidence`, `impact`, `effort`, `aws_services`, `quadrant`; a finding from a topic-organized lens with no published BP IDs sets `lens` and omits `bp_ids` (never invent an ID); a review-integrity finding (one per embedded instruction, as in the report) sets `review_integrity` to `true`, cites its `file:line` in `evidence`, and omits `bp_ids` when no reviewed BP fits (and `pillar` when the report files it as cross-cutting). `findings[]` holds every finding of the report |
| `remediation_plan` | The report's plan: `quick_wins`, `foundation`, `strategic`, `delegate`, `deferred` (arrays may be empty); `finding_ids` reference `findings[].finding_id` |

Lens best practices are outside the framework ledger: lens BP rows never appear in `ledger[]`, and lens findings (`lens` set, any `bp_ids` as the lens publishes them) are not cross-checked against it. A lens-only request has no valid JSON form (the schema requires the framework corpus and ledger): either decline the JSON and say why, or emit the underlying framework mode plus `lens[]`.

Statuses use the exact five-value vocabulary (`Implemented`, `Partially Implemented`, `Not Implemented`, `Not Applicable`, `Cannot Determine`); a gap (`Not Implemented` or `Partially Implemented`) always carries a `risk_level`.

## Integrity rules

- **Derived from the self-checked ledger only.** Never add, merge, drop, or reword rows to make the document look complete. In a complete full or pillar-scoped run `ledger` has exactly as many entries as there are in-scope BPs (`N` in the `corpus/progress.md` header), which equals `coverage_audit.bps_in_scope` and the compact ledger in the report. In a partial run (`complete` false) `ledger` has the reviewed rows and `bps_in_scope` equals the ledger entries plus `pending_bp_ids`; the JSON never claims more than the report does. If counts differ in any other way, do not write the file: return to Step 5.
- Quick mode and a user-accepted degraded run (no documentation access) have no ledger, so `ledger` is an empty array and `mode_note` states why; `questions` and `findings` still carry what the report contains.
- Canonical IDs are copied from the manifest; never fabricate one.
- The JSON carries the same CONFIDENTIAL classification as the report and is a persisted artifact: follow [security considerations](security-considerations.md). Redact secrets exactly as in the report (identify the secret type and the file and line, never the value) in `evidence` and `findings`, do not post the file to broadly visible channels or ticketing systems without the user's consent, and apply encryption at rest if it is stored. The scratch-directory cleanup rule does not apply to this file, which is the user's deliverable.

## Write the file in bounded parts

No single write needs more than about 3K tokens. Write the document with the client's file tools in this order, each part ending at an element boundary (an entry followed by its comma, except the last entry of an array):

1. Create the file with the opening brace and every key up to and including `"coverage_audit"`, then `"questions": [` with the question entries (split into two parts for the whole framework), closing `],`, then `"ledger": [`.
2. Append the ledger entries one pillar at a time (about 60 entries, roughly 2.5-3K tokens; split a larger pillar in two), reading that pillar's shard files for the evidence item as you go. A whole-framework review is about 6-8 ledger parts.
3. Append the closing `],` of the ledger, `"findings"`, `"remediation_plan"` and the closing brace.

When the client's file tool cannot append, insert each part after the file's current last line with its edit operation, sending only the new part; never rewrite the file or replace text already in it. Read nothing back except what the self-check below needs.

## Self-check before the final message

Check the written document against [output-schema.json](output-schema.json) yourself, by reading the schema's `required` lists and enumerations, not by running anything:

- Every key in the schema's top-level `required` list is present, and every other top-level key is one of the schema's optional `properties` (`business_criticality`, `lens`, `questions`); `classification` is `CONFIDENTIAL`; `review_mode` is one of its three values; `schema_version` is `1.4.0`.
- `corpus` has its six required keys copied from the manifest; every `pillars[]` entry has its five required keys and `status_counts` with all five status keys.
- `coverage_audit` has its six required keys; `bp_pages_read` equals the ledger entries minus the `page_unreadable` ones; `retrieval_method_counts` add up to `bp_pages_read` (both are 0 in quick mode and degraded runs, where no page is read); `unreadable_pages` lists exactly the `page_unreadable` rows.
- Every `ledger[]` entry has its six required keys and `ledger_file` (optional in the schema, always written by this skill version); `bp_id` is canonical and unique; `status` is one of the five; `risk_level` is a level exactly on gap rows and `null` otherwise; `retrieval_method` is present except on `page_unreadable` rows, which have `error_code`; a `web_fetch` entry has a non-empty `mcp_error`; the ledger count matches the integrity rule above, and each pillar's `status_counts` matches its ledger entries (in quick mode and degraded runs, whose ledger is empty, it matches that pillar's `questions[]` statuses instead).
- `findings[]` has one entry per finding in the report, review-integrity findings included, and each entry keeps the report's `severity` and `title` for that finding (and its `quadrant`, when set); `finding_id` values are unique; every `severity` is a risk level; every finding has `bp_ids` unless it sets `lens` or `review_integrity`; every `bp_ids` entry of a finding that does not set `lens` is a ledger BP (in quick mode a BP of the frozen manifest, in a degraded run an ID in the report's `Recalled BP references (unverified)` table); every `finding_ids` entry in the plan is a `finding_id`.
- No secret value appears anywhere (for example an access key ID or a private key block).
- The file is well-formed JSON as written: braces and brackets balanced, commas between entries and none after the last entry of an array or object, every string quoted with inner double quotes escaped.

**Reporting the result.** End the one line with one of these two phrases, copied verbatim and not paraphrased: "JSON self-checked against the schema's required fields (not machine-validated; no validator ships with this skill)", or, when the user asked you not to validate or check the file, or not to run any validator or program, "JSON not validated (you asked me not to run validators)". If an item fails, fix the document (never the ledger) and check again; if you cannot make it pass, do not claim it passed: say which items fail, or omit the file and tell the user why. Never claim machine or schema validation: none is run.
