#!/usr/bin/env python3
"""Detect and remove duplicate records from a JSONL dataset.

Two-phase deduplication:
  Phase 1: Exact dedup via MD5 hash of the full record.
  Phase 2: Fuzzy dedup via MinHash LSH on specified field(s) character n-gram shingles.

The later record is removed when a candidate pair's estimated Jaccard similarity
meets or exceeds the configured threshold.

CLI: python dedup_filter.py INPUT.jsonl --output OUT.jsonl [options]
  --mode M             exact | fuzzy (default fuzzy = exact + MinHash LSH)
  --fields F...        field(s) to compare (default: prompt), concatenated
  --threshold T        fuzzy Jaccard threshold (default 0.7)
  --num-perm N         MinHash permutations
  --ngram-size N       character n-gram size for shingling
  --json               emit statistics as JSON to stdout
Full reference: references/op_dedup.md.
"""

import argparse
import hashlib
import json
import os
import random
import sys
from collections import defaultdict

from transform_helpers import input_exists, iter_text_lines

# ---------------------------------------------------------------------------
# MinHash implementation
# ---------------------------------------------------------------------------


class MinHasher:
    """Lightweight MinHash implementation using universal hashing."""

    def __init__(self, num_perm=256, ngram_size=5, seed=42):
        """Initialize MinHasher with hash function coefficients.

        Parameters
        ----------
        num_perm : int
            Number of permutations (signature length).
        ngram_size : int
            Character n-gram size for shingling.
        seed : int
            Random seed for reproducibility.
        """
        self.num_perm = num_perm
        self.ngram_size = ngram_size
        # Pre-generate hash coefficients: h(x) = (a*x + b) % p
        rng = random.Random(seed)
        self._max_hash = (1 << 32) - 1
        self._prime = 4294967311  # next prime > 2^32
        self._a = [rng.randint(1, self._prime - 1) for _ in range(num_perm)]
        self._b = [rng.randint(0, self._prime - 1) for _ in range(num_perm)]

    def _shingle(self, text):
        """Generate character n-grams from text.

        Parameters
        ----------
        text : str
            Input text to shingle.

        Returns
        -------
        set[str]
            Set of character n-gram shingles.
        """
        text = text.strip().lower()
        if len(text) < self.ngram_size:
            return {text} if text else set()
        return {text[i : i + self.ngram_size] for i in range(len(text) - self.ngram_size + 1)}

    def signature(self, text):
        """Compute MinHash signature for the given text.

        Parameters
        ----------
        text : str
            Input text to compute signature for.

        Returns
        -------
        list[int]
            MinHash signature of length num_perm.
        """
        shingles = self._shingle(text)
        if not shingles:
            return [self._max_hash] * self.num_perm

        # Hash each shingle to a 32-bit int
        shingle_hashes = []
        for s in shingles:
            h = int(hashlib.md5(s.encode(), usedforsecurity=False).hexdigest()[:8], 16)
            shingle_hashes.append(h)

        sig = []
        for i in range(self.num_perm):
            min_val = self._max_hash
            a, b = self._a[i], self._b[i]
            for h in shingle_hashes:
                val = (a * h + b) % self._prime
                if val < min_val:
                    min_val = val
            sig.append(min_val)
        return sig


# ---------------------------------------------------------------------------
# LSH index
# ---------------------------------------------------------------------------


class MinHashLSH:
    """Locality-Sensitive Hashing index for MinHash signatures."""

    def __init__(self, threshold=0.7, num_perm=128):
        """Initialize LSH index with auto-tuned band/row parameters.

        Parameters
        ----------
        threshold : float
            Target Jaccard similarity threshold.
        num_perm : int
            Number of MinHash permutations (must match MinHasher).
        """
        self.num_perm = num_perm
        self.bands, self.rows = self._optimal_params(threshold, num_perm)
        self._buckets: list = [defaultdict(list) for _ in range(self.bands)]

    @staticmethod
    def _optimal_params(threshold, num_perm):
        """Find (bands, rows) where bands*rows=num_perm approximating the target threshold.

        The approximate threshold for a given (b, r) is (1/b)^(1/r).

        Parameters
        ----------
        threshold : float
            Target similarity threshold.
        num_perm : int
            Number of permutations.

        Returns
        -------
        tuple[int, int]
            Optimal (bands, rows) pair.
        """
        best = (1, num_perm)
        best_err = float("inf")
        for b in range(1, num_perm + 1):
            r = num_perm // b
            if b * r != num_perm or r == 0:
                continue
            # Approximate threshold for this (b, r)
            t = (1.0 / b) ** (1.0 / r)
            err = abs(t - threshold)
            if err < best_err:
                best_err = err
                best = (b, r)
        return best

    def insert(self, idx, signature):
        """Insert a signature into the LSH index.

        Parameters
        ----------
        idx : int
            Record index.
        signature : list[int]
            MinHash signature.
        """
        for band_i in range(self.bands):
            start = band_i * self.rows
            band = tuple(signature[start : start + self.rows])
            band_hash = hash(band)
            self._buckets[band_i][band_hash].append(idx)

    def query(self, signature):
        """Return set of candidate indices that may be similar.

        Parameters
        ----------
        signature : list[int]
            MinHash signature to query.

        Returns
        -------
        set[int]
            Set of candidate record indices.
        """
        candidates = set()
        for band_i in range(self.bands):
            start = band_i * self.rows
            band = tuple(signature[start : start + self.rows])
            band_hash = hash(band)
            for idx in self._buckets[band_i].get(band_hash, []):
                candidates.add(idx)
        return candidates


