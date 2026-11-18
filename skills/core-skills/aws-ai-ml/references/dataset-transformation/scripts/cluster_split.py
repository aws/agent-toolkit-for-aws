#!/usr/bin/env python3
"""Cluster-aware stratified split into dev / val / test.

Why not a random split: a random split leaks semantically-similar rows across
partitions, so the held-out number is inflated. This embeds inputs, clusters
them, and stratifies by (cluster_id, gt_label) so every partition sees the full
distribution of both semantic neighborhoods and labels. Seeded → reproducible.

- dev:  refiner signal (the labeler is tuned against this).
- val:  per-iteration gate (steering signal; rotated during refinement).
- test: RESERVED. Never shown to labeler or refiner. The only partition the
        reported macro-F1 is measured on.

Falls back to label-only stratification when clustering is impossible (n<6, or
sentence-transformers / scikit-learn not installed). The fallback is reported in
the manifest so the run stays honest about which strategy was used.

`--strategy random` asks for that random split outright: it reads neither gold nor
text. A certificate on the test rows (the labeling job's) assumes those rows are a random
sample of the corpus; the stratified strategies read gold and break that on a
random-sample seed, so the cold start (auto-labeling references/cold-start.md, Step D)
splits its seed with `--strategy random`.

Free-text gold (QA `gt_answers`, untyped NER spans) has a near-unique value per
row, so stratifying on it makes one bucket per row and drains val/test to ~1 row
each. When the gt field is detected as free-text (mostly-singleton buckets), the
split switches to a RANDOM split that honors the requested dev/val/test fractions
and records `strategy: "random"` in the manifest.

Numeric gold with many distinct values (a continuous judge score, e.g. the mean of
several expert ratings) is stratified by quantile bin (NUMERIC_GOLD_BINS), not by
raw value, so tiny per-value buckets do not skew the split toward dev. Integer gold is
ambiguous (class ids 0..19, or a 0-100 rating), so `--gold-kind class|score` says which
it is; with the default `auto`, integer gold is binned only in a score field (a name with
`score` or `rating`, e.g. `gt_score`) and otherwise stays exact class strata.

Dependencies (optional, for cluster strategy), pinned in references/dependencies.md:
    pip install scikit-learn==1.7.2 sentence-transformers==6.3.0

CLI: python cluster_split.py --labeled JSONL --gt-field F --out-dir DIR
     [--strategy cluster|label --gold-kind auto|class|score
      --dev-frac 0.5 --val-frac 0.25 --text-fields a,b,c --seed 42]
Writes dev.jsonl, val.jsonl, test.jsonl, manifest.json under --out-dir.
Full reference: references/op_split.md -> "Shared Cluster Splitter".
"""

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

# ---- user-configurable defaults (scan here before reading the logic) --------
DEFAULT_DEV_FRAC = 0.5
DEFAULT_VAL_FRAC = 0.25  # test gets the remaining 1 - dev - val
DEFAULT_SEED = 42
DEFAULT_TEXT_FIELDS = ["text", "premise", "hypothesis", "dialogue", "content"]
# @secure_recommendation: In a restricted runtime, use an approved internal
# model artifact source; direct external download requires the user's explicit
# approval and any required AppSec sign-off.
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# A row missing the gt field cannot be stratified: it falls into the catch-all
# `None` bucket and is split at random. A few such rows only blunt the
# stratification; once they are the MAJORITY the split is a random split wearing a
# stratified label, which is the failure this module exists to prevent.
MAX_MISSING_GT_FRAC = 0.5
# Free-text gold (QA answers, untyped NER spans) has a near-unique value per row.
# Stratifying on it makes one bucket per row and _three_way drains val/test to ~1
# row each. When at least this fraction of keyed rows carry a
# DISTINCT stratification key, the field is treated as free-text and the split
# switches to a random split that honors the requested fractions. Categorical
# gold repeats labels, so its unique fraction stays well below this bar.
FREE_TEXT_UNIQUE_FRAC = 0.9
# Require this many keyed rows before declaring free-text: on a handful of rows a
# distinct-per-row key is indistinguishable from a small categorical vocabulary.
MIN_KEYED_FOR_FREE_TEXT = 6
# Warn (stderr) when a realised partition fraction diverges from the requested one
# by more than this (5 percentage points).
FRAC_DIVERGENCE_TOL = 0.05
# Numeric gold (an llm_judge / ordinal score) with more distinct values than this is
# stratified by quantile bin instead of by raw value. Raw continuous gold (e.g. a mean
# of several expert ratings) makes one tiny bucket per value; crossed with ~20
# clusters most (cluster, value) buckets hold 1-2 rows, and the small-bucket rules in
# _three_way (1 row -> dev, 2 rows -> dev + val) skew the split toward dev, leaving
# a small test split.
NUMERIC_GOLD_BINS = 5
# --gold-kind: `class` keeps every gold value as its own stratum, `score` bins numeric
# gold, `auto` bins fractional gold and integer gold in a field whose name has one of
# SCORE_FIELD_HINTS (llm_judge / ordinal use `gt_score`). Integer gold in any other
# field (`category`, `intent`, `class_id`) is kept as exact classes: binning class ids
# would merge distinct classes into one stratum.
GOLD_KINDS = ("auto", "class", "score")
SCORE_FIELD_HINTS = ("score", "rating")
# -----------------------------------------------------------------------------


