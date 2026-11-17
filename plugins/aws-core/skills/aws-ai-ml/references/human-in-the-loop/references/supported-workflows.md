## Supported Workflows

This skill executes the human-in-the-loop cycle. The decision to run it can come from `dataset-quality` signals (flagged records needing human judgment) or directly from the user. `dataset-transformation` produces the split files, then this skill runs.

### Workflow A: Local review (quick, in-chat)

`dataset-quality` flags issues → user or plan decides human-in-the-loop review is needed → `dataset-transformation` produces `low_confidence.jsonl` → activates this skill with the file path → preview samples → user picks **local** → propose annotation questions → walk records one-by-one in chat → capture to `local_review_feedback.jsonl` → summarize → user approves edit plan → `dataset-transformation` applies edits → `dataset-quality` re-scores → before/after comparison. No Label Studio, no leaving chat.

### Workflow B: Label Studio (full annotation project)

`dataset-quality` flags issues → user or plan decides human-in-the-loop review is needed → `dataset-transformation` produces the split files → activates this skill → preview samples → user picks **Label Studio** → propose annotation questions → produce `annotation_specification.md` → connect to the Label Studio shared space → split records across annotator profiles, one project each → return per-annotator links → annotation runs in Label Studio → skill reports per-annotator progress on request → user reports completion → this skill summarizes annotation status → user approves edit plan → `dataset-transformation` applies edits → `dataset-quality` re-scores → before/after comparison.

### Workflow C: Mode switch mid-cycle

If during local review the user decides records are too long or too numerous, they can switch to Label Studio: `local-review-guide.md` → Step 3b: Mode switch mid-loop.

### Workflow D: Spec-only (no execution)

`dataset-quality` flags issues → user or plan decides human-in-the-loop review is needed → `dataset-transformation` produces the split files → activates this skill → preview samples → user picks **Label Studio** → produces `annotation_specification.md` → user stops there to plan the annotation project. The user can resume later to complete the Label Studio setup. Post-annotation steps run later in a separate session.

### Workflow E: Re-running with a different split

If the user wants to retry with a different rule (different score columns, threshold, or filter logic), they update the split criteria, call `dataset-transformation` again to produce fresh split files, then re-activate this skill. This skill never re-splits in place.

### Workflow F: Direct invocation

The user can invoke this skill directly with pre-split files plus context they provide themselves: the primary quality issues, and what kind of review each split needs. This skill prompts for any missing context before drafting questions. Same downstream flow as Workflows A and B.

### Workflow G: Auto-labeling hand-off
Auto-labeling hands over its review set or cold-start sample, with its hand-off spec when it has one → preview the id field and the input fields → check the record ids → the label question for the task → local review or Label Studio, blind → export with each id unchanged → the export goes back to auto-labeling, with or without this skill's Step 8 merge (`references/auto-labeling-input.md` → After the review).

## Notes

- The annotation specification is produced in Label Studio mode. It declares what to annotate, what questions to ask, and what fields to capture. Label Studio itself runs as an app in a SageMaker Studio shared space that the user launches from the Studio UI, or that the skill creates or starts when the user chooses that (`overview.md`, Step 3a.3); Step 3a of this skill connects to it to create projects, and later reads progress and exports annotations.
- Annotation questions are drafted by this skill from the `dataset-quality` report findings or user-provided context, using `references/annotation-question-guide.md` as the design reference. The user reviews and approves the draft. This skill does not invent questions without context — if no `dataset-quality` report is available, it asks the user for the quality issues directly.
- The confidence-split file (`low_confidence.jsonl`) is produced upstream by `dataset-transformation` before this skill runs. This skill receives it as input and does not re-split, override, or invoke `dataset-transformation` for splitting.
- A second upstream shape comes from `auto-labeling`: `review.jsonl`, defined (row schema and the spot-check rows it carries) in `auto-labeling/references/input-output-contract.md`, "Human-in-the-loop hand-off". A third is auto-labeling's cold-start sample (`auto-labeling/references/cold-start.md`, Step B): rows with an id field and the input fields only, which people label from scratch. Auto-labeling folds the export of either back by each record's id field (`id` by default); what that asks of this skill (the ids, what annotators see, the question and the export) is in `references/auto-labeling-input.md` (Workflow G).
- The only `dataset-transformation` activation this skill performs is in Step 8 (post-annotation edits).
- Data split paths are documented in the specification (Label Studio mode) or the workflow state (local review) for clear handoff to setup skills or downstream skills.
- Local review writes to `local_review_feedback.jsonl` using the same canonical field schema Label Studio exports produce — Step 6's summary code does not branch on review mode.