# ---------------------------------------------------------------------------
# Deduplication logic
# ---------------------------------------------------------------------------


def _jaccard_from_sigs(sig_a, sig_b):
    """Estimate Jaccard similarity from two MinHash signatures.

    Parameters
    ----------
    sig_a : list[int]
        First MinHash signature.
    sig_b : list[int]
        Second MinHash signature.

    Returns
    -------
    float
        Estimated Jaccard similarity in [0, 1].
    """
    return sum(a == b for a, b in zip(sig_a, sig_b)) / len(sig_a)


def dedup_dataset(
    input_path: str,
    output_path: str | None = None,
    *,
    mode: str = "fuzzy",
    threshold: float = 0.7,
    fields: list[str] | None = None,
    num_perm: int = 256,
    ngram_size: int = 5,
    expected_bucket_owner: str | None = None,
) -> dict:
    """Deduplicate a JSONL dataset using exact MD5 hashing and optionally MinHash LSH.

    Modes:
      - ``"exact"``: Only Phase 1 (byte-identical record removal via MD5).
      - ``"fuzzy"``: Phase 1 + Phase 2 (exact + MinHash LSH fuzzy matching).

    In both phases, the later record is removed when a duplicate is detected.

    Parameters
    ----------
    input_path : str
        Path to the input JSONL file.
    output_path : str | None
        Path to write deduplicated output. If ``None``, output is not written.
        Optional so the function can be called for stats-only / validation
        scenarios; the CLI always provides an output path.
    mode : str
        Deduplication mode: ``"exact"`` or ``"fuzzy"`` (default ``"fuzzy"``).
        ``"exact"`` performs only MD5-based exact dedup. ``"fuzzy"`` performs
        exact dedup followed by MinHash LSH fuzzy dedup. The default matches
        the CLI default and the documentation in ``op_dedup.md``.
    threshold : float
        Jaccard similarity threshold for fuzzy dedup (default ``0.7``).
    fields : list[str] | None
        Fields to use for fuzzy matching. When ``None`` or empty, defaults to
        ``["prompt"]``. Multiple fields are concatenated with a space.
    num_perm : int
        Number of MinHash permutations (default ``256``).
    ngram_size : int
        Character n-gram size for shingling (default ``5``).

    Returns
    -------
    dict
        Stats: ``input_records`` (all non-blank lines attempted), ``total``
        (UTF-8 lines processed by deduplication), ``output_records``,
        ``exact_duplicates``, ``fuzzy_duplicates``, ``kept``, ``removed``,
        and ``malformed`` (invalid UTF-8 records skipped before
        deduplication). Fuzzy mode additionally includes ``bands`` and
        ``rows``.
    """
    if not fields:
        fields = ["prompt"]

    if not (0.0 <= threshold <= 1.0):
        raise ValueError(f"threshold must be between 0.0 and 1.0, got {threshold}")
    if num_perm < 1:
        raise ValueError(f"num_perm must be >= 1, got {num_perm}")
    if ngram_size < 1:
        raise ValueError(f"ngram_size must be >= 1, got {ngram_size}")
    # Load records — supports local paths and s3:// URIs.
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
            if isinstance(record, dict):
                # Generic str() coercion handles nested objects (lists/dicts) safely.
                # TODO: Improve with schema-aware text extraction or recursive
                # flattening for better semantic matching on nested formats (e.g., Nova).
                text_for_fuzzy = " ".join(str(record.get(f, "") or "") for f in fields)
            else:
                text_for_fuzzy = ""
            records.append((text_for_fuzzy, line))
        except json.JSONDecodeError:
            # Keep malformed lines as-is (they pass through dedup unchanged)
            records.append(("", line))

    if malformed:
        print(
            f"Warning: skipped {malformed} invalid UTF-8 JSONL "
            f"line{'s' if malformed != 1 else ''}.",
            file=sys.stderr,
        )

    if not records:
        # Empty file: write empty output and return
        if output_path:
            out_dir = os.path.dirname(output_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("")
        stats = {
            "input_records": malformed,
            "total": 0,
            "output_records": 0,
            "exact_duplicates": 0,
            "fuzzy_duplicates": 0,
            "kept": 0,
            "removed": malformed,
            "malformed": malformed,
            "mode": mode,
            "threshold": threshold,
            "num_perm": num_perm,
            "ngram_size": ngram_size,
        }
        if mode == "fuzzy":
            stats["bands"] = 0
            stats["rows"] = 0
        return stats

    # Phase 1: Exact dedup via MD5 hash of full record
    seen_exact = set()
    exact_dupes = 0
    exact_kept_indices = []

    for i, (_prompt, line) in enumerate(records):
        rec_hash = hashlib.md5(line.encode(), usedforsecurity=False).hexdigest()
        if rec_hash in seen_exact:
            exact_dupes += 1
        else:
            seen_exact.add(rec_hash)
            exact_kept_indices.append(i)

    # Phase 2: Fuzzy dedup via MinHash LSH on specified fields
    fuzzy_dupes = 0
    lsh_bands = 0
    lsh_rows = 0

    if mode == "fuzzy":
        hasher = MinHasher(num_perm=num_perm, ngram_size=ngram_size)

        # Compute signatures for records that survived exact dedup and have matchable text.
        # Records with empty fuzzy text (malformed JSON, missing fields) are skipped —
        # they already passed exact dedup so they are not byte-identical.
        signatures = {}
        for i in exact_kept_indices:
            text_for_fuzzy = records[i][0]
            if not text_for_fuzzy.strip():
                continue
            signatures[i] = hasher.signature(text_for_fuzzy)

        # Build LSH index and find fuzzy duplicates
        lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        duplicate_of = {}

        for i in exact_kept_indices:
            if i in duplicate_of or i not in signatures:
                continue
            sig = signatures[i]
            candidates = lsh.query(sig)
            for c in candidates:
                if c == i or c in duplicate_of or c not in signatures:
                    continue
                if _jaccard_from_sigs(sig, signatures[c]) >= threshold:
                    # Mark the later record (i) as a duplicate of the earlier one (c)
                    duplicate_of[i] = c
                    break  # No need to check more candidates for i
            if i not in duplicate_of:
                lsh.insert(i, sig)

        fuzzy_dupes = len(duplicate_of)
        lsh_bands = lsh.bands
        lsh_rows = lsh.rows
    else:
        duplicate_of = {}

    # Assemble output: keep records that survived both phases
    kept = []
    for i in exact_kept_indices:
        if i not in duplicate_of:
            kept.append(records[i][1])

    # Write output
    if output_path:
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            if kept:
                f.write("\n".join(kept) + "\n")
            else:
                f.write("")

    total_removed = exact_dupes + fuzzy_dupes + malformed

    stats = {
        "input_records": len(records) + malformed,
        "total": len(records),
        "output_records": len(kept),
        "exact_duplicates": exact_dupes,
        "fuzzy_duplicates": fuzzy_dupes,
        "kept": len(kept),
        "removed": total_removed,
        "malformed": malformed,
        "mode": mode,
        "threshold": threshold,
        "num_perm": num_perm,
        "ngram_size": ngram_size,
    }
    if mode == "fuzzy":
        stats["bands"] = lsh_bands
        stats["rows"] = lsh_rows

    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Deduplicate JSONL dataset using exact MD5 and MinHash LSH"
    )
    parser.add_argument("input", help="Input JSONL file")
    parser.add_argument("--output", required=True, help="Output JSONL file path")
    parser.add_argument(
        "--mode",
        choices=["exact", "fuzzy"],
        default="fuzzy",
        help="Deduplication mode: 'exact' (MD5 only) or 'fuzzy' (exact + MinHash LSH). Default: fuzzy",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.7,
        help="Jaccard similarity threshold for fuzzy dedup (default: 0.7)",
    )
    parser.add_argument(
        "--num-perm",
        type=int,
        default=256,
        help="Number of MinHash permutations (default: 256)",
    )
    parser.add_argument(
        "--ngram-size",
        type=int,
        default=5,
        help="Character n-gram size for shingling (default: 5)",
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON")
    parser.add_argument(
        "--fields",
        nargs="+",
        default=None,
        help="Fields to use for fuzzy matching (default: prompt). Multiple fields are concatenated.",
    )
    parser.add_argument(
        "--expected-bucket-owner",
        default=None,
        help="For an s3:// input, the 12-digit account that must own the bucket "
        "(default: the caller's own account). Set only for a bucket the user "
        "confirmed is in another account.",
    )
    args = parser.parse_args()

    if not input_exists(args.input, args.expected_bucket_owner):
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    result = dedup_dataset(
        args.input,
        output_path=args.output,
        mode=args.mode,
        threshold=args.threshold,
        num_perm=args.num_perm,
        ngram_size=args.ngram_size,
        fields=args.fields,
        expected_bucket_owner=args.expected_bucket_owner,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Total:              {result['total']}")
        print(f"Mode:               {result['mode']}")
        print(f"Exact duplicates:   {result['exact_duplicates']}")
        print(f"Fuzzy duplicates:   {result['fuzzy_duplicates']}")
        print(f"Kept:               {result['kept']}")
        print(f"Removed:            {result['removed']}")
        if result["mode"] == "fuzzy":
            print(f"Threshold:          {result['threshold']}")
            print(f"Bands:              {result['bands']}")
            print(f"Rows:               {result['rows']}")


if __name__ == "__main__":
    main()
