#!/usr/bin/env python3
"""Shared file and run-log helpers for the auto-labeling scripts.

What the scripts share lives in the SDK's auto-labeling operators and is re-exported here
under the names the scripts use: the JSONL and S3 reads and the `confidence` reader
(`operators._rows`), the row-field contract between the labeling job, the review and
`fold_review.py` (`operators._fields`), the task-correctness rule and the task tables
(`operators._rowrule`), and the frozen-split state (`operators.seed`). What stays here is
the glue a command line needs: writing files, appending to and reading the project's run log
through the shared writer (directory-management/scripts/run_log.py, which the labeling-round
template also writes through), re-reading a labeling run's recorded invocation
(`operators.job.run_log`) for `emit_delivery.py --from-run-log`, and printing the
`client-read:` notices.
"""

import json
import os
import sys
import tempfile

_RUN_LOG_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "directory-management", "scripts"
)


def sdk_missing(e):
    """The message a script exits with when the V3 SDK's operators do not import."""
    return (
        "V3 SDK (sagemaker.ai_registry.DataPreparer) is not installed yet - this is an "
        "install step, not an environment limitation. Activate the `sdk-getting-started` "
        "skill and run its install to completion, then retry. Root cause: "
        f"{type(e).__name__}: {e}"
    )


try:
    import types as _types

    from sagemaker.ai_registry.data_preparer.auto_labeling.operators import _rows, _s3
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators._digest import (  # noqa: F401
        sha256_file,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators._fields import (  # noqa: F401
        BLIND_FIELD_SET,
        BLIND_FIELDS,
        CONTAINER_BLIND_FIELDS,
        GOLDEN_REVIEW_FIELD,
        JOB_ROW_FIELDS,
        LABELED_BY_FIELD,
        LABELED_BY_PEOPLE,
        LEGACY_REVIEW_REASON_FIELDS,
        MODEL_OUTPUT_FIELD,
        MODEL_OUTPUT_FIELDS,
        MODEL_OUTPUT_SUFFIX,
        OPTION_RESERVED_FIELDS,
        PEOPLE_LABELED_PROVENANCE,
        RECALIBRATION_FIELDS,
        REVIEW_HIDDEN_FIELDS,
        REVIEW_REASON_FIELD,
        REVIEWED_UNTAGGED,
        SEED_METADATA_FIELDS,
        SPOT_CHECK_REASONS,
        STATED_CONFIDENCE_FIELDS,
        STATED_CONFIDENCE_MISSING_RATE,
        VERBALIZED_CONFIDENCE_FIELDS,
        blind_row,
        fold_report_path,
        job_summary_sha256,
        join_model_output,
        labeled_by_people,
        model_output_candidates,
        model_output_path,
        reserved_field_reason,
        reserved_text_field_conflicts,
        review_hidden_fields,
        review_reason_of,
        stated_confidence_missing,
        unblind_row,
        verbalized_confidence_missing,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators._rowrule import (  # noqa: F401
        DEFAULT_CORRECT_TOLERANCE,
        GT_FIELD_FOR_PRED,
        NO_PROMISE_TASKS,
        QA_MATCH_DEFAULT,
        TASK_FIELDS,
        label_matches,
        label_text,
        ner_span_set,
        no_promise_reason,
        parse_qa_match,
        qa_correct,
        squad_normalize,
        task_correct,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators._rows import (  # noqa: F401
        CLIENT_READ_MAX_BYTES,
        HEAD_ROWS,
        JSONL_HINT,
        confidence,
        read_jsonl,
        s3_uri_for_input,
    )
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.job import run_log as _records
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed import split as _split
    from sagemaker.ai_registry.data_preparer.auto_labeling.operators.seed import (
        split_state as _split_state,
    )

    # The frozen split as the human-in-the-loop scripts use it: the SDK's decisions (seed.split) and its
    # project layer (seed.split_state, which writes the files and the run-log entries).
    split_state = _types.SimpleNamespace(
        SplitGuardError=_split.SplitGuardError,
        find_splits_dir=_split.find_splits_dir,
        nearest_project=_split.nearest_project,
        load_state=_split.load_state,
        state_path=_split.state_path,
        test_ids=_split.test_ids,
        verify=_split.verify,
        sha256_file=sha256_file,
        freeze=_split_state.freeze_split,
        rehash=_split_state.rehash_split,
        relabel=_split_state.relabel_split,
        guard_read=_split_state.guard_split_read,
        log_test_read=_split_state.log_test_read,
    )
    from sagemaker.core import Attribution, set_attribution
except ImportError as e:
    sys.exit(sdk_missing(e))

set_attribution(Attribution.SAGEMAKER_AGENT_PLUGIN)


# --- the project's run log (the shared writer) --------------------------------------


def _run_log():
    if _RUN_LOG_DIR not in sys.path:
        sys.path.insert(0, _RUN_LOG_DIR)
    import run_log

    return run_log


def record_entry(project_dir, *, kind, step, iteration, status, **fields):
    """Append one entry to the project's run log through the shared writer and return
    its `id`. The writer refuses `kind="approval"`: the agent records approvals."""
    return _run_log().write_entry(
        project_dir, kind=kind, step=step, iteration=iteration, status=status, **fields
    )


def read_run_entries(project_dir, **filters):
    """The project's run-log entries matching `filters`, oldest first (shared reader)."""
    return _run_log().read_entries(project_dir, **filters)


# --- a labeling run's recorded invocation ----------------------------------------
# The labeling round (code_templates/labeling_round.py) records each run as one `job` entry
# per labeling job and one `artifact` entry (`labeling_run: true`) naming them, all through the
# shared writer; `operators.job.run_log` rebuilds a run from those entries.


def labeling_run_invocation(project, entry_id=None):
    """The `invocation` a labeling run recorded, with its paths resolved against the
    project: the run with `entry_id`, else the newest run. Raises ValueError when
    the run log has no such run or the run recorded no invocation."""
    run_log = _run_log()
    return _records.labeling_run_invocation(
        run_log.read_entries(project), run_log.resolve_project_dir(project), entry_id=entry_id
    )


# --- files ----------------------------------------------------------------------------


def upload_file(path, s3_uri, region):
    """Upload one local file to an exact s3:// key (the SDK's transfer; a test stubs ``_s3``)."""
    _s3.upload_file(path, s3_uri, region)
    return s3_uri


def download_file(s3_uri, local, region):
    """Download one s3:// object to a local path (the SDK's transfer; a test stubs ``_s3``)."""
    return _s3.download_file(s3_uri, local, region)


def write_jsonl(path, rows):
    """Write rows as JSONL (one compact object per line, unicode preserved)."""
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def write_text_atomic(path, text):
    """Write via a temp file beside path and os.replace: a killed or failed write leaves the old file
    whole. The file keeps its old permission bits (or the umask's, for a new file)."""
    if os.path.exists(path):
        mode = os.stat(path).st_mode & 0o7777
    else:  # reading the umask sets it, so only a new file does
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:  # a failed cleanup never hides the error that stopped the write
            os.unlink(tmp)
        except OSError:
            pass
        raise


# --- client reads ---------------------------------------------------------------------
# The corpus stays behind the API: every read of customer rows on the client is one
# stderr line naming the primitive and the row count, never a row's content. The prefix
# is `client-read:`, not `WARNING:`, so it does not trip the actionable-WARNING checks.


def warn_client_read(primitive, n_rows, stream=None):
    """One stderr line naming the primitive and the `n_rows` customer rows it read on
    the client."""
    print(_rows.client_read_message(primitive, n_rows), file=stream or sys.stderr)


def head_rows(uri, max_rows=HEAD_ROWS, max_bytes=65_536, region=None):
    """The first `max_rows` JSONL records of an ``s3://`` object from one ranged
    GetObject of `max_bytes` (`operators.common.rows.head_rows`), reported as
    `client-read:`."""
    _rows.print_client_reads()
    return _rows.head_rows(uri, max_rows=max_rows, max_bytes=max_bytes, region=region)


def read_input_rows(path_or_uri, region=None, primitive="read_input_rows"):
    """Every non-blank JSONL record of a client-readable file (the cold-start sample,
    or a whole corpus no larger than it), never the unlabeled corpus or the corpus
    run's labels (`operators.common.rows.read_input_rows`). Reported as `client-read:`;
    a malformed line raises, and so does a file over CLIENT_READ_MAX_BYTES (ValueError,
    before any row is read)."""
    _rows.print_client_reads()
    return _rows.read_input_rows(path_or_uri, region=region, primitive=primitive)
