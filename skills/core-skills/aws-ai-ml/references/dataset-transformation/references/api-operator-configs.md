# API Operator Configs

**Source of truth:** the runtime operator enum and its per-operator JSON Schema
that the service uses to validate `TransformationConfig.Operations[].Config`.
The fields below come from the service's per-operator JSON Schema.

Unknown operator names and unknown Config keys are rejected **client-side, pre-submit**
— the SDK validates `Config` against a dynamic Pydantic model built from the Hub
`JobConfigSchema` (`additionalProperties:false` on every schema), raising
`DataPreparerSchemaValidationError` before the job is submitted (see
`api-execution-flow.md`, "Config-typo failure surfacing"). The service enforces the same contract as a backstop.
**Exception:** the `Config` of `LanguageFilter` and of `PiiRedaction` is not validated
pre-submit; the service rejects their unknown keys and bad values when the job runs (see
"LanguageFilter" and "PiiRedaction" below).
The skill never invents fields.

## Built-in operations

This skill covers 11 operators. **9 are built-in operations**
(below); CodeGen and custom code (BYOC) are handled by the execution flow, not as
built-in ops. All 9 are present in the operator enum AND dispatched by the
service. The enum can also hold operators this skill does not cover; never use an
operator that is not listed in this file.

**How to use this table:** it declares each operator's fields — it does not, by
itself, tell you how to build a request. To assemble a `Config` from it, follow the
procedure in `api-execution-flow.md` → "Config assembly per operation": resolve the
user's intent to an operator via `operator-name-mapping.md`, then emit **only** the
keys listed here for that operator (unknown keys are rejected), filling required
fields first. Fill known user-set values into the artifact's configuration cell and
keep placeholders only for genuinely unknown values. Keep core request assembly
parameterized through those configuration names. Per-operator specifics (e.g.
`FuzzyDedup` defaults, `Split` requires `Ratios`, `Merge` takes no Config) are in
the Notes column and the defaults below.

