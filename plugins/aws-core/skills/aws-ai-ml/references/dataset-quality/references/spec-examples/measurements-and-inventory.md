# Spec Examples: Measurements and Inventory (examples 17 to 20)

Examples 17 to 20 of the dataset quality spec examples: the family that asks for values rather than verdicts (measurements next to checks, a benchmark characterization, an inventory with no per-row model calls, the documents as the authority). The routing tables, the use-case index and the spec-format notes are `spec-examples.md`; the other two families are `spec-examples/answer-correctness.md` and `spec-examples/keep-drop.md`. Examples 18 to 20 use the structured `## Criteria` format, whose grammar is `structured-spec.md`.

### 17. Measurements Alongside Checks (Metric Criteria)

**Use case:** The user wants per-record quantities reported next to their pass/fail rules — here, lengths — without a threshold. A requirement written as "report / count / compute X" with no bar becomes a **metric criterion**, written `kind: metric`: the job returns a value per row (the report marks it `is_metric: true`, `pass_rate: null`) and it never counts as a failure. For example, two "Report the character count…" lines produce `prompt_character_count` and `completion_character_count`, both routed to `code`, with `{"verdict": null, "value": 30, "source": "code"}` per row.

```markdown
# Q&A Dataset — Checks and Measurements

Each row has a `prompt` and a `completion`.

## Requirements
- The completion must address the question in the prompt.
- The completion must not be empty.
- Report the character count of the `prompt`.
- Report the character count of the `completion`.
- Count the number of sentences in the `completion`.
```

**Expected routing:** the first check → `llm`; the empty check and all three measurements → `code` (0 model calls per row). In the report, the two checks appear under Checks with pass rates; the three measurements appear under Measurements with the summary the aggregate carries for each (a row-only metric has none yet: its row says where the per-row values are and that they can be summarized on request). In the scored rows, `dq_spec_eval_criteria["prompt_character_count"].value` carries the number; `dq_spec_eval_pass` ignores metric criteria.

If a built-in covers the same quantity (`character_count`, `word_count`), the built-in is the cheaper path, and the user may keep the measurement in the spec.

### Example 18 — characterize a benchmark (annotation-style, structured)

Every example is classified rather than checked; the results feed a downstream program by id. Yes/no capabilities are `llm!` checks; the two measurements are `kind: metric`. Note that every scale and the field-scope instruction live inside each description; the `values` line on `difficulty` restates the scale for the code-writing model.

```markdown
# squad-v2 benchmark characterization — extractive QA with abstention

## Stratify by
- split

## Criteria
- id: tests_reasoning
  type: llm!
  scope: row
  reads: [prompt, completion]
  description: Base this judgment ONLY on the `prompt` and `completion` fields; do not read or consider `references`, `metadata`, `system`, `split`, `dataset`, or `id`. True if producing the gold answer requires multi-step inference over the passage — combining several sentences, handling negation, comparison, or a causal chain — rather than locating a stated fact.
- id: tests_contextual_comprehension
  type: llm!
  scope: row
  reads: [prompt, completion]
  description: Base this judgment ONLY on the `prompt` and `completion` fields; do not read or consider `references`, `metadata`, `system`, `split`, `dataset`, or `id`. True if the gold answer in `completion` is derivable entirely from the passage text in `prompt`.
- id: dominant_capability
  kind: metric
  scope: row
  reads: [prompt, completion]
  description: Base this judgment ONLY on the `prompt` and `completion` fields; do not read or consider `references`, `metadata`, `system`, `split`, `dataset`, or `id`. Report, as a single string value spelled exactly as written, one label from this set — Reasoning, Contextual Comprehension — naming the PRIMARY capability the example tests. It must be one of the capabilities judged true in the criteria above. This requires reading and understanding the passage and question; it cannot be inferred from lengths, keywords, or formatting.
- id: difficulty
  kind: metric
  values: 1 to 5
  scope: row
  reads: [prompt, completion]
  description: Base this judgment ONLY on the `prompt` and `completion` fields; do not read or consider `references`, `metadata`, `system`, `split`, `dataset`, or `id`. Report an integer value from 1 to 5 rating how hard this example is for a model. 1 = trivial (any competent model gets it; single obvious step). 2 = easy (single-step lookup). 3 = moderate (some reasoning or domain knowledge; 2–3 steps). 4 = hard (multi-step, subtle patterns, combining several pieces of information). 5 = expert (deep expertise, complex multi-hop inference, or genuine ambiguity). Judge the passage and question, not surface statistics such as length or word count.
```

