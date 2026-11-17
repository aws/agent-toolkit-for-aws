#!/usr/bin/env python3
"""Materialize the training set for one iterative-SDG iteration.

Fine-tuning takes exactly ONE dataset (`training_dataset=<ARN>` is scalar, created
from a single S3 URI), and every grid trial in an iteration shares it. So training
on more than one iteration's generated data requires materializing one merged,
curated JSONL first. This script is that step.

Two modes:

  * ``replace``    — train on iteration N's generated data only (the loop default,
                     and the historical behavior).
  * ``accumulate`` — train on the *selected* previous iterations plus N, curated.

`accumulate` is deliberately selective and curated, not a blind union. The fixed
pipeline order is:

    select iterations -> concat oldest->newest -> structural filter
                      -> leakage guard -> dedup -> cap

  * **select** — iterations flagged harmful (their model collapsed or regressed
    materially) are excluded; error-analysis publishes the selection in
    `data_composition.include_iterations`, and ``--include-iterations`` overrides it.
  * **oldest -> newest** — dedup keeps the FIRST occurrence, so ordering this way
    keeps the earlier, already-trained-on record and drops the newer duplicate.
  * **structural filter** — drops rows that are junk as *training* rows
    (placeholder/empty completion, empty prompt, completion echoing the prompt).
  * **leakage guard** — drops training rows that are near-duplicates of `dev` or
    `test` rows. This reads the held-out splits ONLY to exclude overlap; test is
    never scored, selected, or terminated on here, so the held-out invariant is
    strengthened, not weakened. Splits may be JSONL or **parquet** (the benchmark
    datasets are parquet); parquet needs pyarrow or pandas, and `s3://` parquet is
    staged locally first. When a split cannot be read the guard says so loudly
    rather than reporting a clean result it never computed.
  * **dedup** — exact + optional MinHash-LSH fuzzy, via dataset-transformation's
    pre-built `dedup_filter.dedup_dataset`.

    **Defaults are `--dedup exact` and `--dedup-field completion`, deliberately.**
    Fuzzy matching on `prompt` is a trap for this loop: the prompt is a chat-message
    list whose *system prompt is identical on every row*, and character-n-gram
    shingles of that shared boilerplate dominate the Jaccard score. Measured on a
    real 2-iteration run (1000 rows):

        exact                      ->  999 kept  (1 real byte-identical duplicate)
        fuzzy on prompt            ->  165 kept  (834 FALSE duplicates, 83.5% loss)
        fuzzy on prompt+completion ->  254 kept  (still boilerplate-dominated)
        fuzzy on completion        ->  987 kept  (13 removed, plausible)

    So `exact` is the safe default, and if you opt into `--dedup fuzzy`, match on
    `completion` (the discriminating field). `--dedup-max-loss` additionally warns
    when dedup removes an implausible fraction of the data.
  * **cap** — newest-first: keep all of iteration N, then backfill from the
    next-newest included iteration until `--max-samples`. Deterministic.

Reuses existing utilities rather than reimplementing them: `transform_helpers`
(`iter_text_lines` streams S3 and local, `input_exists`, `copy_file`) and
`dedup_filter` (`dedup_dataset`, `MinHasher`, `MinHashLSH`) from the
dataset-transformation skill. Those scripts are called as LIBRARIES — invoking
dataset-transformation as a *skill* is not loop-safe (it pauses for confirmation
several times). The field-variance/placeholder primitives (`PLACEHOLDERS`,
`GOLD_KEYS`, `PROMPT_KEYS`) are defined locally in this module — they are NOT
imported from error-analysis, so this resolver takes no code dependency on the
error-analysis skill (which is splitting into client/server GapAnalysis skills).

Note on structural categorisation: error-analysis's `detectors.structural_categories()`
is written for *eval* rows and compares gold vs prediction, so on a training row
(which has no prediction) it would report `placeholder_output` for every row. This
script therefore owns the primitives above and applies training-row semantics
instead, rather than reusing that function.

Usage:
    python3 build_training_set.py <run_dir> --iteration N [--mode replace|accumulate]
            [--include-iterations 1,3] [--dedup fuzzy|exact|none] [--dedup-field prompt]
            [--threshold 0.9] [--no-filter-structural] [--no-leakage-guard]
            [--max-samples 4000] [--s3 s3://bucket/prefix/] [--check]
            [--expected-bucket-owner <12-digit account>]

Local-vs-cloud routing is the AGENT's job, not this script's — dataset-transformation
owns the decision (source location first, then size; always confirm with the user)
per `../references/routing-and-guardrails.md`. This script just runs the resolve
(`build()`); it does not size inputs, route, or carry a copy of the thresholds.

Cloud (BYOC) lane: do NOT write a second resolution. Author a thin
`transform_dataset(inputs, output_dir)` wrapper that imports this module and calls
`build()`; its interface and return (stats dict) shape are the contract in
`../references/api-execution-flow.md` → "Direct BYOC path". The one requirement that
contract does NOT state: **forward every resolution argument the local lane
(`main()`) passes, so the cloud and local lanes produce the SAME training set** —
`mode`, `include_iterations`, `dedup`, `dedup_fields`, `threshold`,
`filter_structural`, `leakage_guard`, `leakage_field`, `max_samples`,
`dedup_max_loss`, plus `s3_prefix=None` (the service owns upload). Drop any and the
wrapper silently falls back to `build()`'s defaults and diverges from the local run;
`include_iterations` is especially load-bearing for `accumulate`. Keeping the
pipeline in `build()` is the point — never re-derive the stages.

Writes `<run_dir>/iter_{N}/train/training_set_iter_{N}.jsonl` plus the manifest
`<run_dir>/manifests/training_set_iter_{N}.json`, and prints the row count and the
S3 URI to register with `DataSet.create(...)`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SKILLS_ROOT = Path(__file__).resolve().parents[2]
_DT_SCRIPTS = SKILLS_ROOT / "dataset-transformation" / "scripts"
if _DT_SCRIPTS.is_dir() and str(_DT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_DT_SCRIPTS))

# Reused from dataset-transformation (call as libraries, never as the skill).
# These modules use PEP-604 annotations, so they require Python >= 3.10 — the same
# floor the rest of the suite runs on. A failure here is caught (not just
# ImportError: an older interpreter raises TypeError while evaluating the
# annotations) so the pure helpers below stay importable for unit tests, and
# `_require_helpers()` turns it into an actionable message when actually needed.
_HELPER_IMPORT_ERROR: Optional[str] = None
try:
    from dedup_filter import MinHasher, MinHashLSH, dedup_dataset
    from transform_helpers import copy_file, input_exists, iter_text_lines
except Exception as _e:  # noqa: BLE001 - see comment above
    copy_file = input_exists = iter_text_lines = None
    MinHasher = MinHashLSH = dedup_dataset = None
    _HELPER_IMPORT_ERROR = f"{type(_e).__name__}: {_e}"


# Routing thresholds (LOCAL_CAP / API_CEILING) live in exactly one place —
# dataset-transformation/references/routing-and-guardrails.md. The agent reads
# them from there when it routes local vs cloud; this script does not size
# inputs or carry a copy of the numbers.


def _jaccard_from_sigs(a, b) -> float:
    """MinHash Jaccard estimate = fraction of equal signature positions.

    Reimplemented locally rather than importing dedup_filter's private
    `_jaccard_from_sigs`: depending on another module's underscore-prefixed
    symbol couples the leakage guard to its internals, so a rename there would
    break here silently. The estimate is trivial and self-contained.
    """
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    return sum(1 for x, y in zip(a, b) if x == y) / n


def _require_helpers() -> None:
    if iter_text_lines is None:
        raise RuntimeError(
            "could not import the dataset-transformation helpers "
            f"({_HELPER_IMPORT_ERROR}). They require Python >= 3.10; "
            f"run this script with the same interpreter the test suite uses."
        )


# Field-variance + placeholder primitives. Owned locally (static data, no
# behavior) rather than imported from error-analysis's `detectors`: the
# iterative-SDG resolver must not take a code dependency on the error-analysis
# skill, which is being split into client/server (GapAnalysis API) skills. The
# values mirror error-analysis's taxonomy "Field Name Variance" defaults; keep
# them in sync by convention, not by import.
GOLD_KEYS = ("gt_completion", "gt_label", "gt", "gold", "label", "completion")
PROMPT_KEYS = ("prompt", "input")
PLACEHOLDERS = {"", "n/a", "none", "null", "todo", "...", "[answer]"}

# Training-target placeholders: genuine non-answers and format artifacts only.
# Deliberately EXCLUDES `none`/`null`/`n/a`, which are valid labels for a training
# row (negative/absence classes), unlike the eval-prediction `PLACEHOLDERS` above.
_TRAINING_PLACEHOLDERS = {"", "todo", "...", "[answer]"}

STATE_SUBDIRS = ("", "specs")


# --------------------------------------------------------------------------
# io helpers
# --------------------------------------------------------------------------


def _read_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _read_state(run_dir: Path, name: str) -> Dict[str, Any]:
    for sub in STATE_SUBDIRS:
        d = _read_json(run_dir / sub / name) if sub else _read_json(run_dir / name)
        if isinstance(d, dict):
            return d
    return {}


def _lines(
    path: str, on_decode_error=None, expected_bucket_owner: Optional[str] = None
) -> Iterable[str]:
    """Stream a JSONL file, local or s3://, via the shared helper."""
    _require_helpers()
    return iter_text_lines(
        path, on_decode_error=on_decode_error, expected_bucket_owner=expected_bucket_owner
    )


