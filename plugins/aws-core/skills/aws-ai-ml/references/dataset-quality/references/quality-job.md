# Quality Evaluation: the job (Steps 6 to 11)

This page is the quality-evaluation procedure from locating the dataset to the last job parameter. A quality evaluation of a local file or an S3 URI arrives here from `references/format-check.md` (Steps 2 to 5, the detector first). A quality evaluation of a dataset whose Dataset ARN is already known (from a manifest, the conversation, or a synthetic-dataset-generation (SDG) result handed in) starts here at Step 6; the detector has not run, so the format comes from the Dataset entity at Step 9. A spec handed in by a capability, or already in the request, starts at `references/bring-your-own-spec.md` instead. When every parameter is gathered, Step 12 (confirm the plan, choose the delivery mode, generate the code) is `references/quality-job-submit.md`.

### Step 6: Locate the dataset (for the eval job)

Steps 6 to 8 run in this order: locate, intent, register. Never offer to register or import the dataset before the intent decision of Step 7.

For this step, you need: **the dataset to evaluate.**

Note: if the user came through Format Validation (Steps 2-5) with a
local file or an S3 URI, we already have the dataset location — confirm
and reuse rather than re-asking. The three-entry-point flow below is
primarily for users who entered Quality Evaluation directly (e.g., with
a Dataset ARN surfaced from `manifests/`, conversation context, or user
input).

There are three entry points:

| Entry point | What you need |
|---|---|
| Dataset ARN already known | The ARN from a prior generation, import, or conversation context |
| Dataset in S3 | S3 URI — will need to import first |
| Local dataset file | Local path — will need to upload to S3 and import first |

If you already have a Dataset ARN from context (e.g., from SDG output or a Step 0 manifest scan), confirm it with the user and continue to Step 7. For an SDG result the ARN is the `.arn` of the `DataPreparer.generate(...)` result; the request shape for it is `references/dataset-service-api.md`, "Verify the import".

If not, discover first, in the registry and in S3, and offer the candidates you find. Registry: run `aws sagemaker list-hubs`, take the hub whose `HubDisplayName` begins `AiRegistry-` (the account's SageMaker AI Registry, `references/dataset-import.md` "Where it registers"), then run `aws sagemaker list-hub-contents --hub-name <hub> --hub-content-type DataSet` and offer the dataset names it returns; no hub means no registered datasets. S3: run `aws s3 ls` on a bucket the conversation named (or the session's default bucket). Ask the open question only when nothing is found:

