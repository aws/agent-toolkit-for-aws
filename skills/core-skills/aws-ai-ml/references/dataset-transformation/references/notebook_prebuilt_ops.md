# Notebook Pre-Built Ops and Manifest Integration

This reference explains how `transform_helpers.py`, `dedup_filter.py`,
`dataset_split.py`, and `manifest_writer.py` support a portable project
notebook. Read it with `notebook_structure.md`, `notebook_run_lifecycle.md`,
`op_dedup.md`, and `op_split.md`.

## Copy Skill Scripts Into the Project

Before generating notebook cells, copy these files from the skill's `scripts/`
directory into `<project-dir>/scripts/`:

| File                   | Purpose                                                                |
| ---------------------- | ---------------------------------------------------------------------- |
| `transform_helpers.py` | `init_manifest`, `record_step`, `finalize`, and `run_record_transform` |
| `manifest_writer.py`   | On-disk manifest implementation                                        |
| `dedup_filter.py`      | `dedup_dataset`                                                        |
| `dataset_split.py`     | `split_dataset`                                                        |

Create `<project-dir>/scripts/` if needed. Copy only a missing destination file;
preserve an existing file so user edits are never silently overwritten. If the
user explicitly requests a refresh, compare the files, show the proposed
replacement, and obtain confirmation before replacing it.

This copy-on-first-use design makes the notebook portable and pins helper
behavior to the project. The trade-off is that project copies do not
automatically receive later skill changes.

Notebook-native runs do not create `scripts/run_NNN/<op>_fn.py`; executable
step cells come from the operation templates.

## Bootstrap Procedure

The bootstrap is an out-of-band agent action, not a notebook cell:

If the skill was loaded through `retrieve_skill`, follow the SKILL.md guardrail
instead of copying: retrieve each file as
`references/dataset-transformation/scripts/<file>` and write it to the destination.

1. Resolve the loaded skill's `scripts/` directory and the project directory.
2. Create the project `scripts/` directory.
3. For each file above, copy it only when the destination does not exist.
4. Verify all four destination files are readable before assembling cells.

Do not duplicate this procedure as executable Markdown. Use standard
file-copying tools and report which files were copied or preserved.

## Import and Manifest Pattern

`transformation.py` Cell 1 contains the canonical
`sys.path.insert(0, "scripts")` bootstrap and imports `init_manifest`,
`record_step`, `finalize`, and `run_record_transform`. Cell 2 contains the
canonical `init_manifest` call.

`init_manifest` constructs the underlying `ManifestWriter`, writes a partial
manifest immediately, and returns the writer. `record_step` replaces the
matching step entry and re-persists partial progress. `finalize` copies the
last output, updates `final_output`, marks the run completed, and writes the
manifest.

Direct `ManifestWriter` use remains available to script delivery. Notebook
delivery standardizes on the helper API.

## Invoke Pre-Built Operations

Dedup and split are direct function calls. There is no `%%writefile` cell,
`subprocess.run`, or generated per-run script.

- Dedup uses `transformation.py` Cell 3 and the project-local
  `scripts/dedup_filter.py`.
- Split uses `transformation.py` Cell 4 and the project-local
  `scripts/dataset_split.py`.
- Split-as-final uses `transformation.py` Cell 6 to finalize every split file.

The selected cell is copied from the template, every placeholder is replaced,
and `metadata.run` is attached by the notebook assembler.

`record_step` derives counts from the returned stats. Dedup uses `total` and
`kept`; split uses `input_records` and `output_records`. Split records its
directory as the step output and records per-split counts in `parameters`.

## Path and Re-Run Contract

The first step reads `INPUT_PATH`; later steps read the prior step output.
Single-file outputs use `step_K_<op>.jsonl`. Split uses `step_K_split/`.

Fixed paths make a step cell safe to re-run: the operation overwrites its
intermediate result, and manifest read-modify-write replaces the matching step
instead of appending a duplicate.

See `notebook_structure.md` for exact cell mapping and
`notebook_delivery.md` for the end-to-end assembly and validation procedure.
