# Annotation Specification Template

Used by Step 3a of `overview.md`. The annotation specification is tool-agnostic — it declares what to annotate and what fields to capture. Tool-specific work is handled in Step 3a: the agent builds the label config, and `scripts/ls_space_client.py` creates the projects, reports progress and exports annotations (annotator accounts are created automatically on first sign-in).

## File location

Write the spec to `<project-dir>/specs/annotation_specification.md`. If a project directory doesn't exist, load the `directory-management` reference to create one before writing.

## Template

Fill in this template, replacing every placeholder as the table below says, and write the result to the file location above:

```markdown
# Human-in-the-Loop Annotation Specification

## Project Overview

- **Project Name:** [PROJECT_NAME]
- **Dataset:** [DATASET_PATH]
- **Primary Quality Issues:** [QUALITY_ISSUES]

## Data Information

- **Data File:** `[DATA_FILE]` ([N_RECORDS] records)
  - **Selection criteria:** [SELECTION_CRITERIA]
  - **Annotation Task:** [ANNOTATION_TASK]

## Annotation Questions

[ANNOTATION_QUESTIONS]

## Annotation Guidelines

- **Question Types:** [QUESTION_TYPES]
- **Estimated Time per Record:** [MINUTES_PER_RECORD] minutes
- **Total Volume:** [N_RECORDS] records
- **Quality Dimensions:** [QUALITY_DIMENSIONS]

## Data Schema

**Input Fields:** [INPUT_FIELDS]

**Expected Output Fields:** [OUTPUT_FIELDS]

## Success Criteria

- Minimum [MIN_PCT_ANNOTATED]% of records annotated
- Inter-annotator agreement ≥ [MIN_PCT_AGREEMENT]% (if multiple annotators)
- Clear corrections provided for flagged quality issues

## Next Steps

1. Create one Label Studio project per annotator in the shared space (`overview.md` Step 3a.7)
2. Annotators label their projects
3. Export the annotations and summarize them (Steps 5–6)
4. Apply the approved edits to the dataset (Steps 7–8)
```

| Placeholder | Fill with | Example |
|---|---|---|
| `[PROJECT_NAME]` | The project name resolved in Step 3a.1 | `fix-factual-errors` |
| `[DATASET_PATH]` | The original dataset Step 8 edits | `data/evaluated_data.jsonl` |
| `[QUALITY_ISSUES]` | The issues from the `dataset-quality` report or the user; blank if unknown | `factual errors in 12% of completions` |
| `[DATA_FILE]`, `[N_RECORDS]` | The file sent for annotation and its record count | `data/low_confidence.jsonl`, `40` |
| `[SELECTION_CRITERIA]` | How the records were selected, quoted verbatim; blank if the whole file is annotated | `accuracy score below 3` |
| `[ANNOTATION_TASK]` | One of: direct correction, validation, classification, rating, labeling | `direct correction` |
| `[ANNOTATION_QUESTIONS]` | The Step 2 approved questions, one numbered line each: the question text, then its answer type and choices in parentheses | `1. Is the response correct? (single choice: yes / no / partial)` |
| `[QUESTION_TYPES]` | The answer types those questions use | `single choice, text input` |
| `[MINUTES_PER_RECORD]` | The per-record estimate from `references/annotation-question-guide.md` | `2` |
| `[QUALITY_DIMENSIONS]` | The score columns present in the data file; `none` if there are none | `accuracy, completeness` |
| `[INPUT_FIELDS]` | The record fields annotators see, comma-separated | `prompt, completion` |
| `[OUTPUT_FIELDS]` | The captured field names the questions fill (Authoring rules, below) | `corrected_completion, issues` |
| `[MIN_PCT_ANNOTATED]` | The coverage the user needs; `90` if they gave none | `90` |
| `[MIN_PCT_AGREEMENT]` | The agreement target for several annotators; `80` if they gave none; drop the line for one annotator | `80` |

## Authoring rules

- Include the **Annotation Questions** section only for splits actually supplied this cycle (sometimes there is just one).
- Quote the supplied split criteria verbatim. If no criteria text was supplied, leave the field blank rather than inferring it.
- The **Expected Output Fields** list must use the field names of `references/local-review-guide.md` → Step 3b: Captured row schema so post-annotation steps can read either tool's export uniformly. The Label Studio label config (Step 3a.5) maps native field names to these canonical names.
- Keep success criteria concrete (numeric thresholds where possible).
- For auto-labeling input, instead of the field-name rule above: fill `[INPUT_FIELDS]` with the input fields annotators see, `[OUTPUT_FIELDS]` with the id field (carried through unchanged) and the prediction field (`references/auto-labeling-input.md` → What annotators see and answer), and `[QUALITY_DIMENSIONS]` with `none`, because the question asks for the label itself.

## Hand-off after writing

The spec is written from the question set the user approved in Step 2; Step 3a.7's confirmation covers it before any project is created (on the spec-only path, Step 3a.2 asks first). Once written, proceed directly to Step 3a.3 (Find the Label Studio shared space) and continue the Label Studio setup flow. The spec serves as documentation for the annotation project being created.
