# Full loop, Steps 8 to 9: the report, the Hub registration and the delivery artifact

Loaded from `references/full-loop.md` after Step 7 (and after Step 7b when a review ran,
`references/full-loop-review.md`). Step 8 writes the run report, Step 8b registers the labeled
dataset in the Hub, Step 8c emits the reproducible delivery artifact and Step 9 is the planning
run-report integration. The step numbers are unchanged. Then finish with Step 10 and Step 11 in
`references/full-loop.md`.

## Step 8 - Report

This step is required for every task, ordinal and llm_judge included. Do not tell
the user the run is done until the run report has written `report.html` and
`report.md` in the project directory. A held-out score that only sits in a score
file, or only in the chat, has not been reported.

Produce a single self-contained HTML the user can open and share:

`code_templates/run_report.py` with `[PROJECT_DIR]` `<proj>` and `[DATASET]` `"<name>"` (the other settings keep
their defaults; `FORMAT` is `both`). Set `[CALIBRATION]` only when the job's `labeling_summary.json` is not
`<proj>/labeling_summary.json`.

It needs no task, gold or threshold flag: the job graded the task, chose the cutoff
(`AcceptThreshold` in `labeling_summary.json`) and wrote the held-out score, and the
report reads them from the project. It renders the job's certificate (`Status`, target,
the accepted rows' bound, coverage, cutoff, spot-check) as the "Accuracy guarantee"
block. Do not pass `--gt`: the report never joins gold to rows.

> **Run the report template with the Step 0.1 interpreter** (`python`): like every script here it imports the SDK's operators (the split guard checks the `GT` read with them). Do not use a bare `python` outside the venv: on Amazon Linux 2 it is Python 2.7, and the run report (`code_templates/run_report.py`) fails with a SyntaxError.