| Operator            | Config fields (from the enum schema)                                                                                                                                                                                                                | Required                                                                          | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `FuzzyDedup`        | `TextField` (str), `JaccardThreshold` (num 0–1), `NumPerm` (int ≥1), `NgramSize` (int ≥1)                                                                                                                                                           | —                                                                                 | Near-duplicate (MinHash). See defaults below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `ExactDedup`        | `TextField` (str), `Normalize` (bool)                                                                                                                                                                                                               | —                                                                                 | Byte/normalized-equal dedup. `Normalize` — see note below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `Split`             | `Ratios` (object, ≥2 props), `Seed` (int), `Method` (enum: `random`, `stratified`, `cluster`), `StratifyField` (required for `stratified`), `TextField` (required for `cluster`), `NumClusters` (int ≥2, for `cluster`)                             | `Ratios`; `StratifyField` if `Method=stratified`; `TextField` if `Method=cluster` | `Ratios` has NO default (required). `Seed` engine default 42. `Method` literals are **lowercase** (`random`/`stratified`/`cluster`) and the Config is validated client-side case-sensitively with `additionalProperties:false` — emit these exact literals and keys, do not capitalize or add keys. The conditionally-required keys above (`StratifyField` for `stratified`, `TextField` for `cluster`) MUST be emitted for their method or the config is rejected pre-submit. If a stratified/cluster config is ever rejected pre-submit with `DataPreparerSchemaValidationError`, re-confirm these literals against the generated runtime schema (`operator-name-mapping.md` is the sibling source) rather than hand-editing. |
| `Merge`             | _(none — `additionalProperties:false`, empty object)_                                                                                                                                                                                               | —                                                                                 | Takes NO Config. The "≥2 inputs" rule is enforced by the service, not via Config.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| `SchemaConversion`  | `TargetFormat` (enum), `EmitEvidence` (bool)                                                                                                                                                                                                        | `TargetFormat`                                                                    | `TargetFormat` ∈ {`OpenAI_Messages`, `HF_Prompt_Completion`, `Bedrock_Converse`}. Nova DPO → `Bedrock_Converse`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `SchemaFilter`      | `ExpectedFormat` (same enum), `EmitEvidence` (bool)                                                                                                                                                                                                 | —                                                                                 | Same format enum as SchemaConversion. `ExpectedFormat` optional (falls back to dataset's resolved format).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `TextQualityFilter` | `FilterType` (enum), `TextField`, `RowIdField`, `Action` (enum: `drop`), `EmitEvidence` (bool) + filter-specific ratio/length params                                                                                                                | `FilterType`                                                                      | `FilterType` ∈ {`Urls`, `Alphanumeric`, `WordRepetition`, `CharRepetition`, `Mojibake`, `CharacterLength`, `AverageLineLength`}. `Action` must be `drop`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `LanguageFilter`    | `TextField` (str), `Languages` (array of lowercase lid.176 codes), `MinScore` (num 0–1), `RowIdField` (str), `EmitEvidence` (bool, default `false`)                                                                                                 | `TextField`                                                                       | Drops rows outside the language policy. No `Action` key. Cloud API only, one flat text field. **Not validated client-side:** unknown keys and bad values fail the job when it runs, not pre-submit. See "LanguageFilter" below.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `PiiRedaction`      | `MessagesField` (str) or `TextField` (str), `DefaultAction` (enum: `tag`, `redact`, `drop`; default `tag`), `ActionMap` (object: uppercase PII entity type → `tag` / `redact` / `drop`), `RowIdField` (str), `EmitEvidence` (bool, default `false`) | exactly one of `MessagesField` / `TextField`                                      | Detects PII with a Bedrock model and tags, redacts, or drops the rows it finds it in. Cloud API only; a per-job record limit ("PiiRedaction" → Limits). **Not validated client-side:** unknown keys and bad values fail the job when it runs, not pre-submit. See "PiiRedaction" below.                                                                                                                                                                                                                                                                                                                                                                                                                                         |

## CodeGen / BYOC (capability path, not the routing decision)

| Operator  | Config fields                                             | Required                  |
| --------- | --------------------------------------------------------- | ------------------------- |
| `CodeGen` | `SpecificationS3Uri` (s3/https URI), `AutoExecute` (bool) | `SpecificationS3Uri`      |
| `BYOC`    | `TransformationCodeS3Uri` (s3 URI)                        | `TransformationCodeS3Uri` |

`BYOC` must NOT accept `AutoExecute` (that key belongs to CodeGen only; the service
rejects it). CodeGen Job 2 uses the BYOC wire operator with the approved generated
artifact; direct BYOC uses a separately authored `transformer.py`. Keep their URI
variables and templates separate (see `api-execution-flow.md`). Both templates
require an `s3://` transformation-code object URI.

## FuzzyDedup defaults — cite the RIGHT class

Defaults are NOT in the enum wire schema; they come from the engine that runs FuzzyDedup:

→ **`JaccardThreshold=0.7`, `NumPerm=128`, `NgramSize=5`**.

⚠️ Do NOT copy defaults from other MinHash implementations — they are DIFFERENT
features with different values (a separate near-duplicate-report path uses
`threshold=0.8`, which is NOT the DataTransformation operator default).

`NgramSize` counts **words, not characters** (lowercase → tokenize on non-alphanumeric
→ sliding window of N whole words → MinHash). Synthetic test data must differ by whole
words, not single characters, to be detected.

## ExactDedup `Normalize` — set by intent, do NOT blindly inherit the engine default

`ExactDedup` supports `Normalize`: `True` (the engine default) lowercases and
collapses whitespace before hashing, so case/whitespace variants dedupe together;
`False` hashes records as-is. Both paths work. Set `Normalize` by the user's intent —
do not hardcode either value, and do NOT silently inherit the engine's `True` default
when the user's words imply otherwise:

- User says **"exact" / "byte-for-byte" / "identical"** → set **`Normalize: False`**.
  The engine default of `True` is NOT byte-exact (it folds case/whitespace), so
  taking the default here would contradict the user's stated intent.
- User says **"ignore case/whitespace" / "treat near-identical as dupes"** → set
  **`Normalize: True`** (or omit to accept the default).
- Ambiguous → briefly confirm which they mean rather than guessing.

## LanguageFilter — language policy, input, and evidence

`LanguageFilter` classifies one text field per row with the FastText lid.176
model and **drops** the rows that fail the policy:

- **`Languages`** (optional): the allowlist. Non-empty, no repeats, lowercase codes
  exactly as lid.176 emits them: mostly ISO 639-1 (`en`, `fr`, `de`), plus codes such as
  `ast` and `ceb`; 176 codes are accepted. The client-side schema does not check
  LanguageFilter's `Config`, so a bad value is caught only when the job runs and fails
  it. Uppercase codes (`EN`), surrounding spaces,
  an empty list, repeats, and `unknown` are rejected. Omit the key for no allowlist.
- **`MinScore`** (optional): drop rows whose detection confidence is below it; a row
  scoring exactly `MinScore` is kept. In [0, 1]; `0` disables the threshold. The score is
  a FastText confidence, not a calibrated probability, so do not present `0.9` as
  "90% sure".
- **Undetected rows are always dropped.** A null, empty, whitespace-only, or non-string
  `TextField` value has no language (`unknown`, score `0`) and never passes. With neither
  `Languages` nor `MinScore` set, the operator drops only those rows.
- **One flat text field.** `TextField` must name a field holding plain strings. A
  `messages` / `conversations` array (or any nested or binary value) fails the job as a
  client error. For chat data, materialize a flat text field first (CodeGen path), then
  filter on it. For a show-only request, show the built-in `LanguageFilter` artifact
  against a named flat-field output (for example `chat_text`) and explain that its input
  comes from the preceding reviewed CodeGen flattening job; never set `TextField` to
  `messages` or include an unapproved CodeGen full run in the same executable flow.
- **`TextField` must exist.** If no record has the field, the job fails
  (`Config.TextField '<name>' is not present in any record`); records that lack it are
  dropped as undetected.
- Unknown Config keys are rejected by the service when the job runs (there is no pre-submit
  `DataPreparerSchemaValidationError` for LanguageFilter); model settings are service-owned and
  not exposed.

**Execution.** There is no local LanguageFilter: the model exists only in the service,
so a language filter always takes the API lane (see
`routing-and-guardrails.md`). It runs alone in its job (one operation per job; chain
other steps as separate jobs). Size: above `API_CEILING`, disclose that the
whole-file run is outside this reference's validation evidence and recommend
sharding or sampling below the ceiling. A whole-file API run is allowed only as
clearly labeled best effort after explicit confirmation. The service
sets its own LanguageFilter input cap independently; an
input it rejects for size fails the job with "Total input size N bytes exceeds
the maximum supported ... for LanguageFilter."
Expect a slower start than the other built-ins,
even on small inputs. Every LanguageFilter input or Config error found when the job runs
(bad `Languages` / `MinScore`, unknown key, missing `TextField`, chat or binary values,
evidence limits) fails the job with the same generic `ClientError:` FailureReason; the
specific message is in `report.json` in the job's output folder
(`{S3OutputPath}/data-transformation/{job_name}/{createdAt}/`, see
`api-execution-flow.md`) →
`failure_info.error_message`. Check the rules above before submitting.

**Evidence.** With `EmitEvidence: true`, `report.json` → `operations[0].row_outcomes`
holds one decision per input row, kept and dropped alike:
`{"row_id", "action": "retain" | "drop", "reason": "passed" | "flagged_by_language_detection", "details": {"operation_id": "language_detection", "lang", "lang_score"}}`.
The reason does not say which check failed; read `lang` / `lang_score` against the
policy. `row_id` is the `RowIdField` value (unique string or integer per row, at most
1,024 UTF-8 bytes) or, when `RowIdField` is omitted, the 0-based row position as a
string. With `EmitEvidence`, a dataset over the service's evidence row or size limits
fails the job; drop `EmitEvidence` or split the input.
Without `EmitEvidence`, `row_outcomes` is empty; `report.json` still carries the record
counts in `operations[0].inputs[0].records` (total) and `operations[0].outputs[0].records`
(kept); removed is the difference.

**Preview with Data Quality first.** The `dataset-quality` metric `language_detection`
(`../../dataset-quality/references/supported-metrics.md`) runs the same model and policy
without dropping anything: it reports the language mix and the share of rows that would
be removed, and its `language_detection_flagged` column marks exactly the rows this
operator drops when given the same `Languages`, `MinScore`, and text field. When the user
arrives from such a run, reuse its bound column, `languages`, and `min_score` as
`TextField`, `Languages`, and `MinScore`.

**Resolved artifact check.** Before presenting generated code, verify that the
artifact names the operator as `"LanguageFilter"` and emits the resolved values
under the exact service keys as direct literals. For an English-only request on
`review_text`, emit `"TextField": "review_text"` and `"Languages": ["en"]`;
never emit an `Action` key. For a Data Quality hand-off on `completion` with
`min_score = 0.5`, emit `"TextField": "completion"`, `"Languages": ["en"]`,
and `"MinScore": 0.5`. Do not copy the source aliases `languages` or
`min_score` into the API Config.

## PiiRedaction — PII policy, input, and evidence

This section is the home of the `PiiRedaction` contract; other files point here.

**Input** — field selection and shape

- Exactly one field. `MessagesField` names a chat field: an array of turns (`role` / `content`,
  or ShareGPT `from` / `value`), or the same array as a JSON string or wrapper object.
  `TextField` names a field holding one flat string per row; a structured value there fails
  the job as a client error (use `MessagesField`). Both or neither fails the job.
- The field must exist: if no record has it, the job fails
  (`Config.<key> '<name>' is not present in any record`).
- In a requested complete inline artifact, put known user-set values directly
  in each `PiiRedaction` Config (for example, `"TextField": "note"` and
  `"DefaultAction": "redact"`). Keep placeholders only for genuinely unknown
  values.

**Policy** — configured actions

- `tag` keeps the row unchanged (the per-row finding is only in the evidence; the report counts
  the row in `flagged`). `redact` replaces only the PII spans of the scanned field with a
  `[TYPE]` marker such as `[EMAIL]` and keeps every other field. `drop` removes the row.
- `DefaultAction` (default `tag`) applies to every entity type `ActionMap` does not name. When a
  row carries several types, the strongest action wins: `drop` > `redact` > `tag`.
- `ActionMap` (optional) overrides the action per type, keyed by the uppercase taxonomy types:
  `AGE`, `BANK_ACCOUNT_NUMBER`, `CREDENTIALS`, `CREDIT_DEBIT_CVV`, `CREDIT_DEBIT_NUMBER`,
  `DATES`, `DIGITAL_IDS`, `DRIVER_ID`, `EMAIL`, `FULL_ADDRESSES`, `GOVERNMENT_ID`,
  `GPS_COORDINATES`, `IP_ADDRESS`, `LICENSE_PLATE`, `MAC_ADDRESS`, `PARTIAL_ADDRESSES`,
  `PASSPORT_NUMBER`, `PASSWORD`, `PERSONAL_NUMBERS`, `PHONE`, `PIN`, `PRIVATE_NAMES`,
  `PRIVATE_URL`, `PUBLIC_NAMES`, `PUBLIC_URL`, `SSN`, `USERNAME`,
  `VEHICLE_IDENTIFICATION_NUMBER`. An empty object, a key that is not uppercase, or a type
  outside this list fails the job before any data is read. The service owns this taxonomy and it
  may change; when the service rejects a type, trust its message over this list.

**Fail closed under `redact` / `drop`**

- If `DefaultAction` or any `ActionMap` action is `redact` or `drop`, every row the service
  could not fully scan is dropped, even when no PII was found in it.
- Not fully scanned: a `TextField` value over 40,000 characters, or a `MessagesField` value
  whose JSON is over 40,000 characters; a non-string `TextField` value; a record with a
  repeated JSON key; a chat turn with a shape or a tool-call identifier the detector does not
  read; a row the model gave no usable answer for, or named a value in that it could not locate.
- A detection the model cannot label takes the strongest configured action.
- Under an all-`tag` policy these rows are kept unchanged and reported as unverified.
- Tell the user before a redact or drop run: the output can lose rows that hold no PII.

**Limits** (use a known record count before submitting)

- Service limits may change. When a job fails with a limit message that differs
  from this list, trust the service's message and adjust to it.
- Records: at most 10,000 per dataset. Reuse a count supplied by the user, a
  `dataset-quality` report, or a prior transformation report. For a local input
  at or below `LOCAL_CAP`, Step 2 may obtain the count with the appropriate
  parser. For an S3/Hub input or a larger local input without a known count, do
  not stream, download, or parse the dataset client-side merely to count it;
  disclose the service cap and let the service validate it. When a known count
  is above the limit, the way through is to split the dataset with a separate
  `Split` job into equal parts small enough that every part is at most
  10,000 records (`Split` divides by `Ratios`, so use N equal ratios with N = ceil(records / 9,000)
  to leave room for rounding), run one PiiRedaction job per part, and combine the redacted parts
  with `Merge` jobs if the user wants one dataset back. That is several jobs, each billed per row:
  before submitting any of them, tell the user how many jobs it takes and that every part costs a
  model call per row, and ask the user to choose between the split, sampling the dataset down to
  the limit (the output then holds just the sample), and stopping. A single job over the limit
  fails: "PiiRedaction supports at most 10000 records per dataset. Split the input into smaller
  datasets." For a show-only request for one complete inline artifact, that single artifact must
  contain the per-part `PiiRedaction` operator configured on the bound field; include the split
  staging in the same artifact, but never return a Split-only artifact with redaction only in prose.
- Row size: the 40,000-character limit above. It is applied when the job runs (fail closed), not
  checked before submitting: warn the user that over-long rows are dropped under redact or drop.
- Deadline: 6 hours per job. Reaching it fails the job and publishes no output, under any policy.
- Request budget: one per job. Exhausting it fails the job under a `redact` / `drop` policy;
  under all-`tag` the rows it could not check stay in the output as unverified.
- Input size: above `API_CEILING`, disclose that the whole-file run is outside
  this reference's validation evidence and recommend sharding or sampling below
  the ceiling. A whole-file API run is allowed only as clearly labeled best
  effort after explicit confirmation (`routing-and-guardrails.md`, step 1).
  The service sets its own PiiRedaction
  input cap independently; an input over it fails the job with "Total input size
  N bytes exceeds the maximum supported ... for PiiRedaction."

**Execution** — API lane

- There is no local PiiRedaction: detection runs only in the service, so a PII
  step always takes the API lane (see `routing-and-guardrails.md`).
- It runs alone in its job (one operation per job; chain other steps as separate jobs).
- Each row is a model call of a few seconds, so expect a long run even on small inputs. Submit
  with `transform(wait=False)` (a PiiRedaction job always meets the long-running case in
  `api-execution-flow.md` → "wait handling"), tell the user the job ARN and when it was submitted,
  and on a later turn check its status with `DataPreparer.attach(job_arn, wait=False)`
  (`job.job_status`, `job.failure_reason`); attach with `wait=True` only to collect the outputs once
  it has completed. Do not block the conversation for the whole run.

**Errors** — service failure surface

- Every input or Config error found when the job runs (everything under "Input", "Policy", and
  "Limits" except the input-size cap) fails the job with the same generic `ClientError:`
  FailureReason; the specific message is in `report.json` in the job's output folder
  (`{S3OutputPath}/data-transformation/{job_name}/{createdAt}/`, see
  `api-execution-flow.md`) →
  `failure_info.error_message`. Check the rules above before submitting.

**Evidence** (with `EmitEvidence: true`)

- Shape: `report.json` → `operations[0].row_outcomes` holds one decision per input row, kept and
  dropped alike:
  `{"row_id", "action": "retain" | "transform" | "drop", "reason": "passed" | "pii_tagged" | "pii_redacted" | "pii_dropped" | "unverified_retained" | "unverified_dropped", "details": {"operation_id": "pii_detection", "entity_types", "spans", "unverified"}}`.
- Spans: each is `{"source_id", "start", "end"}`, an offset range into the ORIGINAL text.
  `source_id` is `field:<TextField>`, or a turn address relative to the `MessagesField` value
  such as `messages[1].content`. Evidence never holds the PII text.
- Outputs still hold PII: the input dataset is never changed, a `tag` run keeps every row as it
  was, and a redact run keeps the rows it did not flag as they were. When reporting a run, give
  counts, entity types, and row ids; never quote a row's text or a PII value in chat, a report, or
  a notebook output. If the user asks to see such rows, warn that they hold PII first.
- `unverified: true` means part of the row was not checked. Under all-`tag` such a row can
  still be `pii_tagged` with types.
- `row_id` follows the same rules as for `LanguageFilter` above (`RowIdField` value, or the
  0-based position), and the same evidence row and size limits apply.
- Without `EmitEvidence`, `row_outcomes` is empty; `report.json` still carries the record counts
  in `operations[0].inputs[0].records` (total) and `operations[0].outputs[0].records` (kept);
  removed is the difference.

**Preview with Data Quality first** — estimate before mutation

- The `dataset-quality` metric `pii_detection` (`../../dataset-quality/references/supported-metrics.md`) runs the
  same detector annotate-only on a sample of rows and changes nothing: it reports
  the share of rows with PII, the entity types found, and the rows it could not fully check.
- It estimates; it does not mark the exact rows this operator acts on. Its row-size limit is
  higher than the 40,000 characters above, so rows between the two can read clean in `dataset-quality` and
  still be dropped by a redact or drop run here.
- When the user arrives from such a run, reuse its bound column as `MessagesField` (Role
  `Messages`) or `TextField` (Role `Text`), and ask which action to take, since `dataset-quality` never
  chooses one. If the user chooses the action in a later turn and then asks only for
  inline code, reuse that choice and show the artifact without asking again or running it.
- Before presenting generated code, verify that the selected action appears in
  the exact service Config. If the user chose redaction for all detected types,
  emit `"DefaultAction": "redact"`; do not silently fall back to `tag` or
  `drop`. If the user chose entity-specific redaction instead, emit those
  uppercase entity names in `ActionMap` with value `"redact"`.