Output: `row_level_criteria.tests_reasoning.coverage_by_stratum.split.{seed,dev}`; per row `dq_spec_eval_criteria.difficulty.value` (a number, `verdict: null`) and `dq_spec_eval_criteria.dominant_capability.value` (one of the labels). The measurements have no pass/fail — read the values, not `rows_passed` / `rows_failed`.

### Example 19 — inventory a dataset with no per-row model calls (aggregate measurements)

Every criterion is `kind: metric` and `scope: aggregate`; aggregate criteria always run as code, so the job makes no per-row model calls (`llm_api_calls: 0`; the service still spends a few calls once to derive the code from the spec). Aggregate values may be numbers, strings, **or dictionaries** — distributions, percentile tables, and even a small set of rows can be returned in the report. Statistics are spelled out so the generated code is exact.

Two criteria show the pattern. A caller that only reads each `value` may write the same reducers as `code!` checks with "Set the verdict to true"; in a dataset quality report, write them as measurements, as here.

```markdown
# Dataset inventory — no per-row model calls

## Stratify by
- split

## Criteria
- id: row_count_by_split
  kind: metric
  scope: aggregate
  description: Count rows per distinct value of `split`. Return the value as a dictionary {split_value: count}.
- id: representative_sample
  kind: metric
  scope: aggregate
  description: Return 10 rows chosen as follows. Allocate the 10 slots across the distinct values of `split` in proportion to their row counts, rounding down, then give any remaining slots one at a time to the values with the largest fractional remainders, breaking ties by the split value in ascending lexical order. Within each split, order rows by the sha256 hex digest of the string "seed:" followed by the row's `id`, ascending, and take the first allocated number of rows. Return a dictionary with key rows holding the list of the full selected rows, and key allocation holding the dictionary {split_value: slots}.
```

Output: `aggregate_criteria.<id>.value` holds each dictionary; `aggregate_criteria.representative_sample.value.rows` are the sampled rows, readable straight from the report without opening the dataset. Each comes back with `is_metric: true` and `verdict: null`: a measurement, not a check.

### Example 20 — the documents as the authority, and a judge text of your own

`context: documents` makes the documents staged for the job (the folder named by `ContextDocumentsS3Uri` in the `spec_eval` operation's `Config`) the authority a row is judged against, as `rating_symbols_are_sp` does. `prompt:` sends your own judge text, read word for word instead of the description, with or without documents, as `tone_fits_brand` does.

```markdown
# Ratings commentary — checked against the S&P style guide

## Criteria
- id: rating_symbols_are_sp
  context: documents
  reads: [commentary]
  description: The commentary uses only rating symbols and modifiers that S&P Global Ratings
    defines; a symbol from another agency's scale is a defect.
- id: register
  kind: metric
  context: documents
  values: [formal, informal, neutral]
  description: Classify the register of the commentary as formal, informal, or neutral by the style guide's definitions.
- id: cited_sections
  kind: metric
  context: documents
  description: Count the distinct sections of the style guide the commentary cites.
- id: tone_fits_brand
  prompt: You are reviewing a customer-facing commentary for a ratings publisher.
    Pass it only if the tone is measured, confident and free of slang. Fail it otherwise.
  reads: [commentary]
  description: The commentary's tone fits a ratings publisher.
```

Output: `rating_symbols_are_sp` and `tone_fits_brand` carry a verdict per row; `register` carries one of the three labels and `cited_sections` a number, both with `verdict: null`. Each documents criterion's entry in `context_criteria` says where its judge text came from in `judge_text_source`: `written` for the three above, because a model wrote it from the description; the other values are listed in `output-schema.md` "Aggregate report: `spec_eval` section". `tone_fits_brand` has no documents, so it has no `context_criteria` entry; the judge reads its prompt word for word.

<!-- markdownlint-disable-file MD001 -->