**What the report shows.** The corpus run's labels stay behind the API, so its project
has `labeled_dataset.json` and no `labels.jsonl`, and the report is built from
what is on the client: the deliverable record, the job summary (the certificate, with the
fold's spot-check), `held_out_report.json` (the per-class or per-type F1 and the top
confusions), the review set's size by split (`RowsRouted` and `SpotCheckRows`; no review
row is downloaded) and the run log (the jury's missing ballots). It names the labeled
DataSet ARN and the labels' S3 URI and points at `job_report.html`. It draws no per-row
section, since those rows would be the labeled corpus. On the whole-corpus cold start
(`references/cold-start.md`, Step A) the project has a local `labels.jsonl` of people's
labels instead, and the report states its rows, who labeled them, the class balance, a
few samples and the columns. With neither file the report fails loudly: the run did not
complete.

Both `report.html` and `report.md` are written by default (`--format html|md|both`).
Unknown values read "n/a".

## Step 8b - Register the labeled dataset (Hub)

**By default there is nothing to register: the corpus job registered both DataSets**
(`dataset_arn`, the labeled rows under `DATASET_NAME`, and `review_dataset_arn`,
the review set under `REVIEW_DATASET_NAME`, in the submitter's output). Name the
two ARNs to the user after the report; they are the deliverable that dataset-quality
and fine-tuning find by ARN.

**When Step 7b applied an overlay**, the `promote` action added the corrected labels
as the labeled DataSet's next version, one above the job's: name that version's ARN
(the `dataset_arn` `promote` printed, not the overlay job's `OutputDatasetArns`
entry, which is a version of the view) as the deliverable, beside the review DataSet
ARN. Nothing is registered from a local labels file: the corpus run downloaded none.
The skill registers only the overlay rows (Step 7b, step 4: the `hub_ops` `register` action,
`<name>-corrections`, a new name with `APPEND` off), the `dt-view` the job reads, and the `promote` version.
From here on, every step that takes the labeled DataSet (the merge below, Step 11)
takes that version's ARN as `<dataset_arn>`, not `labeled_dataset.json`'s.
Contract and guards: `references/input-output-contract.md`, "Hub doors".

Use a per-project S3 prefix (e.g. `s3://<bucket>/autolabel/<project>/`) for the
whole run, so each project's working folders and outputs stay under one prefix. Names
must be alphanumerics and hyphens only (the Hub content-name pattern rejects
underscores); `register` checks this before uploading anything and suggests a valid
form - confirm the corrected name with the user rather than silently renaming. ⏸

Tell the user the resulting DataSet ARN. If registration degrades
(`hub_registered: false` in the output), the labeled data is still safely in S3 -
report the warning, do not treat the run as failed.

**Hand-off cleanup (the scratch DataSets).** Every refine round registered a scratch
DataSet version (`<name>-<stage>-<run id>`; the run log's `scratch` entries carry
each version's `arn` and `job_arn`), and every dataset-transformation job left a
`<name>-dt-input` view with its output on it (the `dt-view` action records
it; the outputs worth keeping were registered under their own names, or promoted).
Propose deleting them: name the N scratch entries (`<name>-dev-...`, `<name>-val-...`,
`<name>-dt-input`) and say that the S3 files stay and only the catalog entries go.
Run the cleanup on a yes. A view is deleted with the outputs of
the jobs run on it; another project's view of the same DataSet is kept (`kept`).
Deleting a Hub version cannot be undone. ⏸

`code_templates/hub_ops.py` with `[ACTION]` `scratch` and `[PROJECT_DIR]` `<proj>`: `DELETE = False` lists them;
`DELETE = True` deletes them, after the yes.

**Multi-column runs - offer the MERGED dataset as the DEFAULT deliverable.** When
the run labeled multiple label columns (one pass per column, e.g. several annotations
per clinical note), each pass's corpus run registers its own labeled DataSet. Do NOT
stop at N per-column datasets. Before registering, you MUST offer, as the default, to MERGE them into one
aligned dataset - one row per source record with every label column joined on the
shared record id - and register THAT merged dataset as the deliverable when the user
accepts, keeping the per-column datasets available too. The offer names the merged
dataset (`<name>-labeled`, one row per record, all label columns joined by id) and
that it is registered as the deliverable. The merge is a **dataset-transformation** hand-off: one CodeGen job
with `AutoExecute` true over a `hub_ops` `dt-view` of `<dataset_arn>`
of each per-column labeled DataSet (a dataset transformation job cannot read the job's output folder, and
its output lands as a version of its first input) and the shared id field. It joins
them by id, each column's `label` (and `confidence_score`) as its own field; tell it
not to raise on unmatched ids (it runs on a sample of each input first) and that
`transformed_records` is the output row count. Then the `hub_ops` `register-output` action
(`[FROM_ARN]` the `OutputDatasetArns` entry, `[NAME]` `<merged name>`, `[SOURCE_ARN]` the DataSet the job ran on,
`[PROJECT_DIR]` `<proj>`) registers
the merged DataSet under a new name (refused if the name exists). The rows stay
behind the API throughout. Do not call a multi-column run done without offering the
merge.

## Step 8c - Emit the reproducible delivery artifact

A paid labeling run should leave the user something they can KEEP and re-run, not
just a report. The labeling round records its resolved invocation in the
corpus run's run-log `artifact` entry (the entry whose `invocation.out` is
`labeled_dataset.json`; its `id` is the `run_log_entry` the run printed), and
`scripts/emit_delivery.py` turns that into a runnable artifact that reproduces the
corpus run (Step 7) end to end, in **two delivery modes** (as in the synthetic-dataset-generation /
dataset-quality skills; only the executor differs):

- **Script delivery** (default) - a self-contained `*_relabel.py` the user runs
  with `python <file>`.
- **Notebook delivery** - a `*_relabel.ipynb` the user runs cell by cell. Prefer
  this when the user asked for a notebook or a workflow wants a rerunnable artifact.

Default to script and mention the notebook option.

Script (default), under the project's `scripts/` slot:

```bash
python scripts/emit_delivery.py --from-run-log <proj> --entry <id> \
    --mode script --out <proj>/scripts/<name>_relabel.py
```

Notebook, under the project's `notebooks/` slot:

```bash
python scripts/emit_delivery.py --from-run-log <proj> --entry <id> \
    --mode notebook --out <proj>/notebooks/<name>_relabel.ipynb
```

The artifact is the labeling-round template (`code_templates/labeling_round.py`) with the
frozen arguments filled in as its settings (same
`RUN_ID` and `STAGE`, so a re-run re-attaches to the job already submitted; set
a new `RUN_ID` to label again); it runs on the SDK alone. Account-scoped
inputs (the S3 base and role ARN) are NOT baked into the artifact: they are read
from the environment (`AUTOLABEL_S3_PREFIX` / `AUTOLABEL_ROLE_ARN`) so the
script/notebook is shareable without leaking account ARNs. It resolves the shared
run-log writer's directory from `$AUTOLABEL_SCRIPTS_DIR` at run time, falling back to the
path baked in at emit time. Tell the user re-running it re-submits the paid
synthetic data generation and Bedrock jobs.

## Step 9 - Planning run-report integration (when run as a pipeline step)

The labeling round also records each run in the run log of the project
`PROJECT_DIR = <proj>` names: a `job` entry for the labeling job and an `artifact`
entry that names it and carries the run's `invocation` and the job's summary numbers
(`status: scratch` for a refine round, with the scratch DataSet version as `arn` and
the job as `job_arn`; `status: labeled` for the corpus run), so each iteration keeps
its own record; the run report reads the newest run of each output (the SDK's
`operators.job.run_log` builds and reads the entries). The record also carries the
planning skill's run-report contract (the primary job entry holds its `arn` and
`s3_paths`), so auto-labeling renders as a data-producing step inside a plan, like the
synthetic-dataset-generation skill's `report_s3_paths`:

- `report_s3_paths`: a `[{name, path}]` list covering the **labeling spec, input
  data, evaluation data, the job's output folder and labeling index, and the LABELED
  dataset output** - the exact named S3/local paths, read from the job's result, never
  reconstructed from the ARN. The planning skill copies this **verbatim** into the
  DataGeneration / Labeling step's `s3_paths`.
- `run_report`: a ready-made planning step entry (`type: "Labeling"`, description,
  `arn`, `region`, `s3_paths`) shaped to the planning skill's run-report-spec
  (the `sagemaker_jobs[]` step-entry schema; `type` is a DataGeneration/Labeling job).

Under the planning skill, treat auto-labeling as the pre-step that PRODUCES the
dataset a later fine-tuning / DI / model-customization step consumes.
