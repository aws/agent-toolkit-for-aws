#!/usr/bin/env python3
"""Split a JSONL dataset into train/val/test sets (random or stratified), seeded.

CLI: python dataset_split.py INPUT.jsonl --output-dir DIR [options]
  --ratios R...        split ratios (default 0.8 0.2; three values -> train/val/test)
  --strategy S         random (default) | stratified
  --stratify-field F   label field; required for --strategy stratified
  --seed N             RNG seed (default 42)
  --preview            report split sizes without writing files
  --json               emit statistics as JSON to stdout
Full reference and lane routing: references/op_split.md.
"""

import argparse
import json
import os
import random as random_module
import sys
from collections import Counter

from transform_helpers import input_exists, iter_text_lines

# ---------------------------------------------------------------------------
# Core splitting logic
# ---------------------------------------------------------------------------


def _load_jsonl(input_path, expected_bucket_owner=None):
    """Load a JSONL file into a list of records.

    Accepts local paths and ``s3://`` URIs (S3 inputs are streamed via
    :func:`transform_helpers.iter_text_lines` and never written to local
    disk).

    Parameters
    ----------
    input_path : str
        Path to the input JSONL file (local or ``s3://`` URI).

    Returns
    -------
    tuple[list[dict], int]
        Parsed JSON-object records and the number of invalid-UTF-8, malformed,
        or non-object non-blank lines.
    """
    records = []
    malformed = 0

    def count_decode_error():
        nonlocal malformed
        malformed += 1

    for line in iter_text_lines(
        input_path,
        on_decode_error=count_decode_error,
        expected_bucket_owner=expected_bucket_owner,
    ):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(record, dict):
            malformed += 1
            continue
        records.append(record)
    return records, malformed


