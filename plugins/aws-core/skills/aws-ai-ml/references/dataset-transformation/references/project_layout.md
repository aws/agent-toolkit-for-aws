# Project Layout

Both delivery modes use the same project root and run numbering:

- `specs/transformation_spec_run_NNN.json` — saved transformation spec.
- `scripts/api_<capability>_job_J_run_NNN.py` — API script-delivery artifact
  for service-job ordinal `J`.
- `scripts/transformer.py` — editable reviewed direct-BYOC source after the
  existing-file collision check.
- `scripts/transform_helpers.py`, `manifest_writer.py`, `dedup_filter.py`, and
  `dataset_split.py` — local-lane helper copies used by notebook mode.
- `scripts/run_NNN/<op>_fn.py` — local-lane generated script-mode operations.
- `data/raw/<input>` — local-lane location for local or explicitly staged
  inputs.
- `data/transformed/run_NNN/step_K_<op>.jsonl` — intermediate single-file
  local-lane outputs; split uses a `step_K_split/` directory.
- `manifests/transformation_manifest_run_NNN.json` — local-lane run record.
- `notebooks/<project-name>.ipynb` — singular append-only notebook.
- `review/<codegen-job-name>/transformer.py` and `sample_output.jsonl` —
  permission-restricted transient CodeGen review copies, not the authoritative
  service run record. Remove the containing review directory after the user
  approves or rejects the candidate; do not retain these copies as project
  artifacts.

On the default API route, S3 inputs remain S3 URIs and are not downloaded into
`data/raw/`. When the user explicitly confirms the local lane for an S3 or Hub
source and approves staging, download the one resolved exact object unchanged
into `data/raw/`.
Notebook-native runs do not create `scripts/run_NNN/`; their operation cells
come from `code_templates/`. Script delivery creates that directory for
local generated scripts; API script delivery writes the standalone API
submission artifact instead.

The same run number identifies the same run everywhere. Paths use zero-padded
`NNN`; notebook headings use unpadded `N`. See
`notebook_run_lifecycle.md` for append and collision rules.