def _input_text(rec, text_fields):
    parts = [str(rec[f]) for f in text_fields if rec.get(f) is not None]
    return " ".join(parts) if parts else json.dumps(rec, default=str)


def _cluster_ids(texts, n_clusters, seed):
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import KMeans

    emb = SentenceTransformer(EMBED_MODEL).encode(
        texts, show_progress_bar=False, normalize_embeddings=True
    )
    return KMeans(n_clusters=n_clusters, random_state=seed, n_init=10).fit_predict(emb)


def _three_way(buckets, dev_frac, val_frac, seed):
    """Round-robin draw from each bucket into dev/val/test so all see every bucket."""
    rng = random.Random(seed)
    dev, val, test = [], [], []
    for _key, idxs in buckets.items():
        ids = list(idxs)
        rng.shuffle(ids)
        n = len(ids)
        # Guarantee a test row from any bucket of >=3, and a val row from any
        # bucket of >=2: the held-out gate is meaningless with an empty test
        # partition, which integer rounding would otherwise produce on small
        # per-class buckets (the P1 <100-GT case).
        if n >= 3:
            d_cut = max(1, min(int(round(n * dev_frac)), n - 2))
            v_cut = max(d_cut + 1, min(d_cut + int(round(n * val_frac)), n - 1))
        elif n == 2:
            d_cut, v_cut = 1, 2  # dev + val, no test from a 2-row bucket
        else:
            d_cut, v_cut = 1, 1  # single row -> dev only
        dev.extend(ids[:d_cut])
        val.extend(ids[d_cut:v_cut])
        test.extend(ids[v_cut:])
    return sorted(dev), sorted(val), sorted(test)


def _random_split(n, dev_frac, val_frac, seed):
    """Shuffle-and-slice split that HONORS the requested fractions. Used when the
    gt field is free-text and stratification is not meaningful."""
    rng = random.Random(seed)
    ids = list(range(n))
    rng.shuffle(ids)
    d_cut = int(round(n * dev_frac))
    v_cut = min(n, d_cut + int(round(n * val_frac)))
    return sorted(ids[:d_cut]), sorted(ids[d_cut:v_cut]), sorted(ids[v_cut:])


