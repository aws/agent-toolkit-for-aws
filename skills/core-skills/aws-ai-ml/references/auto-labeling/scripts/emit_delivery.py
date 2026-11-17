#!/usr/bin/env python3
"""Emit a reproducible delivery artifact for a labeling run.

A paid labeling run leaves `labels.jsonl`, `held_out_report.json`, and its
run-log entries, but nothing the user can KEEP and re-run to reproduce the
run end to end. This emitter closes that gap: it turns the invocation the run
recorded (the `invocation` of the labeling run's run-log entry, written by the
labeling round) into a runnable artifact: the labeling round's code template
(code_templates/labeling_round.py) with the run's values filled in, so the user
re-runs the same job through the V3 SDK's auto-labeling operators.

Mirrors the synthetic-dataset-generation and dataset-quality skills' delivery convention: the same pipeline
is delivered through **two delivery modes** - a **script** and a **Jupyter
notebook** - that produce identical results; only the executor differs.

  - `--mode script`   → a self-contained Python script (`*_relabel.py`) the user
                        runs with `python <file>` to reproduce the run.
  - `--mode notebook` → a Jupyter notebook (`*_relabel.ipynb`) the user runs cell
                        by cell.

Both run the labeling round with the frozen arguments. The account-scoped inputs
(the S3 base, the role ARN) are read from the environment at run time, never
written into the artifact, so it is safe to share. The run-log writer's directory
(directory-management/scripts) is resolved at run time from
`$AUTOLABEL_SCRIPTS_DIR`, falling back to the path baked in at emit time.

stdlib only: a `.ipynb` is plain JSON, so `json` builds it - no nbformat / SDK.

Usage:
    # from the run's own run-log entry (the common case; --entry picks one run,
    # else the newest labeling run):
    python emit_delivery.py --from-run-log <proj> --entry <id> \
        --mode script   --out <proj>/scripts/relabel.py
    python emit_delivery.py --from-run-log <proj> --entry <id> \
        --mode notebook --out <proj>/notebooks/relabel.ipynb

    # or from an explicit invocation JSON:
    python emit_delivery.py --invocation '{"spec": "...", "input": "...", ...}' \
        --mode script --out relabel.py
"""

import argparse
import json
import os
import re
import sys

# The template the emitted artifact is: the labeling round over the SDK operators.
RUNNER = "code_templates/labeling_round.py"
_TEMPLATE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "code_templates",
    "labeling_round.py",
)

# Invocation-key → template setting. Order fixes a stable, readable artifact.
# `spec`/`input`/`out`/`generation_model_id`/`stage` are the required core; the rest are
# set only when the invocation carries a (non-None) value, so an artifact never sets a
# value the run did not use (the template's default stands).
_ARG_ORDER = [
    ("spec", "SPEC"),
    ("input", "INPUT_DATA"),
    ("out", "OUT"),
    ("project_dir", "PROJECT_DIR"),
    ("stage", "STAGE"),
    ("dataset_name", "DATASET_NAME"),
    ("generation_model_id", "GENERATION_MODEL_ID"),
    ("jury_models", "JURY_MODELS"),
    ("task", "TASK"),
    ("text_fields", "TEXT_FIELDS"),
    ("label_set", "LABEL_SET"),
    ("eval", "EVAL_DATA"),
    ("label_field", "LABEL_FIELD"),
    ("golden_review", "GOLDEN_REVIEW"),
    ("demos", "DEMOS"),
    ("demos_per_class", "DEMOS_PER_CLASS"),
    ("confidence_method", "CONFIDENCE_METHOD"),
    ("confidence_estimator", "CONFIDENCE_ESTIMATOR"),
    ("judge_models", "JUDGE_MODELS"),
    ("confidence_recalibration", "CONFIDENCE_RECALIBRATION"),
    ("recalibration_fit", "RECALIBRATION_FIT"),
    ("optimizer", "OPTIMIZER"),
    ("confidence_floor_bypass", "CONFIDENCE_FLOOR_BYPASS"),
    ("target", "TARGET"),
    ("review_dataset_name", "REVIEW_DATASET_NAME"),
    ("graders", "GRADERS"),
    ("hub_name", "HUB_NAME"),
    ("confirm_no_seed", "CONFIRM_NO_SEED"),
    ("append", "APPEND"),
    ("s3_prefix", "S3_PREFIX"),
    ("role_arn", "ROLE_ARN"),
    ("region", "REGION"),
    ("run_id", "RUN_ID"),
    ("submit_max_wait", "SUBMIT_MAX_WAIT"),
]

