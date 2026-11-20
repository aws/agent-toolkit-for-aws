# The approval summary (HARD RULE #2)

What the pause before the first token-spending run shows the user. Read it with
`references/offer-options.md`; `references/full-loop.md` HARD RULE #2 is the rule, this is its
checklist. A yes here approves the default run (HARD RULE #4).

Show, in this order:

- **The corpus size**: the estimate from Step 0's first-row read.
- **The spec**: provided or induced. Show the spec you drafted and any label definitions you drafted
  (`references/spec-authoring.md`) for the user to approve here.
- **The split**: the dev / val / test sizes.
- **The model line**: the exact `GENERATION_MODEL_ID` (the one model every refine round runs) and
  every `JURY_MODELS` id of the corpus run (2 to 5 models on classification / ner / qa; the one
  model on ordinal / llm_judge / summarization). With `CONFIDENCE_METHOD = verbalized` or
  `CONFIDENCE_ESTIMATOR`: the one model and every `JUDGE_MODELS` id
  (`references/apply-and-confidence.md`); with a judge and no `JUDGE_MODELS`, that the labeling
  model also judges each row and is billed again for it. With `OPTIMIZER`: the teacher model,
  billed for its calls (`references/spec-refinement.md`, In-job search). For summarization the
  `GRADERS` too (`references/task-types.md`). Each id is one the service accepts verbatim: it
  refuses any other id (the `TeacherModel` too) at CreateJob, before any row is labeled, and the
  run relays its allowed list.
- **A rough cost.**
- **The accuracy target** `<target>` for the corpus run: default 0.90; the job certifies that at
  least that share of the auto-accepted rows is correct and routes the rest to review; 0.85 to
  0.99, stated so the user can change it (`references/apply-and-confidence.md`).
- **The DataSet names** the corpus run registers: `DATASET_NAME = <name>` for the labels,
  `REVIEW_DATASET_NAME = <name>-review` for the review set, and the scratch names the rounds
  register under (`<name>-<stage>-<run id>`, deleted at the hand-off, Step 8b).
- **The text columns** Step 0 found outside `TEXT_FIELDS` (`unpassed_text_fields`): ask whether
  each goes in.
- **The seed's ids**: when the seed was labeled outside this corpus, ask whether its ids are this
  corpus's ids for the same rows (Step 7).
- **That the runs are billed and not reversible**, and that the corpus run registers the two
  DataSets in the Hub (they can be deleted later; the S3 files stay).
- **An opt-in option**, only as `references/offer-options.md` says.

⏸ Wait for an explicit yes.
