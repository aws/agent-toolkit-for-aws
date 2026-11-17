# Directory Management

## Principles

1. **One thing at a time.** Each response advances exactly one decision.
2. **Confirm before proceeding.** Always wait for the user's reply before taking the next action. You are a guide, not a runaway train.
3. **A recommendation is not confirmation.** Presenting a suggested name does not mean the user has accepted it. You must receive an explicit reply before creating any directory. **MUST NOT create a directory, write any file, or run any shell command in the same response that proposes the project name.** Ask first. Stop. Wait for the reply. Then act.
4. **Always end with a question.** Whenever you ask the user something, your response must end with that question. Never answer your own question in the same turn.
5. **Always show the full path.** When proposing a project directory, display the complete path (e.g. `./my-project-name/`) so the user can see exactly where it will be created before confirming.

## Project Setup

Before any work begins, resolve the project name:

1. If the project name is already known from conversation context, use it.
2. Otherwise, scan for existing `*/specs/PLAN.md` files in the current directory (PLAN.md lives under the project's `specs/` directory, per the structure below — a `*/PLAN.md` glob matches only one level and never finds it). If found, ask the user if they are resuming an existing project and load that `PLAN.md` into context.
3. **Ask for confirmation.** Derive a ≤64-char lowercase slug (`[a-z0-9-]` only) from the conversation context and present it to the user as a question, showing the full path — for example: *"I'll create the project folder at `./my-project-name/` — does that work, or would you prefer a different name or location?"* End your response there. Do not create the directory, do not write any files, and do not run any commands in this step.

   ⏸ Wait for the user's reply before proceeding.

4. **Create the directory.** Once the user confirms the name (or provides an alternative), create the `<project-name>/` directory and its subdirectories.

## Directory Structure

When working with the agent, all generated files are organized under an project directory.

Create `<project-name>/` under the user's working directory, never under `/tmp` or another scratch path, so the user and any later step can find the files.

```
<project-name>/
├── specs/  
│   ├── PLAN.md             # Your customization plan
├── corpus/                 # Source data being worked on (resolved local copy)
│   ├── corpus.jsonl        # e.g. an auto-labeling run's resolved input corpus (local)
│   ├── corpus.ref.json     # pointer (source_s3_uri/etag/size/hub_arn/...) when a remote
│   │                       #   s3://-or-ARN corpus is resolved --no-download and left in its bucket
│   ├── head.jsonl          # first ~200 rows of a remote corpus (one ranged GetObject); the
│   │                       #   only corpus data on disk in s3:// mode - read by the sample peeks
│   │                       #   (task detection, text-field inference)
├── splits/                 # Train/dev/val/test partitions of the corpus
│   ├── dev.jsonl
│   ├── val.jsonl
│   ├── test.jsonl
├── scripts/                # Generated Python scripts
│   ├── <project-name>_transform_fn.py
├── notebooks/              # Generated Jupyter notebooks
│   ├── <project-name>.ipynb
├── manifests/              # Machine-readable outputs (JSON)
└── run-log.jsonl           # One JSON line per run event, appended only by scripts/run_log.py
```

## Run Log

`<project-dir>/run-log.jsonl` holds what a later step, a report, or a resumed session reads: one JSON object per line, one line per event (a job's launch or result, an analysis result, a decision, an approval, the run parameters, a score). `scripts/run_log.py` is the only writer, and every script, template and agent step appends to this same file. A project has one run log at the project root; a step that puts its artifacts in a subdirectory such as `iter_{N}/` still appends to it, and the writer resolves a subdirectory to its project.

- **The agent records an event** by running the writer, with the values as fields. It never writes an entry, or a JSON file an entry names, by hand:

  ```bash
  python3 <skill-root>/references/directory-management/scripts/run_log.py write --project-dir <project-dir> \
    --kind decision --step iteration-decision --iteration 2 --status continue --field reason='"below target"'
  ```

  The command prints the new entry's `id`. `--field key=value` parses the value as JSON when it can, otherwise keeps it as a string; `--fields-json '{...}'` passes several at once. `run_log.py list --project-dir <project-dir> [--id ID] [--kind K] [--step S] [--iteration N] [--status X] [--latest]` prints matching entries, oldest first, each with its `id`.
- **Code templates and bundled scripts** import the writer (`from run_log import record_job, write_entry`) and call it when they launch a job and when they record its result; `write_entry()` and `record_job()` return the new entry's `id`. A template's placeholders for it:
  - `[RUN_LOG_WRITER_DIR]` — the absolute path of this capability's `scripts/` directory in the installed skill, e.g. `/home/me/.kiro/skills/aws-ai-ml/references/directory-management/scripts`.
  - `[PROJECT_DIR]` — the project directory, relative or absolute, e.g. `my-project`.
  - `[RUN_LOG_STEP]` — the plan step's name in kebab-case, e.g. `fine-tune-model`; outside a plan, the task's name.
  - `[RUN_LOG_ITERATION]` — the iteration integer; `0` for setup and the baseline.
- **Fields.** Every entry carries `kind`, `step` (the plan step's name in kebab-case), `iteration` (0 for setup and the baseline), `created_at` (set by the writer) and `status`. A `job` entry also carries `arn`, and its status is `launched`, `completed`, `failed` or `stopped`. `kind` is one of `parameters`, `job`, `artifact`, `analysis`, `decision`, `approval`, `score`, `incident`.
- **Ids and paths.** The writer sets each entry's `id` from `kind`, `step`, `iteration` and `status` (`job-fine-tune-model-iter1-launched`) and adds a counter when the id is taken, so ids are unique within the file. An entry is referred to by its `id`. The writer appends each line under an exclusive file lock, so scripts running at the same time never interleave lines or reuse an `id`. Paths inside the project are stored relative to the project directory, whether `--project-dir` is relative or absolute.
- **The file is append-only.** An entry is never rewritten, and the file is never rewritten, truncated or reordered. A status change, such as a job going from launched to completed, is a new line.
- **An entry is the only copy of its fact.** When a script already writes the fact to a file under `manifests/`, the entry names that file and carries only what the file lacks (the step, the status, the job ARN). An entry that builds on another names that entry's `id` instead of copying its values.
- **Approvals come from the user.** The agent records an approval (`--kind approval`) after the user gives it, or with `--status waived` when an autonomous run waives the gate. `write_entry()` refuses `kind="approval"`, so code never writes one.

The `corpus/` and `splits/` slots hold the data a run operates on: the resolved
source corpus and its partitions. Skills that split a dataset (e.g. auto-labeling)
write the dev/val/test partitions under `splits/` and keep the resolved input under
`corpus/`, so the inputs a run reproduces from live in a fixed, discoverable place
alongside the generated scripts and notebooks.