# Store-true flags: set True when the recorded value is true, left at the template's
# default when it is false.
_FLAG_ONLY = {"confirm_no_seed", "append", "confidence_floor_bypass"}

_REQUIRED = ("spec", "input", "out", "generation_model_id", "stage")

# Account-scoped inputs (the S3 base, the role ARN) are never written into the shareable
# artifact: they are environment variables the user sets, named as the labeling round
# reads them. invocation-key -> (setting, env var name).
_ENV_ARGS = [
    ("s3_prefix", "S3_PREFIX", "AUTOLABEL_S3_PREFIX"),
    ("role_arn", "ROLE_ARN", "AUTOLABEL_ROLE_ARN"),
]
_ENV_KEYS = {key for key, _setting, _env in _ENV_ARGS}


def env_args_for(inv):
    """(setting, env-var) pairs for the account-scoped inputs this run used (keys with a
    non-None value only)."""
    return [(setting, env) for key, setting, env in _ENV_ARGS if inv.get(key) not in (None, "")]


def invocation_to_settings(inv):
    """A recorded invocation as the template's settings ({SETTING: value}), in _ARG_ORDER,
    with only the keys that have a non-None value, as they are. The account-scoped keys
    (_ENV_KEYS) are left out: the artifact reads them from the environment. A _FLAG_ONLY
    key is set only when true. A test pins that every recorded key has an _ARG_ORDER entry."""
    known = {k for k, _setting in _ARG_ORDER}
    if inv.get("max_tpm") not in (None, ""):
        # --max-tpm is gone (the service refuses TargetTokensPerMinute). It only paced
        # the calls and never changed a label, so the replay drops it with a note.
        print(
            "NOTE: the recorded --max-tpm is dropped: the synthetic data generation service no longer takes "
            "TargetTokensPerMinute, and it never changed the labels.",
            file=sys.stderr,
        )
    removed = sorted(
        k
        for k, v in inv.items()
        if k not in known and k != "max_tpm" and v not in (None, "", False)
    )
    if inv.get("stage") in (None, "") or removed:
        # An invocation recorded before the labeling round took --stage ran the labeling
        # on the client, with flags the job-based round no longer has; replaying it
        # without them would label differently and say nothing.
        raise ValueError(
            "this invocation was recorded by an older labeling round (before one labeling "
            "job per --stage)"
            + (
                f"; it used flag(s) that no longer exist: {', '.join(removed)}"
                if removed
                else "; it has no --stage"
            )
            + ". It cannot be replayed as it was: run the corpus labeling again with the "
            "current skill (full-loop Step 7), then emit the artifact from that run."
        )
    missing = [k for k in _REQUIRED if inv.get(k) in (None, "")]
    if missing:
        raise ValueError(
            f"invocation is missing required key(s): {', '.join(missing)}. "
            f"Was it recorded by the labeling round?"
        )
    settings = {}
    for key, setting in _ARG_ORDER:
        if key not in inv or key in _ENV_KEYS:
            continue
        val = inv[key]
        if val is None:
            continue
        if key in _FLAG_ONLY:
            if val:
                settings[setting] = True
            continue
        settings[setting] = val
    return settings


_COST_NOTE = (
    "This reproduces a paid labeling run: it submits one labeling job (DataPreparer) "
    "that calls Amazon Bedrock. Bedrock Service Terms and pricing apply, and a jury run "
    "(JURY_MODELS) costs roughly Nx a single pass. Re-running with the same RUN_ID "
    "and STAGE re-attaches to the job already submitted instead of paying twice; use "
    "a new RUN_ID to label again. With WAIT = False (the default) a run submits the job "
    "and stops while it runs; run it again to collect the result, or set WAIT = True to "
    "wait for it."
)

