# Structured Spec: the `## Criteria` format and the Criterion grammar

Read this page only when a spec takes the structured `## Criteria` form: `spec-authoring.md` Step 5 offers it after the prose draft is confirmed, and `bring-your-own-spec.md` Step 2 lints a structured spec against the grammar below. A prose spec needs none of this. The Criterion grammar section is the one statement of the grammar; the lint table, the examples page, the request contract and the report pages point here. Worked structured examples are 18 to 20 on `spec-examples/measurements-and-inventory.md`.

## The structured format

### Structured `## Criteria` format (for repeatable runs)

A document with a `## Criteria` section parsed deterministically — no extraction LLM needed. Use this for repeat evaluations where the user wants stable criterion IDs and locked routing.

```markdown
## Criteria
- id: completion_min_length
  type: code!
  description: The completion must contain at least 20 whitespace-separated words.

- id: completion_answers_prompt
  type: llm!
  description: The completion must directly address the question posed in the prompt.

- id: no_placeholder_text
  type: code!
  threshold: {"banned": ["TODO", "TBD", "FIXME"]}
  description: The completion must not contain any of the banned placeholder tokens,
    matched case-insensitively.

- id: substantive_completion_rate
  scope: aggregate
  inputs: [completion_min_length]
  threshold: {"min_rate": 0.90}
  description: At least 90% of all evaluated rows must pass the length check.
```

**Key fields:**

- `id` — stable identifier used in the report and in `inputs` references
- `kind` — `rule` (default; a pass or fail per row) or `metric` (a measured value, no verdict).
- `type` — who computes: `auto` (default, the service decides), `code`, `llm`, `code!`, or `llm!` (the `!` suffix locks classification against override). Applies to metrics too. Leave it out on a `context` or `prompt` criterion.
- `scope` — `row` (default) or `aggregate` (one corpus-level verdict, or one measured value for an aggregate metric)
- `context` — `documents`: the documents staged for the job are the authority and the model judges the criterion against them; row scope; no `type` line. Count the spec's documents criteria against the cap in "Criterion grammar" below; if it exceeds the cap, use the grammar's merge-or-drop remedy.
- `values` — the answers a metric may give: a set of labels in brackets, e.g. `values: [formal, informal, neutral]`, or a range `min to max`, e.g. `values: 1 to 5` (`values: 0 to 100` for a percentage). Optional; leave it out for a count or free text, and the judge may return any number or any non-empty text. Never on a rule. Enforced when the documents or a prompt are in play (an answer outside the set is asked for once more, then the row is `not_evaluable`); a note to the code-writing model otherwise.
- `prompt` — the exact text the judge reads, sent word for word; one paragraph per line; the model judges; no `type` line and row scope only. Keep `description` for the report. A prompt line that must begin with a field name and a colon is written with a leading `|`.
- `inputs` — aggregate criteria only: must name declared row criterion ids
- `source` — optional; the prose sentence the criterion was derived from
- `reads` — optional list of the dataset's own fields the criterion uses, e.g. `reads: [prompt, completion]` on a dataset with those fields (chat records have `messages` instead). Echoed in the report under the criterion; a field the records lack makes that criterion error on every row. A declaration — it does not restrict what the judge sees.
- `threshold` — checks only; a JSON object with tunable parameters. Must be an object, not a scalar. Not allowed with `kind: metric`: `kind: metric` with a `threshold:` is always a parse error, on every route; remove the `threshold:` line, or write `kind: rule` only if a pass/fail check was intended.

**Locking classification with `!`:** Use `code!` or `llm!` to prevent the service from overriding your intended route. A `code!` criterion is reproducible and costs 0 Bedrock calls per row — the primary lever for controlling cost and determinism on repeat runs.

**Rules the parser enforces (submit does not check them: a violation fails the job when spec evaluation starts, after any built-in metrics have run, and no criterion is evaluated):**

- The heading is an H2 whose text is exactly `Criteria` (any case). Any other heading, such as `## Criteria (v2)`, makes the document a prose spec.
- `id` must match `^[a-z][a-z0-9_]*$` — lowercase, starts with a letter, underscores only — and start a bullet (`- id: ...`). Ids are unique.
- Field keys are exactly `id`, `kind`, `type`, `scope`, `threshold`, `inputs`, `reads`, `context`, `values`, `prompt`, `source`, `description`, lowercase.
- Every criterion needs a non-empty `description`; `kind`, `type`, `scope` and `context` must be one of the values above (`context: yes` is an error; write `context: documents`); every `inputs` entry must be a declared criterion id.
- `kind: metric` with a `threshold`, `prompt` with `scope: aggregate`, and `values` on a rule are errors. A `type:` line on a `context: documents` or `prompt:` criterion is ignored with a warning, because the model always judges these criteria; remove the line. A `labels:`, `range:` or `measure:` line is an error whose message shows the `values:` line to write.
- Which continuation lines of a description or a prompt are read as a field and which stay text (the `FIELD_WORD_IN_DESCRIPTION` warning, and the remedy): "Criterion grammar" below.
- Under `## Criteria`, only `- id:` entries are allowed. A prose bullet or paragraph there is a parse error, except that a line directly after a `description:` line (no blank line or other field between) is joined into that description — keep prose out of the section.
- Text outside `## Criteria` and `## Stratify by` (title, tables, scale definitions) is **not shown to the judge and not used to generate code**. Anything the judge or the generated code must know — scales, label sets, which fields to read, what a sentinel value means — goes inside each criterion's `description`.