def _free_text_unique_frac(records, strat_key):
    """Fraction of KEYED rows (non-None stratification key) that carry a distinct
    key, plus the keyed count. A value near 1.0 means one bucket per row: the gt
    field is free-text, not categorical. Rows with no key (None) are excluded so a
    block of unlabeled/empty-span rows does not mask the near-unique remainder."""
    keys = [k for k in (strat_key(r) for r in records) if k is not None]
    if not keys:
        return 0.0, 0
    return len(set(keys)) / len(keys), len(keys)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _numeric_gold_kind(records, gt_field, gold_kind="auto", n_bins=NUMERIC_GOLD_BINS):
    """How numeric gold is stratified: ("score", why) to bin it, ("class", why) to keep
    exact values, or (None, None) when binning does not apply (the gold is not
    all-numeric, or has at most `n_bins` distinct values, so its raw tiers are kept).
    `why` is "flag" for an explicit --gold-kind, else the auto rule that decided;
    "integer_unhinted" marks the auto guess for integer gold in a field with no score
    hint, which split() warns about."""
    if gold_kind not in GOLD_KINDS:
        raise ValueError(f"gold_kind must be one of {GOLD_KINDS}, got {gold_kind!r}")
    vals = [r.get(gt_field) for r in records if r.get(gt_field) is not None]
    if not vals or not all(_is_number(v) for v in vals) or len(set(vals)) <= n_bins:
        return None, None
    if gold_kind != "auto":
        return gold_kind, "flag"
    if any(float(v) != int(float(v)) for v in vals):
        return "score", "fractional"
    name = str(gt_field).lower()
    if "label" not in name and any(h in name for h in SCORE_FIELD_HINTS):
        return "score", "score_field"
    return "class", ("label_field" if "label" in name else "integer_unhinted")