def _read_rows(path: str, expected_bucket_owner: Optional[str] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    skipped = 0

    def count_decode_error():
        nonlocal skipped
        skipped += 1

    for line in _lines(
        path, on_decode_error=count_decode_error, expected_bucket_owner=expected_bucket_owner
    ):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    if skipped:
        print(
            f"WARNING: {path}: skipped {skipped} malformed JSONL line(s) "
            f"— training rows were dropped; check the source for corruption",
            file=sys.stderr,
        )
    return rows


# Splits are frequently stored as parquet (the benchmark datasets are), so the
# leakage guard must be able to read them — otherwise it silently screens nothing.
# pyarrow is preferred, pandas is the fallback; if neither is importable the guard
# says so loudly instead of reporting a clean result it never computed.
_PARQUET_SUFFIXES = (".parquet", ".pq")
_COLUMNAR_SUFFIXES = _PARQUET_SUFFIXES + (".arrow", ".feather")


def _read_parquet_rows(
    path: str, expected_bucket_owner: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Read a parquet file into row dicts. Stages s3:// locally first."""
    local = path
    tmp: Optional[Path] = None
    try:
        if path.startswith("s3://"):
            if copy_file is None:
                return [], "cannot stage s3:// parquet (transform_helpers unavailable)"
            import tempfile as _tf

            tmp = Path(_tf.mkdtemp()) / Path(path).name
            copy_file(path, str(tmp), expected_bucket_owner)
            local = str(tmp)
        try:
            import pyarrow.parquet as pq  # type: ignore

            return pq.read_table(local).to_pylist(), None
        except ImportError:
            pass
        try:
            import pandas as pd  # type: ignore

            df = pd.read_parquet(local)
            # pandas maps nulls to float('nan'), which is truthy and would leak
            # the string "nan" into the leakage guard; coerce to None so this
            # path matches pyarrow's to_pylist().
            rows = [
                {
                    key: (None if pd.api.types.is_scalar(value) and pd.isna(value) else value)
                    for key, value in record.items()
                }
                for record in df.to_dict(orient="records")
            ]
            return rows, None
        except ImportError:
            return [], (
                "parquet support needs pyarrow (preferred) or pandas; "
                "install one (pip install pyarrow==25.0.1) to enable the "
                "leakage guard on parquet splits"
            )
    except Exception as e:  # noqa: BLE001 - surfaced to the caller/manifest
        return [], f"{type(e).__name__}: {e}"
    finally:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
                tmp.parent.rmdir()
            except OSError:
                pass


def _read_rows_safe(
    path: str, expected_bucket_owner: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """(rows, error). Never raises — the caller reports what could not be read."""
    low = path.lower()
    if low.endswith(_PARQUET_SUFFIXES):
        return _read_parquet_rows(path, expected_bucket_owner)
    if low.endswith(_COLUMNAR_SUFFIXES):
        return [], (
            "this local parser has no validated reader for columnar format "
            f"({Path(path).suffix})"
        )
    try:
        return _read_rows(path, expected_bucket_owner), None
    except Exception as e:  # noqa: BLE001 - surfaced to the caller/manifest
        return [], f"{type(e).__name__}: {e}"


def _first(row: Dict[str, Any], keys) -> Optional[Any]:
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


def _text(row: Dict[str, Any], keys) -> str:
    v = _first(row, keys)
    return "" if v is None else str(v)


# --------------------------------------------------------------------------
# stage 1 — which iterations
# --------------------------------------------------------------------------


def latest_error_analysis(run_dir: Path) -> Dict[str, Any]:
    """Highest-numbered error_analysis_iter_*.json (its history is cumulative)."""
    best, best_n = {}, -1
    for f in (run_dir / "manifests").glob("error_analysis_iter_*.json"):
        try:
            n = int(f.stem.rsplit("_", 1)[1])
        except (IndexError, ValueError):
            continue
        if n > best_n:
            d = _read_json(f)
            if isinstance(d, dict):
                best, best_n = d, n
    return best


def _normalize_excluded(items: Any) -> List[Dict[str, Any]]:
    """Coerce a published excluded_iterations list into the {"iteration","reason"}
    dict shape _print_summary expects. error-analysis may write either dicts or
    bare iteration numbers; a bare-int list would otherwise crash _print_summary's
    ex.get("iteration")."""
    out: List[Dict[str, Any]] = []
    for it in items or []:
        if isinstance(it, dict):
            out.append(it)
        elif isinstance(it, (int, float)):
            out.append({"iteration": int(it), "reason": "excluded by error-analysis"})
    return out


def select_iterations(
    run_dir: Path,
    iteration: int,
    mode: str,
    override: Optional[List[int]],
) -> Tuple[List[int], List[Dict[str, Any]], str]:
    """Return (included, excluded_with_reasons, source_of_decision)."""
    if mode == "replace":
        return [iteration], [], "mode=replace"
    if override is not None:
        included = sorted({i for i in override if 1 <= i <= iteration})
        if iteration not in included:
            included.append(iteration)  # newest is always included
        return sorted(included), [], "--include-iterations"

    ea = latest_error_analysis(run_dir)
    dc = ea.get("data_composition") if isinstance(ea.get("data_composition"), dict) else {}
    assert dc is not None
    inc = dc.get("include_iterations")
    if isinstance(inc, list) and inc:
        included = sorted(
            {int(i) for i in inc if isinstance(i, (int, float)) and 1 <= int(i) <= iteration}
        )
        if iteration not in included:
            included.append(iteration)
        # error-analysis may publish excluded_iterations as dicts or as bare
        # ints; normalize to the {"iteration","reason"} shape _print_summary
        # expects so a plain-int list cannot crash it.
        excluded = _normalize_excluded(dc.get("excluded_iterations"))
        return sorted(included), excluded, "error-analysis"

    # No published selection: derive the same harmful-iteration rule locally from
    # iteration_history so the script is usable standalone.
    history = ea.get("iteration_history") or []
    baseline = None
    scores: Dict[int, float] = {}
    for h in history:
        if not isinstance(h, dict):
            continue
        it, acc = h.get("iteration"), h.get("overall_accuracy")
        if isinstance(it, (int, float)) and isinstance(acc, (int, float)):
            scores[int(it)] = float(acc)
    baseline = scores.get(0)

    # The screen fails OPEN: a missing baseline or a missing per-iteration score
    # makes the exclusion test False, so the iteration is INCLUDED. Warn when the
    # history is incomplete so a "nothing excluded" result is not mistaken for
    # "screened and clean" (same visibility rule as the leakage guard).
    if baseline is None:
        print(
            "WARN: no iteration-0 overall_accuracy in iteration_history; "
            "harmful-iteration screen cannot run -- NO iteration will be excluded",
            file=sys.stderr,
        )
    missing = [k for k in range(1, iteration) if k not in scores]
    if baseline is not None and missing:
        print(
            f"WARN: no score for iteration(s) {missing} in iteration_history; "
            "they are included unscreened (screen fails open)",
            file=sys.stderr,
        )

    included, excluded = [], []
    # Local fallback screen, used only when error-analysis's own harmful-iteration
    # verdict is unavailable. This is a deliberately LOOSER rule than
    # error-analysis/overview.md's definition (dev accuracy below the iteration-0
    # baseline OR improvement < -min_delta): here an iteration is excluded only on
    # a MATERIAL regression — more than `margin` below baseline — and `improvement`
    # is not consulted, so a noise-level dip does not drop a whole iteration's data.
    margin = 0.01
    for k in range(1, iteration + 1):
        if k == iteration:
            included.append(k)  # newest always included
            continue
        s = scores.get(k)
        if baseline is not None and s is not None and s < baseline - margin:
            excluded.append(
                {
                    "iteration": k,
                    "reason": f"dev {s:.4f} materially below baseline "
                    f"{baseline:.4f} (margin {margin})",
                }
            )
        else:
            included.append(k)
    return included, excluded, "derived from iteration_history"


def iteration_sources(run_dir: Path, iterations: List[int]) -> List[Tuple[int, str]]:
    """(iteration, path) for every JSONL under each iteration's data/ dir, oldest first."""
    out: List[Tuple[int, str]] = []
    for k in sorted(iterations):
        d = run_dir / f"iter_{k}" / "data"
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.jsonl")):
            out.append((k, str(f)))
    return out


# --------------------------------------------------------------------------
# stage 2 — structural filter (training-row semantics)
# --------------------------------------------------------------------------


def structural_issues(row: Dict[str, Any], completion_field: Optional[str] = None) -> List[str]:
    """Structural problems that make a row unusable as a TRAINING example.

    Deliberately not `detectors.structural_categories()`: that function compares
    gold vs prediction for EVAL rows and would flag every training row (no
    prediction) as `placeholder_output`. Reuses its primitives instead.

    `completion_field` is the SAME field dedup and the leakage guard key off
    (the primary `dedup_fields` entry, default `completion`). We read it first
    so a row carrying both a `label` and a `completion` has its structural
    junk-check run against the field the rest of the pipeline uses — otherwise
    `GOLD_KEYS`' first-match-wins order inspects `label`/`gt_*` ahead of
    `completion`, and an empty/placeholder `completion` could slip past the
    filter because the row's `label` was non-empty. `GOLD_KEYS` remains the
    fallback when the configured field is absent. A configured field that is
    present with a null value is treated as an empty completion rather than
    falling through to another gold field.
    """
    issues: List[str] = []
    prompt = _text(row, PROMPT_KEYS).strip()
    if completion_field and completion_field in row:
        configured_completion = row[completion_field]
        completion = ("" if configured_completion is None else str(configured_completion)).strip()
    else:
        completion = _text(row, GOLD_KEYS).strip()

    if completion.lower() in _TRAINING_PLACEHOLDERS:
        issues.append("placeholder_completion")
    if not prompt:
        issues.append("empty_prompt")
    if prompt and completion and prompt == completion:
        issues.append("completion_echoes_prompt")
    return issues


# --------------------------------------------------------------------------
# stage 3 — leakage guard vs dev/test
# --------------------------------------------------------------------------


def split_paths(run_dir: Path) -> Dict[str, str]:
    """dev/test paths from run_state.json (local preferred, else S3)."""
    state = _read_state(run_dir, "run_state.json")
    out: Dict[str, str] = {}
    for name, val in (state.get("splits") or {}).items():
        if name not in ("dev", "test"):
            continue
        if isinstance(val, str):
            out[name] = val
        elif isinstance(val, dict):
            p = val.get("local") or val.get("s3")
            if isinstance(p, str):
                out[name] = p
    return out


def leakage_indices(
    rows: List[Dict[str, Any]],
    heldout_texts: List[str],
    *,
    fields: List[str],
    threshold: float,
    num_perm: int = 256,
    ngram_size: int = 5,
) -> set:
    """Indices of `rows` that are near-duplicates of any held-out row."""
    if not heldout_texts:
        return set()
    if MinHasher is None or MinHashLSH is None:
        detail = f" ({_HELPER_IMPORT_ERROR})" if _HELPER_IMPORT_ERROR else ""
        raise RuntimeError(
            "held-out leakage checking requires the dataset-transformation "
            f"MinHash helpers, but they are unavailable{detail}"
        )
    hasher = MinHasher(num_perm=num_perm, ngram_size=ngram_size)
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)

    held_sigs: list = []
    for t in heldout_texts:
        if not t.strip():
            continue
        # Below the shingle size a MinHash signature carries no char-n-gram
        # evidence: _shingle collapses the string to a single whole-string
        # token, so two identical short strings score Jaccard 1.0 by exact
        # equality, not by near-duplication. For a label-style field (e.g.
        # "yes"/"positive") that would flag every training row sharing a class
        # label with a held-out row as leakage and silently drop it. Fuzzy
        # leakage only means something on texts long enough to shingle; shorter
        # ones are left to the exact-dedup/structural stages instead.
        if len(t.strip()) < ngram_size:
            continue
        sig = hasher.signature(t)
        # LSH keys must index the compact signature list, not the original
        # heldout_texts list: blank held-out rows are intentionally skipped.
        i = len(held_sigs)
        held_sigs.append(sig)
        lsh.insert(i, sig)

    hit = set()
    for idx, row in enumerate(rows):
        text = " ".join(str(row.get(f, "") or "") for f in fields).strip()
        # Same gate on the training side: a sub-ngram text cannot be a genuine
        # fuzzy near-duplicate of a held-out row, only an exact-label collision.
        if not text or len(text) < ngram_size:
            continue
        sig = hasher.signature(text)
        for cand in lsh.query(sig):
            if cand < len(held_sigs) and _jaccard_from_sigs(sig, held_sigs[cand]) >= threshold:
                hit.add(idx)
                break
    return hit


# --------------------------------------------------------------------------
# stage 5 — cap, newest-first
# --------------------------------------------------------------------------


def apply_cap(
    tagged: List[Tuple[int, Dict[str, Any]]],
    max_samples: Optional[int],
    newest: Optional[int] = None,
    quiet: bool = False,
):
    """Keep all of the newest iteration, then backfill from next-newest.

    When the newest iteration ALONE exceeds max_samples the "keep all of N"
    guarantee cannot hold, so N is truncated to the cap -- warn rather than
    truncate silently.
    """
    if not max_samples or len(tagged) <= max_samples:
        return tagged, 0
    if newest is not None:
        n_rows = sum(1 for it, _ in tagged if it == newest)
        if n_rows > max_samples and not quiet:
            print(
                f"WARNING: iteration {newest} has {n_rows} rows, above "
                f"--max-samples {max_samples}; the newest iteration is truncated "
                f"to the cap (the 'keep all of N' guarantee cannot be honored)",
                file=sys.stderr,
            )
    kept: List[Tuple[int, Dict[str, Any]]] = []
    for it in sorted({t[0] for t in tagged}, reverse=True):  # newest first
        for pair in [t for t in tagged if t[0] == it]:
            if len(kept) >= max_samples:
                break
            kept.append(pair)
        if len(kept) >= max_samples:
            break
    dropped = len(tagged) - len(kept)
    # Restore oldest->newest order for reproducible output.
    order = {id(p): i for i, p in enumerate(tagged)}
    kept.sort(key=lambda p: order[id(p)])
    return kept, dropped


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------


def build(
    run_dir: Path,
    iteration: int,
    *,
    mode: str = "replace",
    include_iterations: Optional[List[int]] = None,
    dedup: str = "exact",
    dedup_fields: Optional[List[str]] = None,
    threshold: float = 0.9,
    filter_structural: bool = True,
    leakage_guard: bool = True,
    leakage_field: str = "completion",
    max_samples: Optional[int] = None,
    dedup_max_loss: float = 0.5,
    s3_prefix: Optional[str] = None,
    check: bool = False,
    quiet: bool = False,
    expected_bucket_owner: Optional[str] = None,
) -> Dict[str, Any]:
    dedup_fields = dedup_fields or ["completion"]
    included, excluded, decided_by = select_iterations(run_dir, iteration, mode, include_iterations)
    sources = iteration_sources(run_dir, included)

    report: Dict[str, Any] = {
        "iteration": iteration,
        "mode": mode,
        "include_iterations": included,
        "excluded_iterations": excluded,
        "selection_source": decided_by,
        "sources": [{"iteration": k, "path": p} for k, p in sources],
        "stages": {},
    }
    if not sources:
        report["error"] = f"no JSONL found under iter_{{{','.join(map(str, included))}}}/data/"
        if not quiet:
            print(f"ERROR: {report['error']}", file=sys.stderr)
        return report

    # ---- concat, oldest -> newest --------------------------------------
    tagged: List[Tuple[int, Dict[str, Any]]] = []
    per_source: List[Dict[str, Any]] = []
    for k, path in sources:
        rows = _read_rows(path, expected_bucket_owner)
        per_source.append({"iteration": k, "path": path, "rows": len(rows)})
        tagged.extend((k, r) for r in rows)
    report["sources"] = per_source
    report["stages"]["concatenated"] = len(tagged)

    # ---- structural filter ---------------------------------------------
    struct_dropped = 0
    struct_reasons: Dict[str, int] = {}
    if filter_structural:
        keep: List[Tuple[int, Dict[str, Any]]] = []
        completion_field = dedup_fields[0] if dedup_fields else "completion"
        for k, row in tagged:
            issues = structural_issues(row, completion_field=completion_field)
            if issues:
                struct_dropped += 1
                for i in issues:
                    struct_reasons[i] = struct_reasons.get(i, 0) + 1
            else:
                keep.append((k, row))
        tagged = keep
    report["stages"]["structural_filtered"] = struct_dropped
    report["stages"]["structural_reasons"] = struct_reasons

    # ---- leakage guard vs dev/test -------------------------------------
    leak_dropped = 0
    leak_detail: Dict[str, Any] = {}
    if leakage_guard:
        paths = split_paths(run_dir)
        held: List[str] = []
        unchecked: List[str] = []
        if not paths:
            unchecked.append("no dev/test paths in run_state.json")
        for name, p in sorted(paths.items()):
            if input_exists is not None:
                try:
                    exists = input_exists(p, expected_bucket_owner)
                except Exception as e:  # noqa: BLE001 - record an unchecked split
                    check_error = f"{type(e).__name__}: {e}"
                    leak_detail[name] = f"existence check failed: {check_error}"
                    unchecked.append(f"{name} ({check_error})")
                    continue
                if not exists:
                    leak_detail[name] = "not found"
                    unchecked.append(f"{name} (not found)")
                    continue
            rows_h, err = _read_rows_safe(p, expected_bucket_owner)
            if err:
                leak_detail[name] = f"unreadable: {err}"
                unchecked.append(f"{name} ({err})")
                continue
            texts = [str(r.get(leakage_field, "") or "").strip() for r in rows_h]
            non_empty = [t for t in texts if t]
            if rows_h and not non_empty:
                # A field-name mismatch is indistinguishable from a clean split:
                # every text is "", nothing reaches `held`, the guard below never
                # runs, and `leakage_dropped: 0` reads as "screened, found nothing".
                # Generated rows use `completion`, but a benchmark's dev/test split
                # may key the answer `response` / `output` / `answer`, so name it.
                leak_detail[name] = f"no non-empty {leakage_field!r} in {len(rows_h)} rows"
                unchecked.append(f"{name} (field {leakage_field!r} absent/empty)")
                continue
            held.extend(non_empty)
            # Count what was actually comparable, not the row count — a partly
            # populated split would otherwise overstate the guard's coverage.
            leak_detail[name] = len(non_empty)
        leak_detail["field"] = leakage_field
        if held:
            rows_only = [r for _, r in tagged]
            before_leak = len(rows_only)
            hits = leakage_indices(rows_only, held, fields=[leakage_field], threshold=threshold)
            if hits:
                tagged = [p for i, p in enumerate(tagged) if i not in hits]
            leak_dropped = len(hits)
            # Safety rail, symmetric with dedup's loss guard: both warn at the
            # same configurable `dedup_max_loss` ceiling. An implausibly large
            # leakage drop usually means the matched field collapsed to a shared
            # label (e.g. a categorical answer identical across rows), not real
            # train/test overlap. Surface it rather than silently shrinking the set.
            leak_loss = leak_dropped / before_leak if before_leak else 0.0
            leak_detail["loss_fraction"] = round(leak_loss, 4)
            if leak_loss > dedup_max_loss:
                msg = (
                    f"leakage guard dropped {leak_loss:.1%} of training rows on "
                    f"field {leakage_field!r} (> --dedup-max-loss {dedup_max_loss:.0%}); "
                    f"a drop this large usually means the "
                    f"field is a shared label, not genuine leakage — review before training"
                )
                report.setdefault("warnings", []).append(msg)
                if not quiet:
                    print(f"WARNING: {msg}", file=sys.stderr)
        if unchecked:
            # Never let an unchecked guard read as a clean bill of health.
            report.setdefault("warnings", []).append(
                "leakage guard could not check: " + "; ".join(unchecked)
            )
            if not quiet:
                print(
                    f"WARNING: leakage guard could not check {'; '.join(unchecked)} "
                    f"— training rows were NOT screened against those splits",
                    file=sys.stderr,
                )
    report["stages"]["leakage_dropped"] = leak_dropped
    report["stages"]["leakage_sources"] = leak_detail

    # ---- dedup (delegated to the pre-built script) ----------------------
    out_dir = run_dir / f"iter_{iteration}" / "train"
    out_path = out_dir / f"training_set_iter_{iteration}.jsonl"
    dedup_stats: Dict[str, Any] = {"mode": dedup}

    if check:
        report["stages"]["after_dedup"] = None
        report["stages"]["capped"] = None
        report["final_rows"] = len(tagged)
        report["output"] = str(out_path)
        if not quiet:
            _print_summary(report, checked=True)
        return report

    out_dir.mkdir(parents=True, exist_ok=True)
    staged = out_dir / f".staged_iter_{iteration}.jsonl"
    staged.write_text("".join(json.dumps(r) + "\n" for _, r in tagged))

    if dedup != "none" and dedup_dataset is not None:
        before = len(tagged)
        deduped = out_dir / f".deduped_iter_{iteration}.jsonl"
        dedup_stats = dedup_dataset(
            str(staged), str(deduped), mode=dedup, threshold=threshold, fields=list(dedup_fields)
        )
        kept_keys = {json.dumps(r) for r in _read_rows(str(deduped))}
        tagged = _dedup_align(tagged, kept_keys)
        deduped.unlink(missing_ok=True)
        dedup_stats = dict(dedup_stats)
        dedup_stats["fields"] = list(dedup_fields)
        # Safety rail: an implausible loss almost always means the matched field is
        # dominated by shared boilerplate (e.g. an identical system prompt), not
        # that the data is genuinely duplicated.
        loss = (before - len(tagged)) / before if before else 0.0
        dedup_stats["loss_fraction"] = round(loss, 4)
        if loss > dedup_max_loss:
            msg = (
                f"dedup removed {loss:.1%} of rows on fields {list(dedup_fields)} "
                f"(> --dedup-max-loss {dedup_max_loss:.0%}) — the matched field is "
                f"likely dominated by shared boilerplate; review before training"
            )
            report.setdefault("warnings", []).append(msg)
            if not quiet:
                print(f"WARNING: {msg}", file=sys.stderr)
    staged.unlink(missing_ok=True)
    report["stages"]["dedup"] = dedup_stats
    report["stages"]["after_dedup"] = len(tagged)

    # ---- cap, newest-first ---------------------------------------------
    tagged, capped = apply_cap(tagged, max_samples, newest=iteration, quiet=quiet)
    report["stages"]["capped"] = capped

    # Every stage removed every row: a 0-row training set must not be written,
    # uploaded, or registered -- DataSet.create on an empty file fails opaquely
    # during training, and an unattended loop scanning for the canonical output
    # path must not pick up an empty dataset. Guard BEFORE the write so no
    # 0-byte file is ever materialized at out_path.
    report["final_rows"] = len(tagged)
    if not tagged:
        report["error"] = (
            "training set is empty after filter/leakage/dedup -- "
            "nothing to train on; not written, uploaded, or registered"
        )
        if not quiet:
            print(f"ERROR: {report['error']}", file=sys.stderr)
        man = run_dir / "manifests" / f"training_set_iter_{iteration}.json"
        man.parent.mkdir(parents=True, exist_ok=True)
        man.write_text(json.dumps(report, indent=2) + "\n")
        report["manifest"] = str(man)
        return report

    out_path.write_text("".join(json.dumps(r) + "\n" for _, r in tagged))
    report["output"] = str(out_path)
    report["rows_per_iteration"] = {str(k): sum(1 for kk, _ in tagged if kk == k) for k in included}

    if s3_prefix and copy_file is not None:
        uri = s3_prefix.rstrip("/") + "/" + out_path.name
        try:
            copy_file(str(out_path), uri, expected_bucket_owner)
            report["s3_uri"] = uri
        except Exception as _e:  # noqa: BLE001 - surfaced to the manifest, loop continues
            msg = f"S3 upload to {uri} failed: {type(_e).__name__}: {_e}"
            report.setdefault("warnings", []).append(msg)
            if not quiet:
                print(f"WARNING: {msg}", file=sys.stderr)

    man = run_dir / "manifests" / f"training_set_iter_{iteration}.json"
    man.parent.mkdir(parents=True, exist_ok=True)
    man.write_text(json.dumps(report, indent=2) + "\n")
    report["manifest"] = str(man)

    if not quiet:
        _print_summary(report)
    return report


def _dedup_align(tagged, kept_keys):
    """Re-select surviving (iteration, row) pairs, preserving order and first-wins."""
    out, seen = [], set()
    for k, row in tagged:
        key = json.dumps(row)
        if key in kept_keys and key not in seen:
            seen.add(key)
            out.append((k, row))
    return out


def _print_summary(report: Dict[str, Any], checked: bool = False) -> None:
    st = report["stages"]
    head = "would build" if checked else "wrote"
    print(f"{head} {report.get('output')}  ({report.get('final_rows')} rows)")
    print(
        f"  mode={report['mode']}  include={report['include_iterations']}"
        f"  (selected by {report['selection_source']})"
    )
    for ex in report.get("excluded_iterations") or []:
        print(f"  excluded iteration {ex.get('iteration')}: {ex.get('reason')}")
    for s in report.get("sources") or []:
        print(f"  source iter_{s['iteration']}: {s['rows']} rows  ({s['path']})")
    print(
        f"  concatenated={st.get('concatenated')}"
        f"  structural_filtered={st.get('structural_filtered')}"
        f"  leakage_dropped={st.get('leakage_dropped')}"
        f"  after_dedup={st.get('after_dedup')}  capped={st.get('capped')}"
    )
    if st.get("structural_reasons"):
        print(f"  structural reasons: {st['structural_reasons']}")
    if report.get("s3_uri"):
        print(f"  uploaded: {report['s3_uri']}")
        print(
            f"  register with: DataSet.create(name='<jobname>-cumulative-iter"
            f"{report['iteration']}', source='{report['s3_uri']}', wait=True)"
        )


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir")
    ap.add_argument("--iteration", type=int, required=True)
    ap.add_argument("--mode", choices=["replace", "accumulate"], default="replace")
    ap.add_argument(
        "--include-iterations",
        default=None,
        help="comma-separated iteration numbers (overrides error-analysis)",
    )
    ap.add_argument(
        "--dedup",
        choices=["fuzzy", "exact", "none"],
        default="exact",
        help="default exact; fuzzy on a boilerplate-heavy field gives huge "
        "false-positive loss (see module docstring)",
    )
    ap.add_argument(
        "--dedup-field",
        default="completion",
        help="comma-separated field(s) to match on (default: completion)",
    )
    ap.add_argument("--threshold", type=float, default=0.9)
    ap.add_argument(
        "--dedup-max-loss",
        type=float,
        default=0.5,
        help="warn when dedup removes more than this fraction (default 0.5)",
    )
    ap.add_argument(
        "--filter-structural", dest="filter_structural", action="store_true", default=True
    )
    ap.add_argument("--no-filter-structural", dest="filter_structural", action="store_false")
    ap.add_argument("--leakage-guard", dest="leakage_guard", action="store_true", default=True)
    ap.add_argument("--no-leakage-guard", dest="leakage_guard", action="store_false")
    ap.add_argument(
        "--leakage-field",
        default="completion",
        help="field compared against dev/test rows (default: completion)",
    )
    ap.add_argument("--max-samples", type=int, default=None)
    ap.add_argument("--s3", dest="s3_prefix", default=None)
    ap.add_argument(
        "--expected-bucket-owner",
        default=None,
        help="12-digit account that must own every s3:// bucket read or "
        "written (default: the caller's own account)",
    )
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.is_dir():
        print(f"ERROR: not a directory: {run_dir}", file=sys.stderr)
        return 1

    if not 0.0 <= args.threshold <= 1.0:
        print(
            "ERROR: --threshold must be between 0.0 and 1.0 (Jaccard similarity)", file=sys.stderr
        )
        return 1

    if args.max_samples is not None and args.max_samples < 1:
        print("ERROR: --max-samples must be a positive integer", file=sys.stderr)
        return 1

    inc = None
    if args.include_iterations:
        try:
            inc = [int(x) for x in args.include_iterations.replace(" ", "").split(",") if x]
        except ValueError:
            print("ERROR: --include-iterations must be comma-separated integers", file=sys.stderr)
            return 1
    fields = [f for f in args.dedup_field.replace(" ", "").split(",") if f] or ["completion"]
    report = build(
        run_dir,
        args.iteration,
        mode=args.mode,
        include_iterations=inc,
        dedup=args.dedup,
        dedup_fields=fields,
        threshold=args.threshold,
        filter_structural=args.filter_structural,
        leakage_guard=args.leakage_guard,
        leakage_field=args.leakage_field,
        max_samples=args.max_samples,
        dedup_max_loss=args.dedup_max_loss,
        s3_prefix=args.s3_prefix,
        check=args.check,
        quiet=args.quiet,
        expected_bucket_owner=args.expected_bucket_owner,
    )
    return 1 if report.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