**`## Stratify by` (optional, before `## Criteria`):** one bullet naming a column, e.g. `- split`. Every row-level pass/fail criterion then reports `coverage_by_stratum` (per-value `n_evaluated`, `n_pass`, `pass_rate`) in the aggregate report. Bullets only — any other line under the heading is a parse error. Metric criteria do not get per-stratum blocks.

**`## Pass rate includes not applicable` (optional, before `## Criteria`):** the one job-level switch, on the pass rates of `context: documents` criteria. Its body, what it changes, the parse error and the `PASS_RATE_SWITCH_IGNORED` warning: "Criterion grammar" below.

**Two wordings, two behaviors:**

- `code!` descriptions are turned into code that does exactly what they say. Define every statistic (which median, which percentile rule, how ties break, what happens on empty input); leave nothing to "obvious". Seeded selection must use `hashlib` — `random` is not importable in the sandbox, and the job fails at run time if the generated code imports it.
- `llm!` descriptions are rewritten by the code generator into the judge prompt and may be shortened. Put one idea per sentence, and state the essential constraints (which fields to judge from, the scale, the label set) plainly — they are more likely to survive as separate sentences than folded into one.

### Criterion grammar

The rules below are the one statement of the structured grammar; the lint table in `bring-your-own-spec.md`, the examples page, the request contract and the report pages point here.

A criterion block carries these fields, in this order:

- `id` — the criterion's name in the report and in `inputs`.
- `kind: rule | metric` — what the criterion produces per row. `rule` gives a pass or fail, the default; a `kind: rule` criterion is reported as a check, and these pages say "check" except for the field value itself. `metric` gives a value and no verdict.
- `type: auto | code | llm | code! | llm!` — who computes; `auto`, the default, lets the service decide; the `!` locks the choice; works for metrics too; leave it out on a documents or prompt criterion.
- `scope: row | aggregate` — per row, the default, or one result over the rows' results; `inputs: [id, ...]` names the row criteria an aggregate reads. A documents or prompt criterion is row scope.
- `threshold: {"min_words": 20}` — on checks only: a one-line JSON object of tunable parameters, never a bare value; not valid with `kind: metric` (`kind: metric` with a `threshold:` is always a parse error).
- `context: documents` — the documents staged for the job decide the verdict; row scope; no `type` line. At most 16 documents criteria per job, the service's own `builtin_faithfulness` criterion counted, so at most 15 of the spec's own; a spec with more fails the job with `CONTEXT_TOO_MANY_CRITERIA` after the criteria are derived and the code is generated, before any row is judged: merge or drop documents criteria. The cap may change.
- `values: [a, b, c]` or `values: 1 to 5` — on a metric only: a set of labels in brackets for a closed set of answers, or a range `min to max` for a bounded number; leave it out for a count or free text. Enforced when the documents or a prompt are in play: an answer outside the set is asked for once more, then the row is not evaluable. On a metric with neither `context: documents` nor `prompt:`, the line is a note to the code-writing model.
- `prompt:` — the exact text the judge reads, when the description is not enough; one paragraph per line; the model judges; keep `description` for the report. A prompt line that must begin with a field name and a colon is written with a leading `|`.
- `reads` — the dataset fields the criterion uses.
- `source` — optional; the prose sentence the criterion was derived from.
- `description` last.

A line that begins with a lowercase field name and a colon (`kind:`, `values:`, `reads:`, `prompt:` and the others above) is that field in any order, and inside a prompt continuation it ends the prompt. Inside a description, indentation decides: a field line at or left of the `description:` key's column is that field, whatever the word. A line indented deeper than the key ends the description only when it begins with `id:`, `type:`, `scope:`, `threshold:`, `inputs:`, `reads:` or `description:`; any other field word on a deeper line (`kind:`, `values:`, `context:`, `prompt:` and the rest) stays description text and the parser warns once (`FIELD_WORD_IN_DESCRIPTION`). A capitalized word such as `Context:` stays text. So write every field at the key's column if the field was meant, and never begin a deeper continuation line of a description, or any continuation line of a prompt, with a lowercase field name and a colon: if the text was meant, reword the line, or in a prompt write `|` before it.

A spec may also carry one job-level section above `## Criteria`, `## Pass rate includes not applicable`. Its body is one word: `true` or `yes`, `false` or `no`; absent or empty means `false`. It changes the pass rates of `context: documents` criteria only: with `true`, a row such a criterion finds not applicable counts as a pass in its pass rate (a row that is not evaluable is never counted). Any other body is a parse error when the spec has a `context: documents` criterion; otherwise the section has no effect, the default `false` is kept and the job carries a `PASS_RATE_SWITCH_IGNORED` warning: remove the section, or write `true` or `false`.

Structured entries for measurements **must** carry `kind: metric` and no
`threshold`. Without it the service can treat the entry as a check: a row entry
is then left out of `metric_criteria_declared` (which counts row criteria
only), and an aggregate entry comes back as a check with `verdict: true`
instead of a measurement. Example:

```yaml
- id: completion_word_count
  kind: metric
  scope: row
  description: Report the word count of each completion.
- id: mean_completion_words
  kind: metric
  scope: aggregate
  description: Report the average completion length in words across the dataset.
- id: register
  kind: metric
  context: documents
  values: [formal, informal, neutral]
  description: Classify the register of the completion as formal, informal, or neutral by the style guide's definitions.
```

Before saving, re-read the draft: every "report / count / compute" requirement
has `kind: metric`; every check has none. A check whose description mentions
counting or measuring anywhere ("number of", "word count", "average", "how
many" and the like) should say `kind: rule`, so the service does not take it
for a metric.

---