_CELL_RE = re.compile(r"^# Cell (\d+)( \[markdown\])?: (.*)$", re.MULTILINE)
_SETTING_RE = re.compile(r"^([A-Z][A-Z0-9_]*) = (.*?)(\s+#.*)?$")


def template_cells(path=_TEMPLATE_PATH):
    """The template's cells as (number, is_markdown, label, source), in order."""
    text = open(path, encoding="utf-8").read()
    marks = list(_CELL_RE.finditer(text))
    cells = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        cells.append(
            (int(m.group(1)), bool(m.group(2)), m.group(3).strip(), text[m.end() : end].strip("\n"))
        )
    return cells


def _fill_settings(source, settings, env_pairs, scripts_dir):
    """The configuration cell with the run's values, the account-scoped inputs read from
    the environment, and the run-log writer's directory resolved at run time."""
    env_by_setting = dict(env_pairs)
    out = []
    for line in source.split("\n"):
        m = _SETTING_RE.match(line)
        if not m:
            out.append(line)
            continue
        name, comment = m.group(1), m.group(3) or ""
        if name in env_by_setting:
            out.append(f'{name} = os.environ.get("{env_by_setting[name]}"){comment}')
        elif name == "RUN_LOG_SCRIPTS":
            out.append(
                f'{name} = os.environ.get("AUTOLABEL_SCRIPTS_DIR", {scripts_dir!r}){comment}'
            )
        elif name in settings:
            out.append(f"{name} = {settings[name]!r}{comment}")
        else:
            out.append(line)
    return "\n".join(out)


_ENV_CHECK = """
missing = [env for env in {envs!r} if not os.environ.get(env)]
if missing:
    raise SystemExit("set the account-scoped input(s) in your environment before running: "
                     + ", ".join(missing)
                     + " (e.g. export AUTOLABEL_S3_PREFIX=s3://your-bucket/autolabel/proj/).")
"""


def render_script(inv, scripts_dir):
    """Full source for the `--mode script` artifact (a runnable .py)."""
    settings = invocation_to_settings(inv)
    env_pairs = env_args_for(inv)
    parts = [f'''#!/usr/bin/env python3
"""Reproduce this auto-labeling run end to end.

Generated by emit_delivery.py: the labeling round's code template with the arguments
the original run recorded, so the labeling run can be reproduced or audited later.

Account-scoped inputs (your S3 base and execution role ARN) are NOT baked into
this file - it is safe to share. Set them in the environment before running:

    export AUTOLABEL_S3_PREFIX=s3://your-bucket/autolabel/your-project/
    export AUTOLABEL_ROLE_ARN=<your SageMaker execution role ARN>

NOTE: {_COST_NOTE}
"""
import os
''']
    for _n, is_md, label, source in template_cells():
        if is_md:
            continue
        if label.startswith("Configuration"):
            source = _fill_settings(source, settings, env_pairs, scripts_dir)
            if env_pairs:
                source += "\n" + _ENV_CHECK.format(envs=[env for _s, env in env_pairs])
        parts.append(f"\n# {label}\n{source}\n")
    return "".join(parts)


def _cell(source, cell_type="code"):
    cell = {
        "cell_type": cell_type,
        "metadata": {},
        "source": source if isinstance(source, list) else [source],
    }
    if cell_type == "code":
        cell["execution_count"] = None
        cell["outputs"] = []
    return cell


