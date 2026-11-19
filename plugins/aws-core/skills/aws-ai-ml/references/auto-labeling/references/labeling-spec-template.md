# Auto-Labeling Specification Template

## Use Case Context
[Describe the labeling task: what data is being labeled, why, and how the labels will be used (e.g., for fine-tuning, evaluation, analytics).]

## Quality Standards
[High-level criteria for labeling quality. For example, label accuracy, consistency across similar inputs, coverage of edge cases, inter-annotator agreement targets.]

## Input Data
[Description of the corpus being labeled. This section is required - auto-labeling always operates on existing data.]

- **Source:** [S3 URI or local path to the unlabeled JSONL]
- **Input field:** [Which JSON field contains the text to label, e.g., `text`, `content`, `input`]
- **Size:** [Approximate number of rows]
- **Domain:** [Brief description of where the data comes from]

### Labelled Seed (required for full loop and refinement)
[A small set of rows with confirmed ground-truth labels. Used to split into dev/val/test, drive refinement, and produce the held-out macro-F1. Not required for apply-only workflows (frozen spec + confidence tagging).]

- **Source:** [S3 URI or local path to the labeled seed JSONL]
- **Ground-truth field:** [Which JSON field holds the label, e.g., `gt_label`]
- **Size:** [K labeled examples per class - at least ~10 per class (`references/taxonomy-guidance.md`); an accuracy promise needs at least 50 gold rows in the test split, about 200 seed rows]

## Input Data Preparation (optional)
[Preprocessing steps applied to input data before labeling, if any. For example, deduplication, filtering by language, truncation.]

## Labelling Configuration
### Label Set
[A flat, mutually exclusive list of class names, each with a one-line definition of when it applies. If two labels can both apply to one record, that is a taxonomy problem - restructure before proceeding.]

| Label | Definition |
|---|---|
| label_1 | One-line description of when to assign this label |
| label_2 | One-line description of when to assign this label |

### Score Levels (numeric tasks: `llm_judge` by default, `ordinal` optionally)

[For a numeric task, write this section INSTEAD of the Label Set (leave the Label Set out, or the task is detected as classification). This anchored rubric is the default structure for an `llm_judge` spec: one entry per score level, high to low, each with a definition in observable terms and 1 or 2 example rationales. Draw the examples from the DEV split of the labeled seed only, never val or test, since the spec is quoted into every prompt. `code_templates/induce_spec.py` with `TASK = "llm_judge"` writes this section for you (see `references/spec-induction.md`). Why it is the default: `references/task-types.md`, **Judge tasks**.]

- **5 - Excellent:** [What earns the top score, in terms a reader can check.]
  - Example: "[short excerpt of a dev row, under 40 words]" -> 5. Why: [one sentence tying the excerpt to the definition]
- **4 - Good:** [What separates a 4 from a 5 and from a 3.]
  - Example: "[short excerpt]" -> 4. Why: [one sentence]
- **3 - ...:** [one entry per level, down to the lowest score]
  - Example: "[short excerpt]" -> 3. Why: [one sentence]

### Labelling Rules
[One short rule per label describing the decisive signal. Where two labels are easily confused, add a disambiguation line. The content can start minimal - the auto-labeling refinement loop will harden and expand it against held-out data - but the section itself is required (a spec missing a section breaks labeling).]

- **label_1:** [The decisive signal for this label.]
- **label_2:** [The decisive signal for this label.]
- **label_1 vs label_2:** [Disambiguation - when to pick one over the other. Cite observable features in the text.]

## Output Schema
[Per record: a short reasoning chain, then the final label (one of the label set). Ground truth, if present in the input data, is for scoring only and must not be read when predicting. The labeling job appends its own JSON reply format after the spec and reads only its keys, so this section restates that format and asks for no other.]

```
{"reasoning": "<one short sentence explaining the label choice>", "label": "<one of the labels from the Label Set above>"}
```

For another task, restate that task's job reply instead (`references/task-types.md` lists each): `ner` uses `"entities"`, `qa` `"answer"`, `summarization` `"summary"`, `ordinal` `"score"` and `llm_judge` `"judge_score"`. Never ask for `REASONING:` / `LABEL:` / `SCORE:` lines. For a numeric task, put your scale's own ends in the reply (ordinal: `{"reasoning": "<one short sentence explaining the score>", "score": <a number from 1 to 5>}`), add a `Scale: 1 to 5` line under it, and check for a number in range instead of a Label Set member. The labeling job reads the scale from the `Scale:` line and refuses a numeric corpus run whose spec states none.

## Data Verification

### Verification Mode
deterministic

Do not use LLM to verify samples. All verification must be pure Python only. Do not make any LLM calls in the verification function.

### Checks

1. **Structural checks**:
    - Output is a single JSON object with "reasoning" and "label" keys
    - label value is one of the labels in the Label Set (exact match, case-sensitive)
    - reasoning is non-empty
    - For a numeric task (`ordinal`, `llm_judge`), use these instead of the two `label` checks: the JSON object has "reasoning" and the score key (`score` or `judge_score`), and that key holds a number within the scale (`--score-min` to `--score-max`)
