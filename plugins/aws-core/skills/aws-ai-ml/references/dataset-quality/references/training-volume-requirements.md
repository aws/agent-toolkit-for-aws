# Training Volume Requirements

Single source of truth for the minimum record count a dataset needs for SageMaker
fine-tuning. Both `dataset-quality` (checking a produced dataset) and
`synthetic-dataset-generation` (advising on size before anything is generated)
read this page. Do not restate this number in an `overview.md` — reference this
file instead.

## The recommended minimum

**200 records.** Below that, training is more likely to fail.

Do not explain how the number is derived or quote a lower hard limit. If the user
asks whether a smaller dataset could work, the honest answer is that it might, but
the risk of the job failing goes up and we recommend 200.

## State this as viability, not preference

Below the minimum, training is more likely to **fail** than to merely produce a
weaker model. Say so:

- **Correct:** "We recommend at least 200 records — below that, training is more
  likely to fail. For your setup that means N total."
- **Incorrect:** "A few hundred records is a good starting point." — the user
  reads this as a quality-vs-cost tradeoff and may reasonably pick less, without
  learning their number may not train at all.

Users often pick small first-run sizes to test quickly or cheaply. That intent is
legitimate — answer it with the smallest number that clears the minimum rather
than talking them up to a comfortable one.

## What to count

The minimum applies to the **training partition**, not the total pool.

- **If the data will be split** (train/eval, held-out categories, frozen
  generalization sets), the training partition is what must clear 200. Work
  backwards through the split ratios to get the required total, and quote it with
  margin — a pool that clears 200 can still leave a training partition that
  doesn't.
- **If generation is additive** (topping up an existing pool, as in the
  iterative-SDG loop), compare against the resulting total, not this job's output.
  A 70-record top-up onto 300 existing records is fine. Do not warn on the
  increment.

## How to count

For a local JSONL file:

```bash
wc -l < local_path/to/dataset.jsonl
```

For an S3 URI, never write a local copy, and check the size first, under the same
50 MB guard the capability uses for every client read:

```bash
aws s3api head-object --bucket <bucket> --key <key> --query ContentLength
```

Under 50 MB, stream the object and count its lines:

```bash
aws s3 cp s3://bucket/key.jsonl - | wc -l
```

At 50 MB or over, do not stream the whole object. Count the lines in its first 1 MB
(`head` ends the copy after 1,048,576 bytes) and scale by the size: about
`lines × ContentLength / 1048576` records. Say that the count is an estimate from
the first 1 MB, for example "about 120,000 records (estimated from the first 1 MB)".

```bash
aws s3 cp s3://bucket/key.jsonl - | head -c 1048576 | wc -l
```

**If all you have is a registered dataset ARN** (common when the dataset quality evaluation is entered
straight from SDG output), resolve its underlying S3 source first — via the
`DataSet` object's `source` attribute or by asking the user — then count that. If
the source cannot be resolved, state the minimum anyway so the user can check it
themselves. Do not skip the advisory silently, and do not guess a count.

🚨 **Do not use `records_parsed` from `format_detector.py` as the count.** The
detector reads at most 1MB, so that field is a sample count and under-reports on
larger files.

## Warning text

When the count is below the recommended minimum:

> "⚠️ Your dataset has [N] records. We recommend a minimum of 200 records for fine-tuning — below that, training is more likely to fail. Would you like to generate more synthetic data to reach the minimum, or do you have additional data to add?"

## Scope

Applies to SageMaker fine-tuning of language models (SFT, DPO, RLVR) on both Open
Weights and Nova base models.

Does **not** apply to:

- Tabular generation for traditional ML (XGBoost, LightGBM)
- Database seeding, test fixtures, data augmentation, or any non-training
  synthetic data use case
- Evaluation-only datasets (a small eval set is coarse and noisy, but it runs)

Do not warn a user who asked for 70 rows of CSV to seed a database.

## Warn, do not block

Surface the number and the consequence, then let the user decide. Do not proceed
to fine-tuning without the user acknowledging the warning, but do not hard-block
on it either, and do not re-litigate once they have decided.