def build_notebook(inv, scripts_dir):
    """A valid nbformat-4 notebook dict for `--mode notebook` (stdlib only)."""
    settings = invocation_to_settings(inv)
    env_pairs = env_args_for(inv)
    intro = _cell(
        [
            "# Reproduce this auto-labeling run\n",
            "\n",
            "Runs the labeling round (the V3 SDK's auto-labeling operators) with the "
            "arguments the original run recorded, so the labeling run can be reproduced or "
            "audited later.\n",
            "\n",
            "Account-scoped inputs (your S3 base and execution role ARN) are NOT "
            "baked into this notebook - it is safe to share. Set them in the "
            "`%env` cell below before running.\n",
            "\n",
            f"> WARNING: {_COST_NOTE}\n",
        ],
        cell_type="markdown",
    )
    # Account-scoped inputs as %env placeholders: %env persists across cells, while
    # `!export` runs in a throwaway subshell.
    env_lines = [
        "# Set your account-scoped inputs here, then run this cell. These persist\n",
        "# across cells (%env line magic), so the cells below pick them up.\n",
    ]
    if env_pairs:
        for _setting, env in env_pairs:
            env_lines.append(f"%env {env}=REPLACE_WITH_YOUR_{env}\n")
    else:
        env_lines.append("# (this run used no account-scoped inputs)\n")
    cells = [intro, _cell(env_lines)]
    for _n, is_md, label, source in template_cells():
        if is_md:
            continue
        if label.startswith("Configuration"):
            source = "import os\n\n" + _fill_settings(source, settings, env_pairs, scripts_dir)
            if env_pairs:
                source += "\n" + _ENV_CHECK.format(envs=[env for _s, env in env_pairs])
        cells.append(_cell([line + "\n" for line in (f"# {label}\n" + source).split("\n")]))
    return {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        },
        # nbformat_minor 4: 4.5 requires a per-cell `id`, which _cell() does not emit.
        "nbformat": 4,
        "nbformat_minor": 4,
    }


def _default_out(mode, run_log_path, inv):
    base = os.path.dirname(os.path.abspath(run_log_path)) if run_log_path else "."
    stem = (inv.get("task") or "labeling") + "_relabel"
    return os.path.join(base, stem + (".ipynb" if mode == "notebook" else ".py"))


def emit(inv, mode, out_path, scripts_dir):
    """Write the artifact to `out_path` and return the path."""
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    if mode == "notebook":
        with open(out_path, "w") as f:
            json.dump(build_notebook(inv, scripts_dir), f, indent=1)
    else:
        with open(out_path, "w") as f:
            f.write(render_script(inv, scripts_dir))
    return out_path


def _default_scripts_dir():
    """The run-log writer's directory (directory-management/scripts), beside this skill."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(here)), "directory-management", "scripts")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--from-run-log",
        metavar="PROJECT_DIR",
        help="project dir whose run-log.jsonl records the labeling run "
        "(reads its entry's `invocation`).",
    )
    src.add_argument("--invocation", help="explicit invocation as a JSON object string.")
    ap.add_argument(
        "--entry",
        default=None,
        help="with --from-run-log: the id of the labeling run's entry. "
        "Defaults to the newest labeling run.",
    )
    ap.add_argument(
        "--mode",
        choices=("script", "notebook"),
        default="script",
        help="delivery mode: a runnable .py (default) or a .ipynb.",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="artifact path. Defaults to <task>_relabel.{py,ipynb} " "in the project dir.",
    )
    ap.add_argument(
        "--scripts-dir",
        default=None,
        help="the run-log writer's dir (directory-management/scripts) baked into "
        "the artifact as the default AUTOLABEL_SCRIPTS_DIR. Defaults to the "
        "one beside this skill.",
    )
    args = ap.parse_args(argv)

    if args.invocation:
        inv = json.loads(args.invocation)
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from io_utils import labeling_run_invocation

        inv = labeling_run_invocation(args.from_run_log, args.entry)

    scripts_dir = args.scripts_dir or _default_scripts_dir()
    anchor = os.path.join(args.from_run_log, "run-log.jsonl") if args.from_run_log else None
    out_path = args.out or _default_out(args.mode, anchor, inv)
    emit(inv, args.mode, out_path, scripts_dir)
    print(json.dumps({"mode": args.mode, "out": out_path, "reproduces": RUNNER}, indent=2))


if __name__ == "__main__":
    main()