> "What dataset would you like to evaluate? You can provide:
>
> - A Dataset ARN (if you've already imported or generated one)
> - An S3 URI (s3://bucket/path/to/data.jsonl)
> - A local file path"

⏸ Wait for user.

### Step 7: Evaluation intent and free-form exploratory analysis

Two things happen here. First, decide which evaluation path the user
is on. Second, on one of those paths, run the free-form exploratory
analysis before the spec exists.

**Determine the entry type:**

- **Caller already has a finished spec** (a spec file or S3 URI is in the
  request, or another capability hands one in) → record `intent = byo-spec` and
  follow `references/bring-your-own-spec.md`. Skip Steps 7–11 — that page
  confirms the plan itself and the spec is the whole evaluation.
- **SDG-generated dataset** (the Dataset entity carries a `SpecS3Uri` —
  check via `aws sagemaker describe-hub-content --hub-name <hub> --hub-content-type DataSet --hub-content-name <name>`
  or the Step 0 manifest scan) → the
  spec exists. Record `intent = spec-exists`, say nothing, and continue
  to Step 9. The exploratory analysis may still run during the job when
  included in the Step 12 plan.
- **BYOD dataset** (local file, S3 URI, or an imported ARN without a
  spec). If the user **already stated requirements** in the
  conversation ("make sure every reply addresses the message", "I want
  the character count of X", "check that…"), do not ask — record
  `intent = knows-requirements` and continue; those statements are spec
  requirements, not metric requests. A stated requirement says what a
  record or the dataset must or must not do. A request to evaluate, run,
  or report, however complete ("evaluate its quality before I fine-tune
  on it", "run it yourself and wait, then give me the results"), states
  none, and a request to run without waiting does not answer this
  question. Otherwise ask once:

> "Do you know what this data needs to satisfy — things a good record
> must or must not do, or conditions the dataset as a whole should meet?
> If so, I'll turn those into a requirements spec to evaluate against.
> If you're not sure yet, I can first explore the data for issues; then
> you tell me what to check, with the findings in front of you."

⏸ Wait for user.

- *Knows the requirements* → record `intent = knows-requirements`;
  continue to Step 8. The spec is authored at Step 10.1.
- *Unsure / wants to explore first* → record `intent = explored`; run
  the exploratory analysis now (`references/exploratory-analysis.md`), then continue to Step 8. The
  spec is still authored at Step 10.1 — the findings stay on screen as
  context while the user states their requirements.

The exploratory analysis itself (its two prerequisites, the rules for the pass, the **Exploratory Analysis** findings block and the routing after it) is `references/exploratory-analysis.md`. Read that page only on the *unsure* branch; on every other branch, continue to Step 8 (BYOD entries) or Step 9 (Dataset ARN entries, which are already registered).

### Step 8: Collect the dataset location to register

This step only applies to BYOD entries (local file or S3 URI) — Dataset
ARN entries are already registered and go straight to Step 9, after the region check at the end of this step.

The dataset quality evaluation API requires a `DatasetArn` — the dataset must be registered in the account's SageMaker AI Registry. Nothing is uploaded or registered in this step: the generated notebook does both after the user confirms the plan (Step 12), in Cell 6 (the upload, local files only) and Cell 7 (the registration, the SDK's `DataSet.create`); `references/dataset-import.md` is the import's contract. Here you collect and verify what those cells need: the location of one data file, and a Hub content name.

A dataset is one data file. The service evaluates one data file per dataset entry, and the SDK registers one file key, never a folder (`references/dataset-import.md`, "What the source must be").

**If the user has an S3 dataset (BYOD):**

- Record the full S3 URI of the data file (it fills `[DATASET_S3_URI]`) and a Hub content name for the dataset (`[HUB_CONTENT_NAME]`, the dataset name with letters, digits and hyphens unless the user names one)
- Verify access with a read call: `aws s3 ls s3://<bucket>/<key>` lists the file. If it fails, report the error and ask for a location that works.
- If the user gave a folder, list it: `aws s3 ls s3://<bucket>/<folder>/`. One data file inside means its key is the location. Several means you say, in one sentence, that the service evaluates one data file per dataset and ask which file.

**For local files:**

- Record the file path, its filename and a Hub content name as above; ask which bucket the upload goes to (`[INPUT_BUCKET]`) when the conversation has not named one
- Verify the file exists and the bucket is reachable: `aws s3 ls s3://<bucket>/`
- The location Cell 7 registers is the upload's URI, `s3://<input bucket>/byod/<hub content name>/<filename>`.

Continue to Step 9 with the dataset unregistered. The plan at Step 12 states the registration and the ARN exists only after Cell 7 runs. A Hub content name already registered in the account's SageMaker AI Registry gets a new major version at Cell 7; nothing is overwritten.

**The region check (every entry, before anything is uploaded).** The job runs in the dataset's region: the region in the Dataset ARN, or the bucket's region for a dataset the run registers (`aws s3api get-bucket-location --bucket <bucket>`; `null` means us-east-1); with neither, the session's region (`aws configure get region`, or the `AWS_REGION` variable). That region must be one of the regions `references/dataset-service-api.md` "Available regions" lists. When it is not, stop here, before the spec is written or uploaded (Step 10.1) and before the plan: say which region the dataset is in and which regions the service runs in, and that the evaluation cannot run on this dataset where it is; nothing is uploaded or registered, and the plan is not shown. The user decides what to do (a copy of the data to a bucket in a listed region, or another dataset); never move the data yourself. Step 11 item 4 carries the result into the notebook.

### Step 9: Validate format

Determine the format the dataset quality evaluation API will see. What runs depends on the entry:

- **Dataset ARN known** (the entry that starts at Step 6; the detector has not run): the format comes from the Dataset entity, as this page's intro and `../overview.md` say. Describe the entity with the `describe-hub-content` call `references/dataset-service-api.md` "Verify the import" gives and read `HubContentDocument.DatasetFileFormat`: the import wrote that field and the job reads it. No detector runs on this entry; there is no file path to run one on.
- **Local file or S3 URI** (BYOD, the location collected at Step 8): run the format detector on the dataset's path, the local file or the S3 URI Cell 7 will register (the one `[DATASET_S3_URI]` file), so the Step 4 result is re-confirmed against the data the job will read; the result fills `[DATASET_FORMAT]`. On this entry the detector output is the only source for format classification; the mandate and rules from Step 4 apply identically here.

```bash
python scripts/format_detector.py <dataset_path> --json
```

Either way the result is the format the rest of this page calls "the format from Step 9". If the format is `Custom` or `Nova_RLVR`, apply the verdict Step 5 reached (`references/format-check.md`) and the branch `references/supported-formats.md` gives for it: Custom columnar continues to Step 10 with explicit column bindings; Custom nested has no validated workflow here because the service binds flat columns only, so offer dataset-transformation to flatten first and never write transformation code inline; Nova_RLVR continues with spec-driven and exploratory evaluation only, and built-ins run only on its additional flat scalar columns (the sentence to the user is on `references/supported-formats.md`, "When the format is Nova_RLVR").

**Training volume, on either entry.** When the user said the set is for training (fine-tuning), read `training-volume-requirements.md` here, before the plan, on the Dataset ARN entry too, where `references/format-check.md` (which carries this check) does not run: count the records as that page says, and below the minimum say so before the plan, in that page's words.

**Formats supported for quality evaluation:** every format in `references/supported-formats.md` **except** `Custom` (unrecognized nested). Unrecognized columnar formats require explicit column bindings for built-ins. `Nova_RLVR`: built-ins only on additional flat columns; never on `messages` / `reference_answer`.

Read `references/format-metric-mapping.md` to check which metrics are available for the detected format.

### Step 10: Decide the evaluation

Branch on the entity and the Step 7 intent. Do not present a menu of
metric families — the families are implementation; the user's
question is whether the data is good for their use.

**SDG dataset (`intent = spec-exists`):**

> "Your dataset was generated from a spec, so we already know what it's
> supposed to satisfy. I can distill a focused dataset quality spec from it
> — the requirements, constraints, and metrics it already states — which
> you can review and extend with more checks or measurements before we
> run. Or I can evaluate against the generation spec as-is. Or, if you
> want to evaluate against something different, we write a new spec from
> scratch. Which do you prefer?"

⏸ Wait for user.

Ask this even when the user already named the evaluation families
they want ("spec plus the built-ins") — which spec is a separate choice from
which families. Skip it only if they already chose distill, as-is, or a
new spec.

- Distill (recommended) → Step 10.1 in SDG-distill mode.
- As-is → carry the entity's `SpecS3Uri` (retrieved via
  `aws sagemaker describe-hub-content --hub-name <hub> --hub-content-type DataSet --hub-content-name <name>`)
  forward to Step 12; skip Step 10.1.
- New spec → Step 10.1 in standard mode (same as BYOD). The generation
  spec is still available as grounding material.

**BYOD, `intent = knows-requirements` or `explored`** → Step 10.1.
Requirements the user stated go into the spec — never propose a
built-in metric (`character_count`, `word_count`, …) as the way to satisfy
a stated requirement; Step 10.1's overlap rule offers built-ins as an
alternative the user may take. A user who wants quality judged but
names no requirements ("is this good enough to fine-tune on?", "you decide")
is not declining the spec: `spec-authoring.md` Step 2 proposes the
qualities to judge. When
the user answers the opening question there with "no requirements" /
"just run the standard checks" and does not want quality judged
(`spec-authoring.md` Step 2), record `intent = declines-spec` and go
to Step 10.2 (curated built-ins by use case) with no `spec_eval` operation in
the request. On this path 10.2a is mandatory: parse `data_spec.md` /
`use_case_spec.md` if present, otherwise ask the quality-priorities
question (10.2a item 3), and recommend a curated subset framed to the
answer. "Standard checks" is not a request for all 10 default metrics — do not
present the full default set as the recommendation (the user may
still choose it). Both readings, proposing the qualities and declining the
spec, apply to the user's answer to the Step 7 question, never to the
opening request; the question comes first.

**After any spec decision — offer the built-ins.** The offer depends on
the format from Step 9:

*Recognized format* (has a default set in
`references/format-metric-mapping.md`):

> "Would you also like the default built-in metrics for your format —
> length, diversity, uniqueness, toxicity? They're fast and have no
> model cost."

⏸ Wait for user. Yes → Step 10.2 with the format's default deterministic
set. No → nothing added.

Make either offer even when built-ins already came up during spec
authoring — the 3b overlap exchange is about individual requirements, not
the plan.

*Custom columnar, or Nova_RLVR with additional flat columns* (no default
set — built-ins need metric selection and column bindings; on Nova_RLVR
only the flat columns are bindable — skip this offer when the record has
only `messages` and `reference_answer`, and say why):

> "Your spec is evaluated directly against your columns, so it needs no
> extra setup. Built-in metrics are also available, but there's no default
> set for this format. Want to walk through the ones that can apply to
> your columns and pick some?"

⏸ Wait for user. Yes → Step 10.2 (select) then Step 10.3 (bind). No →
nothing added.

Duplicate detection, language detection, PII detection, and taxonomy are separate
opt-ins (Step 10.2/10.4) — never bundle them into either offer.

**Judged metrics go in the spec.** There are no built-in judged metrics.
If the user asks for the built-in judge or judged
metrics (relevance, accuracy, harmful content, difficulty, …), write those
requirements into the spec instead (Step 10.1) and tell the user that is
how this workflow judges them. On the SDG as-is path this converts the run
to SDG-distill mode — say so and confirm first.

**Column binding:** after the user completes metric selection in Step 10.2, ask whether they want to use default columns or custom columns — unless the format requires explicit binding (Custom columnar; Nova_RLVR flat columns) or the selection includes `language_detection` or `pii_detection`, or any metric of `Column` or `Label` arity (`format-metric-mapping.md`: they always need a View, and the default columns bind none), in which case Step 10.3 is mandatory (for those metrics only on recognized formats). For recognized formats:
> "Your metrics will run on the default columns (prompt and completion). [If additional columns exist: Your dataset also has [list] — want to include any of those?]"

- If yes → proceed to Step 10.3 (column binding)
- If no → skip Step 10.3

### Step 10.1: Author the dataset quality spec

This step runs on every spec path from Step 10 except SDG as-is (which carries the entity's `SpecS3Uri` directly).

Read `references/spec-authoring.md` and follow it completely. Enter in **SDG-distill mode** when Step 10 chose distill; otherwise in standard mode. Its Step 3b, the built-in overlap check, is a numbered step for every requirement before the draft is shown: a requirement a deterministic built-in measures (a word or character count, a language, duplicates, toxicity) gets the cheaper-path question, "Want to use it, or keep it in the spec?", before it is written into the spec, never after. Return here when the spec is confirmed and saved to S3.

Carry forward from spec authoring:

- The spec S3 URI — for the `spec_eval` operation in Step 12
- Any requirements the user chose to cover with a built-in metric instead — add these to the metric selection in Step 10.2
- Whether a sample run was requested — carry `DownSampleRecordCount` forward to Step 12
- If the user answered the opening question with "no requirements" and does not want quality judged (`spec-authoring.md` Step 2) — record `intent = declines-spec`, return to Step 10, and continue with curated built-ins (Step 10.2); no `spec_eval` operation in the request

Then continue in this order: Step 10.2 (built-ins, when the user took the Step 10 offer), Step 10.3 when built-ins run, then Step 11 with every item in order (job name, output, role, dashboard), then the Step 12 plan on `references/quality-job-submit.md`. Step 11 is never skipped on the spec path; the plan is not written before its items are answered.

### Step 10.2: Select metrics

For this step, you need: **which metrics to run.**

This step applies when built-in metrics are part of the plan: the default built-ins add-on next to a spec, or curated built-ins when the user has no spec (`intent = declines-spec`). Skip entirely when the request is spec-only.

When a spec is in the plan: if the format has a default set in `references/format-metric-mapping.md`, recommend it and take it without a selection conversation. If it has no default set (Custom columnar; Nova_RLVR with extra flat columns), don't skip — ask whether the user wants to walk through the built-in metrics that apply to their columns; yes → 10.2a–10.2b to select, then 10.3 to bind; no → no built-ins. 10.2a–10.2b also apply to the `declines-spec` path and to picking extra metrics on request.

#### Step 10.2a: Infer metric suggestions from context

Built-in metrics are the fallback when there is no spec, not the way to honor spec requirements — anything the user wants checked against their own definition belongs in the spec (Step 10.1). Before presenting metrics on this path, check for prior context that can inform a smart recommendation:

1. **Check for `data_spec.md`** in the project directory (from SDG or earlier in the workflow). Parse:
   - Quality standards (e.g., "no toxic content" → `toxicity`)
   - Generation constraints (e.g., "diverse topics" → `keyword_topic_counts`, `data_balance`; "max 150 words" → `word_count`)

2. **If no `data_spec.md`**, check for `use_case_spec.md`. Parse success tenets and quality criteria for similar mappings.

3. **If neither exists**, ask the user what aspects of their dataset's quality matter most. The question must surface four values, in the agent's own words and in whatever form the host renders: safety and toxicity (harmful content), diversity and coverage (variety in topics, vocabulary and formatting), data hygiene (repetition, encoding issues, formatting problems), and the full default set (all of these). Say that the user can also name specific metrics directly. Ask once and wait for the answer.

#### Step 10.2b: Present metric suggestion

**If context was found (data_spec.md or use_case_spec.md):**

Recommend a **curated subset** of metrics — only those that directly map to the user's stated quality standards and constraints. Do NOT include metrics that have no clear connection to the parsed context. The recommendation should be noticeably smaller than the full default set (typically 3-8 metrics, not all 10).

Mapping examples:

- "no toxic content" / "safety" → `toxicity`
- "diverse topics" / "variety" → `ngram_diversity`, `uniqueness`, `compression_ratio`, `keyword_topic_coverage`
- "concise responses" / "max N words" → `word_count`, `character_count`
- "no repetition" / "unique" → `uniqueness`, `compression_ratio`, `ngram_diversity`
- "duplicates" / "near-duplicates" / "audit before removing" → `exact_dedup`, `fuzzy_dedup` (per-row decisions; read the results with `references/deduplication/references/result-interpretation.md`)
- "English only" / "single language" / "multilingual mix" → `language_detection`, with the target codes as `languages` when the user names them (per-row language; would-be-rejected share)
- "no personal data" / "PII" / "privacy" / "emails or phone numbers" → `pii_detection` (share of rows with PII and the entity types found, on a sample)

Present the curated recommendation with per-metric justification:

> "Based on your data spec, I'd recommend these [N] metrics:
>
> **Deterministic:** [curated list with brief reason per metric]
>
> These are targeted to your stated quality standards. Want to add more, adjust, or run the full default set (10 metrics) instead?"

🚨 Do NOT recommend the full 10-metric default set and then justify it after the fact. If the recommendation looks like the defaults, you haven't done the filtering work. A good recommendation is a focused subset that the user couldn't have arrived at without the context parsing.

**If the quality-priorities question was asked (no `data_spec.md` or `use_case_spec.md`; 10.2a item 3):**

The answer is the context. Recommend the curated subset framed to it, with a reason per metric, as "If context was found" says, using the mapping examples above; metrics the user named directly are in the recommendation as named. Only the answer "the full default set" takes the format's default set as it is: continue with "If no context" below.

**If no context — recognized format:**

Present the default set for the detected format:

List the default set for the detected format and the on-request metrics from `references/format-metric-mapping.md` (Default Metric Sets by Format Category), naming each metric; for Custom, list the text metrics and the pair metrics from the same page. End with the question "Want to add, remove, or keep the defaults?".

The families offered on request and never in the default set are listed in `references/on-request-metrics.md`, each with its View rules, cost and region; read it now, and name the family the user asked about and its one-line cost. `taxonomy` runs in us-east-1 only. Read their results with the pages those sections name (the deduplication and taxonomy sub-references, `references/result-interpretation.md` for language and PII), and hand a removal or a redaction to dataset-transformation (Step 13).

**If no context — unrecognized columnar (Custom):**

No defaults exist. Present all available metrics grouped by category, as the sentence above says, and ask which to run.

⏸ Wait for user.

#### Step 10.2c: Judged metrics

There are no built-in judged metrics. When the user asks for them, follow Step 10 ("Judged metrics go in the spec").

#### Step 10.2d: Validation rules

- If the user removes all deterministic metrics, list no metric and no `default_metrics`.
- If the user runs the full default set, send `{"Operator": "default_metrics"}` — with or without a `spec_eval` operation alongside it (see Step 12). The default set does not include `exact_dedup` / `fuzzy_dedup`: when the user adds them to the defaults, list them as their own operations next to `default_metrics`. The same applies to `language_detection` and `pii_detection`. List a default-set metric again next to `default_metrics` only with a View on another column, or, for a metric that writes no row columns (`ngram_diversity`, `uniqueness`, …), with different settings. Anything else fails the job as a duplicate run (`references/dataset-service-api.md`, run-time repeats).
- At least one operation must be present — an empty `Operations` list is rejected.

### Step 10.3: Column binding

This step applies when:

- The user chose **custom columns** for a **recognized columnar** format
- The user chose **custom columns** for a **recognized nested** format that has additional flat keys alongside `messages`
- The format is **unrecognized columnar** (Custom) — column binding is always required
- The format is **Nova_RLVR** and the user chose built-ins on its additional flat columns — bind those columns only; never `messages` or `reference_answer`

**Skip this step entirely if:**

- The user kept the **default columns** — the dataset quality evaluation job auto-binds (still bind `language_detection` and `pii_detection`, which always need one explicit column)
- The format is recognized nested with NO additional flat keys (only `messages`) — only default binding is available

#### Discover available columns

- **For a `.csv` file (any format):** the columns are the `columns` the format check reported at Step 9; do not open the file yourself. Infer what each holds from its name, and ask the user when a name does not say.
- **For a `.parquet` file:** the format check does not read it, so the columns are the names the user gave at Step 5 (the text to evaluate and, when there is one, the completion); do not open the file yourself.
- **For recognized columnar formats:** read the first record and list all flat keys.
- **For recognized nested formats with additional keys:** the bindable columns are the additional flat keys alongside `messages`. Note: `prompt`/`completion` are not directly bindable; the service derives them. Only the additional raw keys can be used with an explicit View.
- **For unrecognized columnar (Custom):** read the first 3-5 lines and list all top-level keys. Infer column types from sample values:
  - Long strings → text columns
  - Short repeating values with few unique entries → categorical columns
  - Numbers → numeric columns

Present the discovered columns:
> "Your dataset has the following columns available for binding:
>
> - [column1] (text)
> - [column2] (text)
> - [column3] (categorical — N unique values)
> - [column4] (numeric)
> ..."

#### Smart suggestions

Use column name heuristics to suggest likely role assignments:

- Columns named `prompt`, `question`, `input`, `instruction`, `query` → likely the text columns (Role `Text`)
- Columns named `completion`, `answer`, `output`, `response` → likely the completion text (Role `Text`; the second operand where a metric takes two)
- Columns with low cardinality (few distinct values) → likely **Label** columns (Role `Label`) for tabular metrics

Present suggestions but let the user confirm or override.

#### Batch binding for shared roles

Group the user's selected metrics by operand type and batch the binding questions:

**Single-operand text metrics** (word_count, character_count, compression_ratio, uniqueness, ngram_diversity, mif_score, toxicity, language_detection, plain_text_ratio, format_distribution, content_structures, exact_dedup, fuzzy_dedup, taxonomy): name the count of text metrics the user selected and ask which column or columns they evaluate, in the agent's own words and in whatever form the host renders. The question must surface the two answers and their difference: one column, on which every selected metric runs, or several columns, on each of which every selected metric runs separately (fan-out). Never bind `exact_dedup` to a column the format check's `service_note` names as holding only numbers, because it fails the whole job there (`format-check.md`, "When the output has a `service_note`").

**PII detection** (`pii_detection`): unless the user already named it, list the dataset's candidate columns from the schema detected in Step 9 and ask the user to pick the one to scan, either a chat column holding each row's turn list (bound with Role `Messages`) or a flat text column (Role `Text`). Exactly one per run; fan out to another column with a second entry.

If the user picks multiple columns, generate separate metric entries for each column (fan-out).

**MANY-arity balance metrics** (data_balance, data_balance_ratio, field_balance, field_balance_ratio — `Label` role):
> "Which columns are your categorical labels? You can pick multiple — they'll be evaluated together."

Only offer these if the dataset has categorical columns.

**Zero-operand metrics** (effectiveness):
No binding needed. Skip silently.

**Numeric column metrics** (mean, median, min, max, std_dev, percentiles, skewness, kurtosis, count_zero — `Column` role, arity MANY):
> "Which numeric column(s) should these evaluate? You can pick several — each metric reports a result per column."

Only offer these if the dataset has numeric columns. Values must be usable ints or finite floats.

**Categorical column metrics** (mode, value_frequency, count_null, count_non_numeric — `Column` role, arity MANY):
> "Which column(s) should these evaluate? You can pick several — each metric reports a result per column."

`count_null` and `count_non_numeric` accept any column and are the fastest way to spot unusable data before spending on other metrics.

🚨 **`Column`-role metrics bind many columns to ONE metric entry** — the aggregate returns per-column results. Do NOT emit one entry per column:

```json
{"Operator": "mean", "Config": {"View": [{"Role": "Column", "Column": "score"}, {"Role": "Column", "Column": "rating"}]}}
```

Fan-out (a separate entry per column) applies only to `Text`-role metrics, which take a single column each.

#### Fan-out option

Applies to `Text`-role metrics only. If the user selects one and the dataset has both a prompt-like and completion-like column:
> "Want to run [metric] on both [prompt column] and [completion column] (separate scores for each), or just one?"

- Both → generate two separate metric entries (fan-out)
- One → single entry with that column

Never fan out a `Column`-role metric — bind its columns into one entry's View instead.

⏸ Wait for user to confirm all bindings.

### Step 10.4: Metric parameters (if applicable)

After column binding, check if any selected metrics have configurable parameters. Only ask about params for metrics that have them — skip silently for metrics with no config knobs. Every param not set runs at its default.

The parameters each metric takes and their defaults are the Params column of `references/supported-metrics.md`, or of `references/on-request-metrics.md` for an on-request family; ask only about parameters whose default the user may want to change, one question per metric family. For `language_detection` that is always `languages`: omitted, there is no allowlist and no row is flagged for its language.

For each selected metric that has params, ask:
> "[metric] has a configurable [param]. Would you like to use the default ([default value]) or set a custom value?"

If the user is fine with all defaults, proceed without further questions.

### Step 11: Gather remaining parameters

Collect any missing parameters one at a time:

1. **Job name** — A base name (letters, digits, hyphens). The SDK appends a timestamp and cuts the base to about 37 characters, so keep the distinguishing part early. Suggest one based on context.
2. **Output S3 URI** — where to store the quality report. Cell 3 computes a default from `session.default_bucket()`, but when chaining from an SDG or dataset-transformation (DT) run **in this session**, **reuse the same `OUTPUT_S3_URI`** the upstream primitive used — do not recompute independently. Check conversation context or the upstream notebook's Cell 3 for the value. This ensures all pipeline outputs are co-located under a single prefix and covered by one IAM policy. When the user arrived with a bare Dataset ARN (no upstream run in this session), do not write into the dataset's own output prefix — propose the default and confirm it in the plan summary. The generated `DatasetJobConfig` MUST include `output_data_config={"S3OutputPath": OUTPUT_S3_URI}` — do not rely on the SDK fallback, which may resolve to a different path.
3. **Role ARN** — settled before the plan, never left to submit time. With none named, the SDK takes the session identity as the job's role (or the SageMaker config `RoleArn` default, when set), so read that role (`aws sts get-caller-identity`; in an assumed-role session it is the segment after `assumed-role/`) and check it the way `../../sdk-getting-started/references/execution-role-setup.md` "Validate" does: `aws iam get-role`, and the trust policy must name `sagemaker.amazonaws.com`. If it does, the identity is itself a SageMaker execution role: `[ROLE_ARN]` stays `None` and the plan says so ("the session's execution role, [role name]"), which Cell 5 prints. If it does not (an Admin role, a federated or assumed-role session, any other role), the job would fail about a minute after submit ("Unable to register credentials for customer role"): list the roles whose trust policy names `sagemaker.amazonaws.com` (`aws iam list-roles` returns each with its `AssumeRolePolicyDocument`); one qualifies, its ARN is `[ROLE_ARN]` and the plan names it; several, the user picks and never you; none, ask for an ARN as that page's "Resolve" does. A role the user named is checked the same way and used. The same role registers the dataset in Cell 7 (`references/dataset-import.md`, "The call"). A role found wanting after the plan is confirmed is a plan change: restate the plan and ask again.
4. **AWS Region** — not a question. The region was settled at Step 8 (the region check): the job runs in the dataset's region, which Cell 3 prints. Leave `REGION = ""` in Cell 3 unless the dataset's region differs from the session's; then fill it with the dataset's region. Cell 3 checks the same list and stops the notebook before any upload, registration or submit when the region is not on it.
5. **Hub** (for BYOD import only) — not a question. The dataset is registered in the account's SageMaker AI Registry, the hub the SDK's `DataSet.create` uses; the SDK creates it when the account has none (`references/dataset-import.md`, "Where it registers"). There is no hub to choose.
6. **VPC config** — not a question. Running the job in the user's own VPC is not offered: do not pass `vpc_config`; the job runs on service-managed networking.
7. **MLflow tracking config** — not a question. Logging the job to SageMaker managed MLflow is not offered: do not pass `mlflow_config`.

8. **Report visualization** *(optional)* — Ask the user whether they want an interactive dashboard of the quality report generated when the evaluation completes; the default is yes.

   - **If yes (default):** after the results are presented (Step 13), generate the dashboard per `references/report-visualization.md` without asking again.
   - **If no:** skip — the user can still ask later (Step 13).

9. **SDK state** — not a question. Before Step 12, check whether the SDK is installed as `../../sdk-getting-started/references/sagemaker-python-sdk-setup.md` says, with the Python the SDK was installed into (on a venv setup, `./.venv/bin/python`): installed means nothing to install; otherwise setup installs. The check installs nothing; the install itself waits for the Step 12 confirmation. The result makes the plan's setup sentence (`references/quality-job-submit.md`, the notice before the question) a fact, so the plan the user approves is complete and nothing is discovered after "Go".

If values are available from conversation context, an upstream SDG/DT manifest scanned in Step 0, or already configured in `SageMakerConfig` (Cell 3 displays them), confirm them rather than re-asking.

⏸ Wait for each answer.

Step 12: read `references/quality-job-submit.md`. It confirms the plan, chooses the delivery mode, generates the code and assembles the `EvaluationConfig`. No code is written and no job is submitted before its "Anything to change before I run it?" confirmation, on any path: a spec authored in `references/spec-authoring.md` or `references/structured-spec.md`, a spec the user brought, or a run the user asked for up front.

<!-- markdownlint-disable-file MD001 -->