def _numeric_bin_fn(records, gt_field, n_bins=NUMERIC_GOLD_BINS, gold_kind="auto"):
    """Key function that maps numeric gold to one of `n_bins` quantile bins, or None
    when the gold is not binned (see _numeric_gold_kind: not all-numeric, at most
    `n_bins` distinct values, or class ids). Rows with no gold keep the None key."""
    kind, _why = _numeric_gold_kind(records, gt_field, gold_kind, n_bins)
    if kind != "score":
        return None
    vals = [r.get(gt_field) for r in records if r.get(gt_field) is not None]
    ordered = sorted(vals)
    # Upper edge of each of the first n_bins - 1 bins, at the value quantiles.
    edges = [ordered[(k * len(ordered)) // n_bins] for k in range(1, n_bins)]

    def key(r):
        v = r.get(gt_field)
        if not _is_number(v):
            return None
        return ("bin", sum(1 for e in edges if v >= e))

    return key


def _strat_key_fn(records, gt_field, gold_kind="auto"):
    """Return a function record -> hashable stratification key. Classification: the gt
    label is already a scalar, use it directly. Numeric gold with many distinct values
    (a continuous judge score): its quantile bin (see _numeric_bin_fn). NER (and any list-valued gt field): the
    value is a list of {type,text} spans, which is unhashable; stratify by the RAREST
    entity TYPE present in the row (global type frequency across the seed) so every
    partition sees the scarce types. Rows with no entities bucket under None."""
    sample = next((r.get(gt_field) for r in records if r.get(gt_field) is not None), None)
    numeric = _numeric_bin_fn(records, gt_field, gold_kind=gold_kind)
    if numeric is not None:
        return numeric
    if not isinstance(sample, list):
        return lambda r: r.get(gt_field)
    freq: dict = defaultdict(int)
    for r in records:
        for e in r.get(gt_field) or []:
            t = e.get("type") if isinstance(e, dict) else e
            if t is not None:
                freq[t] += 1

    def key(r):
        types = [e.get("type") if isinstance(e, dict) else e for e in (r.get(gt_field) or [])]
        types = [t for t in types if t is not None]
        if not types:
            return None
        return min(types, key=lambda t: (freq.get(t, 0), t))

    return key


def split(records, gt_field, dev_frac, val_frac, text_fields, strategy, seed, gold_kind="auto"):
    n = len(records)
    if strategy == "random":
        # Requested: a split that never reads gold or text, so every partition is a
        # uniform random subset of the seed. On a random sample of the corpus (the
        # cold-start seed) the val and test rows that back the certificate are then a
        # random sample of the corpus too. The stratified strategies are not: they
        # read gold, and on many-class seeds they send rows from rare (cluster,
        # label) buckets to dev, so val + test were more accurate than the corpus
        # (banking77 unanimous rows 0.939 vs 0.922) and the certificate fired too often.
        # Return before any gold inspection, so no gold WARNING or numeric_gold field
        # is recorded for a split that ignores gold.
        info = {
            "strategy": "random",
            "strategy_reason": "requested (--strategy random): gold-independent split",
            "degraded_to_random": False,
        }
        dev, val, test = _random_split(n, dev_frac, val_frac, seed)
        return dev, val, test, _with_sizes(info, n, dev, val, test, dev_frac, val_frac)
    info = {"strategy": strategy}
    kind, why = _numeric_gold_kind(records, gt_field, gold_kind)
    if kind is not None:
        info.update(numeric_gold=kind, numeric_gold_reason=why)
    if why == "integer_unhinted":
        print(
            f"WARNING: gt field {gt_field!r} holds integer gold with more than "
            f"{NUMERIC_GOLD_BINS} distinct values; stratifying each value as its own "
            f"class. If it is a score (a rating scale), pass --gold-kind score to "
            f"stratify by quantile bin; pass --gold-kind class to silence this.",
            file=sys.stderr,
        )
    strat_key = _strat_key_fn(records, gt_field, gold_kind)
    gt_present = sum(1 for r in records if gt_field in r)
    # Free-text gold (QA answers, untyped NER spans) keys near-uniquely, so every
    # stratum bucket is a singleton on EITHER path - the cluster path's
    # (cluster, key) bucket is just as singleton-dominated as a label bucket - and
    # _three_way would dump almost everything into dev. Detect it BEFORE choosing a
    # strategy so a free-text corpus takes the random split regardless of --strategy
    # (the default is cluster); otherwise the B4 drain still happens on the default
    # path.
    uniq_frac, n_keyed = _free_text_unique_frac(records, strat_key)
    # Require most of the dataset to actually be keyed, not just the keyed subset to
    # be near-unique: otherwise a mis-specified --gt-field (only a minority of rows
    # carry a coincidentally-unique value) would read as free-text and silently take
    # a random split, bypassing the label branch's loud missing-gt guard. Gating on
    # n_keyed/n keeps a mostly-unlabeled / wrong-field corpus falling through to that
    # ValueError instead.
    free_text = (
        n_keyed >= MIN_KEYED_FOR_FREE_TEXT
        and uniq_frac >= FREE_TEXT_UNIQUE_FRAC
        and n > 0
        and n_keyed >= (1 - MAX_MISSING_GT_FRAC) * n
    )
    buckets: dict = {}
    if free_text:
        info.update(
            strategy="random",
            free_text_gt=True,
            free_text_unique_frac=round(uniq_frac, 4),
            strategy_reason="gold is free-text / mostly-unique, " "stratification not meaningful",
        )
    use_cluster = (not free_text) and strategy == "cluster" and n >= 6
    if use_cluster:
        try:
            labels = {strat_key(r) for r in records}
            n_clusters = max(2, min(20, n // 5, max(int(n**0.5), len(labels) * 2)))
            n_clusters = min(n_clusters, n - 1)
            cids = _cluster_ids([_input_text(r, text_fields) for r in records], n_clusters, seed)
            buckets = defaultdict(list)
            for i, r in enumerate(records):
                buckets[(int(cids[i]), strat_key(r))].append(i)
            info.update(strategy="cluster", n_clusters=n_clusters, n_buckets=len(buckets))
            # Clustering still stratifies by semantic cluster, but note when the
            # label half of the (cluster, label) key was absent from the data.
            if gt_present == 0:
                info["gt_field_missing"] = True
        except Exception as e:  # noqa: BLE001 - any import/runtime failure → fallback
            use_cluster = False
            info["fallback_reason"] = f"{type(e).__name__}: {e}"
            # Warn on stderr, not just in the manifest: the label-stratified fallback
            # leaks semantically-similar rows across partitions, so the held-out
            # number becomes optimistic. The operator must see this.
            print(
                f"WARNING: cluster split unavailable ({type(e).__name__}: {e}); "
                "falling back to a label-stratified split. This inflates the "
                "held-out macro-F1 (semantically-similar rows leak across "
                "partitions). Install sentence-transformers + scikit-learn for the "
                "cluster split.",
                file=sys.stderr,
            )
    if not free_text and not use_cluster:
        # Label stratification requires the gt field. If it is absent from every
        # record, every row collapses into a single bucket and the split is a
        # RANDOM split, not a stratified one — fail loudly rather than silently.
        if gt_present == 0 and n > 0:
            sampled = sorted({k for r in records[:50] for k in r})
            raise ValueError(
                f"gt field {gt_field!r} is not present in any of {n} records; a "
                f"label-stratified split would silently reduce to a random split. "
                f"Pass --gt-field matching your data (sampled fields: {sampled}), or "
                f"use --strategy cluster with sentence-transformers + scikit-learn "
                f"installed for semantic stratification."
            )
        # PARTIAL presence used to pass silently: the missing rows all bucket under
        # `None`, so n_buckets >= 2 and `degraded_to_random` stayed False even with
        # 97 of 100 rows unstratified.
        missing = n - gt_present
        if n > 0 and missing > MAX_MISSING_GT_FRAC * n:
            sampled = sorted({k for r in records[:50] for k in r})
            raise ValueError(
                f"gt field {gt_field!r} is missing from {missing} of {n} records "
                f"({missing / n:.0%}); those rows collapse into one catch-all bucket, "
                f"so the split would be mostly random rather than label-stratified. "
                f"Label them, drop them, or pass --gt-field matching your data "
                f"(sampled fields: {sampled})."
            )
        buckets = defaultdict(list)
        for i, r in enumerate(records):
            buckets[strat_key(r)].append(i)
        info.update(strategy="label", n_buckets=len(buckets))

    # Recorded for BOTH strategies — the cluster path's (cluster, label) key loses
    # its label half exactly the same way. Deliberately NOT folded into
    # `degraded_to_random`, which means one bucket / a wholly random split: these
    # rows are "stratified" on `None`, so the real strata are weaker than
    # `n_buckets` suggests.
    info["gt_present"] = gt_present
    info["gt_missing"] = n - gt_present
    info["partially_stratified"] = bool(n) and (n - gt_present) > 0

    # A single bucket means every partition is drawn from the same pool == a
    # random split. Surface it (e.g. a genuinely single-class dataset) so callers
    # never mistake a random split for a stratified one.
    info["degraded_to_random"] = len(buckets) == 1 and n > 1

    if info.get("strategy") == "random":
        dev, val, test = _random_split(n, dev_frac, val_frac, seed)
    else:
        dev, val, test = _three_way(buckets, dev_frac, val_frac, seed)
    return dev, val, test, _with_sizes(info, n, dev, val, test, dev_frac, val_frac)


def _with_sizes(info, n, dev, val, test, dev_frac, val_frac):
    info.update(dev_size=len(dev), val_size=len(val), test_size=len(test))
    # Record realised vs requested fractions so callers can warn when the split
    # diverges from what was asked for (the B4 failure was a SILENT divergence).
    if n:
        test_frac = max(0.0, 1.0 - dev_frac - val_frac)
        info["requested_fracs"] = {"dev": dev_frac, "val": val_frac, "test": test_frac}
        info["realised_fracs"] = {"dev": len(dev) / n, "val": len(val) / n, "test": len(test) / n}
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labeled", required=True)
    ap.add_argument("--gt-field", default="gt_label")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--dev-frac", type=float, default=DEFAULT_DEV_FRAC)
    ap.add_argument("--val-frac", type=float, default=DEFAULT_VAL_FRAC)
    ap.add_argument("--text-fields", default=",".join(DEFAULT_TEXT_FIELDS))
    ap.add_argument(
        "--strategy",
        choices=["cluster", "label", "random"],
        default="cluster",
        help="cluster (default): stratify by (embedding cluster, gold); label: by "
        "gold; random: uniform, reads neither gold nor text. Use random for a "
        "seed that is a random sample of the corpus and backs a certificate "
        "(the cold start): only then are val and test a random sample of it",
    )
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument(
        "--gold-kind",
        choices=GOLD_KINDS,
        default="auto",
        help="class: every gold value is its own stratum; score: bin numeric "
        "gold by quantile; auto (default): bin fractional gold and "
        "integer gold in a score/rating field, keep other integers as "
        "classes",
    )
    args = ap.parse_args()

    records = []
    with open(args.labeled) as f:
        for i, line in enumerate(f):
            line = line.strip()
            if line:
                obj = json.loads(line)
                # Namespace synthesized ids by dataset so a seed-test row never
                # collides with a corpus row that happens to share the same index
                # (report.py joins gold by `id`; bare str(i) let seed row 5 and
                # corpus row 5 cross-join). setdefault: rows that already carry an
                # id keep it, so legitimate same-item joins still match (B2). A null id
                # is no id: setdefault would keep it, and the row would take its
                # position downstream, which collides with a corpus row's.
                if obj.get("id") is None:
                    obj["id"] = f"seed-{i}"
                records.append(obj)

    # client-side-access guidance: name the primitive and the row count read on the
    # client (the cloud desktop), so the volume that leaves the SDG container is visible.
    # Prefix `client-read:` (not `WARNING:`) so it does not trip actionable-WARNING checks.
    print(
        f"client-read: cluster_split read {len(records)} row(s) of your data on the "
        "client (cloud desktop), not in the SDG container.",
        file=sys.stderr,
    )
    text_fields = [s for s in args.text_fields.split(",") if s]
    try:
        dev, val, test, info = split(
            records,
            args.gt_field,
            args.dev_frac,
            args.val_frac,
            text_fields,
            args.strategy,
            args.seed,
            gold_kind=args.gold_kind,
        )
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    if info.get("degraded_to_random"):
        print(
            "WARNING: only one stratification bucket — this split is effectively "
            "RANDOM, not stratified.",
            file=sys.stderr,
        )
    if info.get("partially_stratified"):
        print(
            f"WARNING: gt field {args.gt_field!r} is missing from "
            f"{info['gt_missing']} of {len(records)} records — those rows were "
            f"bucketed together as {args.gt_field}=None, so the split is only "
            f"PARTIALLY stratified.",
            file=sys.stderr,
        )
    if info.get("strategy") == "random":
        print(
            f"NOTE: {info.get('strategy_reason', 'free-text gold')}; using a "
            f"RANDOM split that honors the requested fractions.",
            file=sys.stderr,
        )
    req, real = info.get("requested_fracs"), info.get("realised_fracs")
    if req and real:
        print(
            "Split fractions dev/val/test: requested "
            f"{req['dev']:.2f}/{req['val']:.2f}/{req['test']:.2f}, realised "
            f"{real['dev']:.2f}/{real['val']:.2f}/{real['test']:.2f}.",
            file=sys.stderr,
        )
        worst = max(abs(real[k] - req[k]) for k in ("dev", "val", "test"))
        # Only WARN for the random strategy, where honoring the requested fractions
        # is the contract. The stratified path intentionally deviates on small buckets
        # (the small-GT guarantee forces >=1 test row from any bucket of >=3 and >=1
        # val row from any bucket of >=2), so warning there is a false alarm that
        # trains operators to ignore the signal the B4 free-text drain needs.
        if worst > FRAC_DIVERGENCE_TOL and info.get("strategy") == "random":
            print(
                f"WARNING: realised split fractions diverge from requested by up "
                f"to {worst * 100:.0f}pp (> {FRAC_DIVERGENCE_TOL * 100:.0f}pp).",
                file=sys.stderr,
            )

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, idxs in (("dev", dev), ("val", val), ("test", test)):
        p = out / f"{name}.jsonl"
        with open(p, "w") as f:
            for i in idxs:
                f.write(json.dumps(records[i], ensure_ascii=False) + "\n")
        paths[f"{name}_path"] = str(p)

    manifest = {
        **paths,
        "gt_field": args.gt_field,
        "gold_kind": args.gold_kind,
        "seed": args.seed,
        "dev_frac": args.dev_frac,
        "val_frac": args.val_frac,
        "info": info,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
