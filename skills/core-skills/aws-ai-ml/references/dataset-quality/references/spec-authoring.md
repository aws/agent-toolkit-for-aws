# Dataset Quality Evaluation Spec Authoring Workflow

This page governs how this capability authors a dataset quality spec with the user. Follow this
workflow on every spec path from `quality-job.md` Step 10 except SDG **as-is**
(the entity's `SpecS3Uri` is passed directly; this page is skipped).

Two modes, set by Step 10:

- **Standard mode** — the user states requirements (Steps 1–8). BYOD, or an
  SDG dataset when the user wants a new spec rather than one derived from the
  generation spec.
- **SDG-distill mode** — the dataset was generated from a spec and the user
  chose a focused dataset quality spec; Step 1 builds the draft from the generation
  spec and the flow resumes at Step 4.

---

## Step 1: Check for existing artifacts

Before asking any questions, silently check for existing context:

1. **`data_spec.md`** in the project directory — from a prior SDG run or earlier in the workflow
2. **`use_case_spec.md`** — from a prior use-case specification step
3. **SDG-generated dataset** — if the dataset ARN came from SDG (visible from Step 0 manifests or conversation context), a generation spec exists on the dataset hub entity (`SpecS3Uri`)

**Standard mode:** `data_spec.md` / `use_case_spec.md` — and, for an SDG
dataset, the generation spec — are grounding material. Surface the constraints
they contain as candidate requirements for the user to confirm, adjust, or
add to — but the user states the requirements (Step 2). When free-form exploratory analysis ran earlier in the session, keep
its findings visible while asking; do not draft requirements from them.

**SDG-distill mode:** the generation spec **is a valid dataset quality spec** — the
service reads both the same way. Distilling makes it focused:

1. Download the generation spec from the entity's `SpecS3Uri` into the project directory (the working folder of the conversation), never /tmp or the home directory.
2. Extract everything it states about the data itself — quality standards,
   constraints, verification rules, field definitions, and any quantities to
   measure — into a `## Requirements` list in plain language, one line each.
   Leave out generation mechanics (batching, prompting strategy, seed handling).
3. Name the fields each requirement reads (from the spec's output schema).
4. Present the draft at Step 4 with: "This is what your generation spec already
   requires of the data. Want to add checks or measurements, or change any?"

Skip Steps 2–3 in this mode; run 3a/3b only on requirements the user adds.

---

## Step 2: Open the conversation

Ask one question (standard mode only):

> "What should this dataset satisfy — rules every record must meet, conditions
> on the dataset as a whole, and anything you want measured or reported per
> record even without a pass/fail bar?"

⏸ Wait for user.

**Wants quality judged, names no requirements** ("evaluate the quality", "is
this good enough to fine-tune on?", "you decide", "I don't know what to check"):
do NOT drop to deterministic-only. Propose the qualities that matter for this
data and its intended use (from Step 1 grounding, the format, and what the
user said about the use), one plain-language line each — e.g. "the
response answers what the prompt asks", "the response is factually correct" —
and ask which to keep, change, or add:

> "Here's what I'd judge for this data: [list]. Keep these, change any, or add
> your own?"

⏸ Wait for user. The qualities they accept are their requirements; continue
at Step 3. Never add a quality they did not accept.

**Does not want quality judged** ("just run the standard checks", "only
length and duplicates", "no spec"): stop here and return to `quality-job.md`
Step 10.1 with `intent = declines-spec`.
Do not invent requirements on their behalf.

---

## Step 3: Build the criteria list

Through conversation, develop a list of requirements. For each requirement the
user states, do the following in order.

### 3a. Ground each requirement in the context

The user's own words are the requirement; do not replace them with a
generic definition. Make each one concrete for this dataset from:

- a few rows of the dataset (every field), to see what the task and the
  answers look like;
- `use_case_spec.md`, `data_spec.md`, and any generation spec (Step 1);
- the format — the `quality-job.md` Step 9 detector result, and whether the rows
  are single-answer questions (multiple choice, yes/no, math, extractive QA,
  SQL), open-ended answers, chat turns, or code.

Write the criterion so a judge can apply it to these rows without guessing:
"correct" on a multiple-choice set means the chosen option is the right one;
on open-ended answers it means no factual errors.

Ask one clarifying question only when this context cannot decide what the
user means:

- "accurate" → "Accurate in what sense — factually correct, addresses the question, matches a reference answer, or something else?"
- "diverse" → "What kind of diversity — topics covered, vocabulary variety, or something else?"
- "high quality" → "What does quality mean for this dataset — is it about relevance, safety, completeness, or a combination?"

### 3b. Check for built-in metric overlap

This check runs for every requirement, after it is grounded and before its
criterion is written, so before the draft of Step 4 is shown. A draft that
carries a requirement from the table below without this question having been
asked is not ready to show. For each requirement:

1. Look it up in the table below. A built-in covers the requirement only when
   its definition *matches what the user means*, not just when the name sounds
   similar ("no prompt is longer than 300 words" is `word_count`; "the prompts
   are concise" is not).
2. When one matches, ask the cheaper-path question before writing the
   criterion, as the decision rule below gives it, and wait for the answer.
3. Record the answer at 3c; the kept requirement, or the built-in, goes on
   from there.

**Built-in deterministic metrics and exactly what they measure:**

| Built-in | What it actually measures |
|---|---|
| `toxicity` | Whether the text contains harmful or offensive language — binary toxic/not_toxic per row. |
| `language_detection` | Which language each row of one flat text column is in (lid.176 code + confidence), and which rows fall outside a `languages` / `min_score` policy. |
| `pii_detection` | Whether each row of one chat or text column holds PII, and which entity types (a Bedrock model on a sample of rows, so not free). |
| `uniqueness` | What fraction of records are unique — detects duplicate or near-duplicate rows across the dataset. |
| `compression_ratio` | How compressible the text is — low ratio = repetitive phrasing, high ratio = diverse/random. |
| `ngram_diversity` | Lexical variety — ratio of unique n-grams to total, per column. |
| `word_count` | Word count per record and aggregate min/max/mean. |
| `character_count` | Character count per record and aggregate min/max/mean. |

**Decision rule — recommend, never block.** A requirement always *can* be a
spec criterion; the built-in is offered when it is the cheaper or better-defined
way to get the same thing.

- **Deterministic built-in matches** (`toxicity`, `uniqueness`, `word_count`, `character_count`, `compression_ratio`, `ngram_diversity`, `language_detection` — e.g. "every completion is in English", flat text columns only) → recommend it as the cheaper path. Say: "The built-in `[metric]` measures exactly that at no model cost. Want to use it, or keep it in the spec?" Either answer is fine. If they keep it in the spec and it has no pass/fail bar, it becomes a **metric criterion** (see below).
- **No deterministic match** → spec criterion in the user's words, like any other requirement.
- **PII presence** ("no personal data in the completions") → offer the built-in `pii_detection` alongside a pattern-based code criterion and ask the user to choose: the built-in also finds names and addresses that patterns miss, but it is not free (a Bedrock model on a sample, see `on-request-metrics.md` → "PII Detection").
- **Partial overlap** → both can run; state what each covers and let the user choose.

**Metric criteria.** A requirement that measures without asserting — "report
the character count of each prompt", "count the citations per completion",
"compute the ratio of question words" — is a valid spec criterion. Write it as
"Report/count/compute X" with no threshold; in the structured format it carries
`kind: metric`, the one spelling to write (never `is_metric`). The job
returns a value per row and the report marks it `is_metric: true`,
`pass_rate: null`; it never counts as a failure. Do not
tell the user that spec criteria must be pass/fail.

🚨 Do NOT route a requirement to a built-in just because the name sounds similar.
The user's intent is what matters.

**Judged qualities** (anything a model must judge — "answers the question",
"factually correct", "clear", "safe"):

- **One criterion per quality.** Every quality the user mentions becomes
  its own criterion. Never drop one, and never merge two into one criterion
  without asking ("correct and complete" is two criteria unless they say
  otherwise).
- **A quality to measure is a graded score.** Write it as a metric criterion
  reporting a score from 0.0 to 1.0 in steps of 0.25, and state in the
  description what 1.0, 0.5, and 0.0 mean for this data, including what earns
  the middle of the scale (e.g. 0.5 = right answer with an error in the
  explanation, when the explanation counts). Use pass/fail only when the
  user asks for pass/fail; if they give their own scale or bar, use
  theirs. Keep 1.0 as the good end: ask for a safety score (1.0 = safe), not
  a harm score, so every quality reads the same way.
- **Name the field it judges** — the response, or the task in the prompt —
  in the criterion itself, by the dataset's own field names from the rows you
  read in 3a: "Judge only the `completion`, given the `prompt`" on a dataset
  with those fields, "Judge only the last assistant message in `messages`,
  given the user turns before it" on a chat format. Spec evaluation reads the
  original records, so chat records have no `prompt` or `completion`, and a
  `reads:` entry naming a field the records lack makes that criterion error
  on every row. Difficulty or complexity rates the task in the prompt, not
  the quality of the answer.
- **Settle the judgment calls.** Decide these for this data from the context
  (3a) and the user's words, and ask only when neither settles them:
  - *Single-answer questions:* by default only the final answer counts —
    1.0 if it is right, 0.0 if it is wrong, however good the reasoning —
    unless the user wants the reasoning credited.
  - *Refusals and safety:* a refusal or safe redirection of a harmful request
    is safe and scores high; only content that is itself harmful lowers a
    safety score. Empty, off-topic, or low-quality text is not unsafe.

  Write each decision into the criterion itself, e.g. "Judge only whether the
  final answer is correct: 1.0 if correct, 0.0 if not."
- **Add a dataset-level mean for each graded score.** The job reports the
  per-row values but adds no dataset mean. Pair each graded
  row criterion with an aggregate criterion that reduces over it — in prose,
  "Report the mean [quality] score across all rows, skipping rows with no
  score"; in the structured format, a measurement (`kind: metric`,
  `scope: aggregate`, `inputs:` naming the row criterion, the statistic spelled
  out). For a dataset whose records have `prompt` and `completion` fields:

```yaml
- id: answers_prompt_score
  kind: metric
  scope: row
  reads: [prompt, completion]
  description: Judge only the `completion`, given the `prompt`. Report a score from 0.0 to 1.0 in steps of 0.25 for how fully the completion answers what the prompt asks. 1.0 = answers every part of the question. 0.5 = answers part of it or answers loosely. 0.0 = does not answer it.
- id: answers_prompt_score_mean
  kind: metric
  scope: aggregate
  inputs: [answers_prompt_score]
  description: Over all rows, compute the arithmetic mean of the `answers_prompt_score` criterion's value, skipping rows where the value is null or not a number. Return the value as a dictionary with key mean (rounded to 4 decimals) and key n (the number of rows averaged).
```

### 3c. Record the outcome

For each requirement, track whether it becomes:

- A built-in metric (carry forward to metric selection in Step 10.2)
- A spec criterion — a check (pass/fail) or a metric (measured value)
- Both

Continue until the user is satisfied with the list.

⏸ Wait for user after each clarification. Do not batch multiple clarifying questions.

---

## Step 4: Present the draft spec

Assemble the requirements into a spec document and show its full text to the
user. Write no file until the user confirms that text (below).

Use **open-ended prose format** by default when a person is describing what
they want — it's easier to read and edit. Use the structured `## Criteria`
format when any of these hold:

- the spec is being written by an agent, a script, another skill, or from a template
  rather than dictated by the user;
- a program will read the results by criterion id (the ids you write become the
  keys in `row_level_criteria`, `aggregate_criteria`, and each row's `dq_spec_eval_criteria`);
- the same evaluation will be repeated across dataset versions and the ids must not change;
- the user asks for it.

The agent helps write structured criteria and may show the derived criteria
from the last run's report (the `row_level_criteria` / `aggregate_criteria` ids and
descriptions) as the starting point; it never converts a prose spec into a structured
one on its own — Step 5 asks first.

The structured form is parsed by rules, not by a model: ids and descriptions arrive
exactly as written and no extraction call is made. The prose form is turned into
criteria by a model, so ids can differ between runs.

**Open-ended prose template:**

```
# [Dataset description — one line]

[One or two sentences describing the dataset's purpose and intended use.]

## Requirements
[Each requirement as a bullet, in plain language.]
```

Ask:

> "Does this capture what you want to evaluate against, or would you like to adjust anything?"

⏸ Wait for confirmation. Revise if needed, then confirm again before proceeding.

On confirmation, **write the confirmed text, byte for byte, to
`<project-dir>/specs/<dataset-name>-dq-spec.md`**. From this point the spec
exists as a file, never only as chat text, so that Step 7 uploads exactly what
was confirmed. Never write the spec over, or upload in its place, a downloaded
generation spec.

Apply the Spec Quality Guidelines (below) **while drafting**, before the user sees the draft. Once the user confirms, the confirmed text is final: upload it byte-for-byte. If you notice something to add afterwards (a tolerance clause, a field name), show the change and re-confirm — never edit a confirmed spec silently; a one-line addition changes the derived criteria.

---

## Step 5: Offer the structured format (optional)

After the user confirms the prose draft, ask:

> "Would you like this as a structured format with explicit criterion IDs? That makes it easier to repeat the same evaluation consistently across dataset versions."

- If yes → convert to structured `## Criteria` format (the grammar is `structured-spec.md`; worked examples are 18 to 20 on `spec-examples/measurements-and-inventory.md`), show it, and get confirmation again; on confirmation **overwrite the same file** (`<project-dir>/specs/<dataset-name>-dq-spec.md`) with it, and the structured version is now the confirmed spec
- If no → keep as prose

For the structured format: assign stable ids (lowercase, underscores, descriptive),
use `code!` or `llm!` where the routing is unambiguous, set `kind: metric` on
measurements (no `threshold`: `kind: metric` with a `threshold:` is always a parse error;
thresholds apply to checks only), and represent tunable parameters on checks as
`threshold` objects.

The Criterion grammar (ids, `kind`, `type`, `scope`, `context`, the continuation rules, the one job-level switch, the parse errors and warnings) is `structured-spec.md`, "Criterion grammar": the one statement of the grammar, read only when the spec takes the structured form.

⏸ Wait for user.

---

## Step 5b: Reference documents folder

Only when the confirmed spec has a `context: documents` criterion; otherwise go to Step 6.

Such criteria are judged against a folder of reference documents in S3, passed beside the spec as `ContextDocumentsS3Uri`. The spec does not name the folder; this step does. What the folder may hold is the contract in `dataset-service-api.md §Spec-driven evaluation` ("The documents folder").

1. **Discover.** Look for a folder the conversation already named: the user's words so far (a style guide, a source corpus, a knowledge base in S3), `data_spec.md` / `use_case_spec.md` from Step 1, or an upstream run in this session. If one is found, offer it:

> "Your `[criterion ids]` criteria are judged against reference documents. I'll use `[s3://.../]` as the documents folder — is that right?"

Ask this even when the user named the folder in the request: the question confirms the contract (the folder holds only the documents the criteria read, and everything in it goes to the model), not the path. It is its own turn, with a wait for the answer; naming the folder is not the answer, and stating the folder is not the question. The plan line at Step 12 is a second sight of the folder, not the confirmation.

2. **List.** If the spec or dataset lives in a bucket you can list, run `aws s3 ls s3://<bucket>/ --region <region>` and offer the prefixes that look like reference-document folders, then confirm.

3. **Ask** as the last resort when nothing named one and no listed prefix fits:

> "Your `[criterion ids]` criteria are judged against reference documents. Which S3 folder holds them? Give the prefix ending in `/`, for example `s3://my-bucket/reference-docs/`."

⏸ Wait for user. Record the confirmed folder URI; Step 8 carries it to Step 12, where the plan summary shows it beside the spec, a second sight of it before submit. The confirmation is the answer given here, never the plan.

---

## Step 6: Sample run recommendation

Ask:

> "Would you like to run on a sample first (e.g. 100 rows) to review the derived criteria before evaluating the full dataset? Recommended for large datasets."

- If yes → ask for record count, suggest 100 as the default (`DownSampleRecordCount`). After the sample run, surface the derived criteria embedded in `spec_eval/judge_code.py` (the `ELIGIBILITY_CRITERIA` list: `id`, `description`, `scope`, `type_hint`, plus `threshold`, `inputs`, `reads`, and `is_metric` when set) together with each criterion's `justification` from `quality_report.json` `spec_eval[0].result.row_level_criteria` / `aggregate_criteria`, and each row criterion's `type` (aggregate criteria have no `type`; they always run as code), so the user can review what the job derived before committing to the full run from that artifact.
- If no → proceed without a sample count.

⏸ Wait for user.

---

## Step 7: Spec delivery

Upload the **final confirmed spec file** — `<project-dir>/specs/<dataset-name>-dq-spec.md` as last confirmed by the user (the structured version if Step 5 converted it, otherwise the Step 4 prose) — to S3 and pass it as `SpecS3Uri`; this is the only supported delivery method. Verify before submit that the uploaded object is byte-identical to that file (not the generation spec, not an earlier draft). Save under the **Output S3 bucket** of this evaluation, at a path like `specs/<dataset-name>-dq-spec.md`. At this step that bucket is not yet confirmed: it is the output location the conversation already settled (an upstream run's `OUTPUT_S3_URI`, or a bucket the user named), otherwise the default `quality-job.md` Step 11 proposes from `session.default_bucket()`. The upload happens at this step, before the Step 11 plan summary, so the plan names a path that already exists. Step 11 confirms the bucket in the plan summary, never a bucket of your own choosing; if the user changes the bucket there, upload the same file again to the new bucket, verify it again, and use the new path.

Mention the S3 path in the plan summary.

---

## Step 7b: Judge model

Spec evaluation uses **one** model for both roles — deriving the criteria from the spec and judging every row. It has its own default and its own allowlist.

**Default:** omit `ModelConfig` for the spec-evaluation default model. Read the service's default and permitted model IDs from `dataset-service-api.md` Spec-driven evaluation, "Model".

🚨 When quoting cost or naming the model for a spec-driven run, name the service's default model from that page. If the plan sets a `ModelId`, say that model instead. The spec model must emit a valid judge module, not just a row verdict.

`dataset-service-api.md` Spec-driven evaluation, "Model", lists the permitted model IDs.

To override, pass `ModelConfig.JudgeModelConfig.ModelId` in the `spec_eval` operation's `Config`. An ID outside the permitted list in `dataset-service-api.md` is rejected at submit with a 400 that names the allowed values, as is a key the `spec_eval` `Config` does not take; the job checks the model again when spec evaluation starts. `CodeGenerationModelConfig` is rejected at submit — one ID serves both roles.

This resolves to a single ID. The account needs Bedrock access to that specific model, so confirm that the chosen override, or the service's default model from `dataset-service-api.md`, is enabled.

---

## Step 8: Return to the main flow

Return to `quality-job.md` Step 10.1, which takes these forward in this order: Step 10.2 (built-ins, when the user took the Step 10 offer), Step 10.3 when built-ins run, then Step 11 with every item in order (job name, output, role, dashboard), then the Step 12 plan on `quality-job-submit.md`. Step 11 is never skipped on the spec path; the plan is not written before its items are answered. Carry forward:

1. The spec S3 URI (`SpecS3Uri`) → into the `spec_eval` operation's `Config` (assembled at Step 12)
2. Any requirements the user chose to cover with a built-in (Step 3b) → into the built-in metric selection (Step 10.2)
3. A judge model override, if the user chose one (Step 7b) → into the `spec_eval` `Config` as `ModelConfig.JudgeModelConfig.ModelId`. If they did not choose an override, omit `ModelConfig` and the service applies the spec-evaluation default model (see `dataset-service-api.md` Spec-driven evaluation, "Model").
4. Whether a sample run was requested (Step 6) → `DownSampleRecordCount`
5. The folder of reference documents confirmed at Step 5b, when the spec has `context: documents` criteria → into the `spec_eval` `Config` as `ContextDocumentsS3Uri` (an S3 folder URI ending in `/`); the Step 12 plan summary shows it on the spec line
6. The mode (standard / SDG-distill) — the Step 12 summary states the spec's provenance

---

## Spec Quality Guidelines

Use these when drafting or reviewing a spec.

**State *what* counts as correct, not *how* to check it.**
Every example spec describes intent — "compare the chosen letter to the reference, ignoring case." Never describe the parsing algorithm. The service classifies each criterion and generates the checker from the intent.

**Mechanical criteria route to `code` and cost nothing per row. Fuzzy criteria route to `llm` and pay per row.**
The routing question is not "what subject is this?" but "is the correct answer mechanically extractable and comparable, or does it require judgment?" Letter equality, number equality, boolean normalization → `code`, 0 LLM calls per row. "Same meaning", "matches in spirit", "relevant to the question" → `llm`, one Bedrock call per row. The same domain can route differently depending on exact intent — exact numeric match routes to `code`, symbolic equivalence routes to `llm`.

**Name the fields the checker will read.**
Name the fields: "each row has a `prompt` and a `completion`." A spec that doesn't name fields causes the checker to guess column names, which leads to KeyError failures at judge time.

**State surface form tolerance explicitly.**
If a criterion has format-variable answers — option letters with or without parentheses, numbers with or without commas — say so in the spec: "casing doesn't matter, and surrounding punctuation should be ignored."

**A criterion can measure instead of check.**
Say "report/count/compute X" and give no threshold. The job returns a value per row; the report summarizes the distribution. Never invent a threshold the user didn't state.

**Dataset-level requirements are aggregate criteria.**
"No more than 5% of records may be refusals", "average completion length must exceed 80 words" apply to the dataset as a whole. In prose, state them as such; in the structured format use `scope: aggregate`. Their results land in `aggregate_criteria[<id>]` with a `value` (and a verdict for checks) — read the value.

**A pass-rate requirement is always an aggregate criterion.**
Any requirement stated as "at least X% of records should..." is a second criterion, not a property of the row-level one. Capture it with `scope: aggregate`, `inputs:` pointing to the row criterion's id, and `threshold: {"min_rate": X}`. Do not fold it into the row-level criterion description.

**`threshold` must always be a JSON object, never a bare value.**
`{"min_words": 20}` is valid. `20` alone is a hard parse error.

---

## Reference

For example specs illustrating each pattern (multiple choice, math, extractive QA,
mixed-route, aggregate threshold, fine-tuning dataset quality), read
`spec-examples.md`.

<!-- markdownlint-disable-file MD029 -->