def _write_jsonl(records, output_path):
    """Write a list of records to a JSONL file.

    Parameters
    ----------
    records : list[dict]
        Records to write.
    output_path : str
        Path to the output file.
    """
    os.makedirs(
        os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True
    )
    with open(output_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _compute_class_distribution(records, stratify_field):
    """Compute class distribution for a stratify field.

    Parameters
    ----------
    records : list[dict]
        Records to analyze.
    stratify_field : str
        Field name to compute distribution for.

    Returns
    -------
    dict[str, int]
        Mapping of class value to count.
    """
    counter: Counter = Counter()
    for record in records:
        value = record.get(stratify_field, "__MISSING__")
        counter[str(value)] += 1
    return dict(counter)


def _random_split(indices, train_ratio, seed):
    """Split indices randomly into train and rest.

    Parameters
    ----------
    indices : list[int]
        Indices to split.
    train_ratio : float
        Proportion for the train set.
    seed : int
        Random seed.

    Returns
    -------
    tuple[list[int], list[int]]
        (train_indices, rest_indices)
    """
    rng = random_module.Random(seed)
    shuffled = list(indices)
    rng.shuffle(shuffled)
    split_point = round(len(shuffled) * train_ratio)
    return shuffled[:split_point], shuffled[split_point:]


def _stratified_split(indices, labels, train_ratio, seed):
    """Split indices with stratification, preserving class distribution.

    Groups indices by label, then splits each group proportionally.
    Falls back to random split if any class has fewer than 2 samples.

    Parameters
    ----------
    indices : list[int]
        Indices to split.
    labels : list[str]
        Label for each index (same length as indices).
    train_ratio : float
        Proportion for the train set.
    seed : int
        Random seed.

    Returns
    -------
    tuple[list[int], list[int], bool]
        (train_indices, rest_indices, fallback_occurred)
        fallback_occurred is True if stratification was not possible.
    """
    # Group indices by class
    class_indices: dict = {}
    for idx, label in zip(indices, labels):
        class_indices.setdefault(label, []).append(idx)

    # Check if stratification is possible (each class needs at least 2 samples)
    min_class_count = min(len(v) for v in class_indices.values())
    if min_class_count < 2:
        train, rest = _random_split(indices, train_ratio, seed)
        return train, rest, True

    # Stratified split: split each class proportionally
    rng = random_module.Random(seed)
    train_indices = []
    rest_indices = []

    for _label, class_idxs in sorted(class_indices.items()):
        shuffled = list(class_idxs)
        rng.shuffle(shuffled)
        split_point = round(len(shuffled) * train_ratio)
        # Ensure at least 1 in each partition when possible
        if split_point == 0 and len(shuffled) >= 2:
            split_point = 1
        elif split_point == len(shuffled) and len(shuffled) >= 2:
            split_point = len(shuffled) - 1
        train_indices.extend(shuffled[:split_point])
        rest_indices.extend(shuffled[split_point:])

    return train_indices, rest_indices, False


def split_dataset(
    input_path: str,
    output_dir: str | None = None,
    ratios: list[float] | None = None,
    strategy: str = "random",
    stratify_field: str | None = None,
    seed: int = 42,
    preview: bool = False,
    *,
    train_ratio: float | None = None,
    val_ratio: float | None = None,
    test_ratio: float | None = None,
    expected_bucket_owner: str | None = None,
) -> dict:
    """Split a JSONL dataset into train/validation/test sets.

    Uses Python's random module for splitting and stratification.

    Two equivalent ways to specify the split:

    * ``ratios=[0.8, 0.2]`` or ``ratios=[0.7, 0.2, 0.1]`` — list form,
      backward compatible with the CLI.
    * ``train_ratio=0.8, val_ratio=0.1, test_ratio=0.1`` — keyword form
      preferred by the notebook helpers. **All three keyword arguments
      must be supplied together when any one is provided** — partial
      keyword input (e.g. only ``train_ratio=0.7``) is rejected with
      ``ValueError``. Use ``test_ratio=0.0`` for a 2-way train/val split.

    The two forms are mutually exclusive — passing both raises
    ``ValueError``. Defaults (``ratios is None`` and all of
    ``train_ratio``/``val_ratio``/``test_ratio`` are ``None``) preserve
    the original ``[0.8, 0.2]`` 2-way behavior used by the CLI.

    Parameters
    ----------
    input_path : str
        Path to the input JSONL file.
    output_dir : str | None
        Directory to write split files. Required unless ``preview=True``.
    ratios : list[float] | None
        Split ratios (2 or 3 values that sum to 1.0). Mutually exclusive
        with ``train_ratio`` / ``val_ratio`` / ``test_ratio``.
    strategy : str
        Splitting strategy: ``"random"`` or ``"stratified"``.
    stratify_field : str | None
        Field to stratify on. Required when ``strategy="stratified"``.
    seed : int
        Random seed for reproducibility (default ``42``).
    preview : bool
        If ``True``, only report statistics without writing files.
    train_ratio, val_ratio, test_ratio : float | None
        Keyword-only equivalents of ``ratios``. All three must be
        supplied together — partial keyword input is rejected. When
        provided, ``ratios`` is derived as ``[train, val, test]`` (with
        ``[train, val]`` if ``test_ratio`` is exactly ``0``).

    Returns
    -------
    dict
        Statistics including ``total``, ``strategy``, ``seed``,
        ``ratios``, ``splits`` (per-split record counts and optional class
        distribution), plus convenience keys ``train_count``,
        ``val_count``, ``test_count``, ``malformed``, ``input_records``,
        and ``output_records``. ``total`` and ``output_records`` count valid
        JSON records; ``input_records`` also includes malformed non-blank
        lines that were attempted and dropped. When ``output_dir`` is
        provided (and therefore files are written), the dict additionally
        includes ``paths`` — a mapping of split name to its output file path.
        ``paths`` is **omitted** when the function is invoked in
        ``preview=True`` mode (no ``output_dir``); callers should use
        ``result.get("paths", {})`` if they cannot guarantee files were
        written.
    """
    if train_ratio is not None or val_ratio is not None or test_ratio is not None:
        if ratios is not None:
            raise ValueError(
                "Specify either 'ratios' or 'train_ratio'/'val_ratio'/" "'test_ratio', not both"
            )
        missing = [
            name
            for name, value in (
                ("train_ratio", train_ratio),
                ("val_ratio", val_ratio),
                ("test_ratio", test_ratio),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                "train_ratio, val_ratio, and test_ratio must all be "
                f"supplied together; missing: {missing}. "
                "Use test_ratio=0.0 for a train/val-only split."
            )
        ratios = (
            [train_ratio, val_ratio] if test_ratio == 0 else [train_ratio, val_ratio, test_ratio]  # type: ignore[list-item]
        )

    if ratios is None:
        ratios = [0.8, 0.2]

    # Validate ratios
    if len(ratios) not in (2, 3):
        raise ValueError("Ratios must have 2 values (train/val) or 3 values (train/val/test)")

    ratio_sum = sum(ratios)
    if abs(ratio_sum - 1.0) > 1e-6:
        raise ValueError(f"Ratios must sum to 1.0, got {ratio_sum:.6f}")

    if any(r <= 0 for r in ratios):
        raise ValueError("All ratios must be positive")

    # Validate strategy
    if strategy == "stratified" and not stratify_field:
        raise ValueError("--stratify-field is required when strategy is 'stratified'")

    # Validate output_dir
    if not preview and not output_dir:
        raise ValueError("output_dir is required when preview is False")

    # Load records
    records, malformed = _load_jsonl(input_path, expected_bucket_owner)
    total = len(records)
    if malformed:
        print(
            f"Warning: skipped {malformed} malformed or non-object JSONL "
            f"line{'s' if malformed != 1 else ''}.",
            file=sys.stderr,
        )

    if total == 0:
        # Handle empty file
        splits = {"train": {"records": 0}, "val": {"records": 0}}
        if len(ratios) == 3:
            splits["test"] = {"records": 0}
        result = {
            "total": 0,
            "strategy": strategy,
            "seed": seed,
            "ratios": ratios,
            "splits": splits,
            "train_count": 0,
            "val_count": 0,
            "test_count": 0,
            "malformed": malformed,
            "input_records": malformed,
            "output_records": 0,
        }
        if not preview and output_dir:
            os.makedirs(output_dir, exist_ok=True)
            _write_jsonl([], os.path.join(output_dir, "split_train.jsonl"))
            _write_jsonl([], os.path.join(output_dir, "split_val.jsonl"))
            paths = {
                "train": os.path.join(output_dir, "split_train.jsonl"),
                "val": os.path.join(output_dir, "split_val.jsonl"),
            }
            if len(ratios) == 3:
                _write_jsonl([], os.path.join(output_dir, "split_test.jsonl"))
                paths["test"] = os.path.join(output_dir, "split_test.jsonl")
            result["paths"] = paths
        return result

    # Fail loudly if the stratify field is absent from the data. Otherwise every
    # row collapses into a single "__MISSING__" class, the per-class ">=2 sample"
    # fallback never trips, and the "stratified" split silently degenerates into
    # a random split reported as stratified.
    if strategy == "stratified" and stratify_field:
        present = sum(1 for r in records if stratify_field in r)
        if present == 0:
            sampled = sorted({k for r in records[:50] for k in r})
            raise ValueError(
                f"stratify field {stratify_field!r} is not present in any of "
                f"{total} records; a stratified split would silently reduce to a "
                f"random split. Pass --stratify-field matching your data "
                f"(sampled fields: {sampled})."
            )
    # Determine stratify labels if needed
    stratify_labels = None
    if strategy == "stratified" and stratify_field:
        stratify_labels = [str(records[i].get(stratify_field, "__MISSING__")) for i in range(total)]

    # Preview mode: report stats without splitting
    if preview:
        result = {
            "total": total,
            "strategy": strategy,
            "seed": seed,
            "ratios": ratios,
            "splits": {},
            "malformed": malformed,
            "input_records": total + malformed,
            "output_records": total,
        }
        if strategy == "stratified" and stratify_field:
            result["class_distribution"] = _compute_class_distribution(records, stratify_field)
        return result

    # Perform the split
    three_way = len(ratios) == 3

    if three_way:
        train_ratio, val_ratio, test_ratio = ratios
    else:
        train_ratio, val_ratio = ratios
        test_ratio = 0.0

    # Track whether stratification fell back to random
    stratification_fallback = False

    # Handle edge case: dataset too small for the requested splits
    min_records_needed = len(ratios)
    if total < min_records_needed:
        # For very small datasets, put all records in train
        train_indices = list(range(total))
        val_indices = []
        test_indices = []
    else:
        if strategy == "stratified" and stratify_labels:
            train_indices, rest_indices, fallback = _stratified_split(
                list(range(total)), stratify_labels, train_ratio, seed
            )
            if fallback:
                stratification_fallback = True
        else:
            train_indices, rest_indices = _random_split(list(range(total)), train_ratio, seed)

        if three_way and len(rest_indices) >= 2:
            # Second split: separate val from test within the rest
            val_proportion = val_ratio / (val_ratio + test_ratio)

            if strategy == "stratified" and stratify_labels and not stratification_fallback:
                rest_labels = [stratify_labels[i] for i in rest_indices]
                val_indices, test_indices, rest_fallback = _stratified_split(
                    rest_indices, rest_labels, val_proportion, seed
                )
                if rest_fallback:
                    stratification_fallback = True
            else:
                val_indices, test_indices = _random_split(rest_indices, val_proportion, seed)
        elif three_way:
            # rest is too small to split further
            val_indices = rest_indices
            test_indices = []
        else:
            val_indices = rest_indices
            test_indices = []

    # Gather records for each split
    train_records = [records[i] for i in sorted(train_indices)]
    val_records = [records[i] for i in sorted(val_indices)]
    test_records = [records[i] for i in sorted(test_indices)] if three_way else []

    # Write output files
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        _write_jsonl(train_records, os.path.join(output_dir, "split_train.jsonl"))
        _write_jsonl(val_records, os.path.join(output_dir, "split_val.jsonl"))
        if three_way:
            _write_jsonl(test_records, os.path.join(output_dir, "split_test.jsonl"))

    # Build result
    splits = {
        "train": {"records": len(train_records)},
        "val": {"records": len(val_records)},
    }
    if three_way:
        splits["test"] = {"records": len(test_records)}

    # Add class distribution per split if stratified
    if strategy == "stratified" and stratify_field:
        splits["train"]["class_distribution"] = _compute_class_distribution(
            train_records, stratify_field
        )
        splits["val"]["class_distribution"] = _compute_class_distribution(
            val_records, stratify_field
        )
        if three_way:
            splits["test"]["class_distribution"] = _compute_class_distribution(
                test_records, stratify_field
            )

    result = {
        "total": total,
        "strategy": strategy,
        "seed": seed,
        "ratios": ratios,
        "splits": splits,
        "train_count": len(train_records),
        "val_count": len(val_records),
        "test_count": len(test_records) if three_way else 0,
        "malformed": malformed,
        # Every valid JSON-object record lands in exactly one output split.
        # Malformed and non-object lines are counted as attempted input and
        # dropped.
        "input_records": total + malformed,
        "output_records": total,
    }

    # Record per-split output paths when files were written. A list of
    # paths (and a `paths` dict keyed by split name) makes it easy for
    # notebook helpers to copy each split to its final destination.
    if output_dir:
        paths = {
            "train": os.path.join(output_dir, "split_train.jsonl"),
            "val": os.path.join(output_dir, "split_val.jsonl"),
        }
        if three_way:
            paths["test"] = os.path.join(output_dir, "split_test.jsonl")
        result["paths"] = paths

    if strategy == "stratified" and stratify_field:
        result["class_distribution"] = _compute_class_distribution(records, stratify_field)

    # Report fallback if stratification was requested but couldn't be applied
    if strategy == "stratified" and stratification_fallback:
        result["stratification_fallback"] = True

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Split JSONL dataset into train/validation/test sets"
    )
    parser.add_argument("input", help="Input JSONL file")
    parser.add_argument(
        "--output-dir",
        help="Directory to write split files (split_train.jsonl, split_val.jsonl, split_test.jsonl)",
    )
    parser.add_argument(
        "--ratios",
        type=float,
        nargs="+",
        default=None,
        help="Split ratios (default: 0.8 0.2). Use 2 values for train/val only.",
    )
    parser.add_argument(
        "--strategy",
        choices=["random", "stratified"],
        default="random",
        help="Splitting strategy (default: random)",
    )
    parser.add_argument(
        "--stratify-field",
        help="Field to stratify on (required when strategy is 'stratified')",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: show statistics without writing files",
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument(
        "--expected-bucket-owner",
        default=None,
        help="For an s3:// input, the 12-digit account that must own the bucket "
        "(default: the caller's own account). Set only for a bucket the user "
        "confirmed is in another account.",
    )
    args = parser.parse_args()

    # Validate arguments
    if not input_exists(args.input, args.expected_bucket_owner):
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    if not args.preview and not args.output_dir:
        print("Error: --output-dir is required unless --preview is specified", file=sys.stderr)
        sys.exit(1)

    try:
        result = split_dataset(
            input_path=args.input,
            output_dir=args.output_dir,
            ratios=args.ratios,
            strategy=args.strategy,
            stratify_field=args.stratify_field,
            seed=args.seed,
            preview=args.preview,
            expected_bucket_owner=args.expected_bucket_owner,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Total records:  {result['total']}")
        print(f"Strategy:       {result['strategy']}")
        print(f"Seed:           {result['seed']}")
        print(f"Ratios:         {result['ratios']}")
        if result.get("stratification_fallback"):
            print("  (stratification fell back to random — a class had < 2 samples)")
        print()
        for split_name, split_info in result.get("splits", {}).items():
            print(f"  {split_name}: {split_info['records']} records")
            if "class_distribution" in split_info:
                for cls, count in sorted(split_info["class_distribution"].items()):
                    print(f"    {cls}: {count}")
        if "class_distribution" in result:
            print()
            print("Overall class distribution:")
            for cls, count in sorted(result["class_distribution"].items()):
                print(f"  {cls}: {count}")

    sys.exit(0)


if __name__ == "__main__":
    main()
