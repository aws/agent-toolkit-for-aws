# Result Interpretation — Deduplication

Apply these checks to the aggregate results and include any triggered flags in the report. They are
**descriptive**: the report says what was found; the user decides whether to remove anything.

## Duplicate rate

Use the same bands dataset-quality uses for `uniqueness` (a duplicate rate of `1 - uniqueness_ratio`):

| `duplicate_rate` | Flag |
|---|---|
| below 0.05 | none — "Duplication is low." |
| 0.05 to 0.30 | "⚠️ [X]% of rows are [exact / near-] duplicates — moderate duplication." |
| above 0.30 | "🚨 [X]% of rows are [exact / near-] duplicates — heavy duplication." |

Report the two operators separately; a fuzzy rate far above the exact rate means the data is
paraphrased rather than copied, which matters for how it should be cleaned.

## Group shape

- `duplicate_groups` much smaller than `duplicate_count` means a few values repeat many times
  (templated or boilerplate rows). Offer to show the largest groups.
- `duplicate_groups` close to `duplicate_count` means mostly pairs.

## Explaining a flagged pair

When the report says why two rows were flagged, or why the exact check missed a pair the fuzzy check
found, the explanation comes from the rows themselves. Read the full field value of every row in the
pair or group from the record-level file, compare the values end to end, and state what they share
and each place they differ, quoting the differing parts or counting them ("the opening and the closing
instruction differ; the 98 words between them match"). A reading of the first few hundred characters
is not a comparison: a difference past the cut goes unseen and the claim comes out wrong, and a claim
corrected a turn later costs more trust than one made after the comparison. The `reason` column names
the decision (`near_duplicate`, `representative`), not what the rows have in common, so it is never
paraphrased as the explanation. The 120-character truncation below is for display; the comparison
runs on the whole values.

## Fuzzy caveats to state once

- The Jaccard threshold is a target for probabilistic candidate generation, not a hard floor.
- Clusters are transitive, so members of one cluster are not all pairwise above the threshold.
- Fields with fewer than five words are skipped by the fuzzy pass and are never flagged.

If the user expected more or fewer matches, offer to rerun with a different `JaccardThreshold`.

## Drilling into groups

When the user asks to see duplicates, use the helper script's group listing
(`dedup_decisions.py --groups N`, run from the shell; the option calls the script's `duplicate_groups_for()`). It joins
each flagged row to its representative via `representative_row_id`. Show at most 20 groups, largest
first, with the representative text and member texts truncated to about 120 characters. Report the
total number of groups. Row numbers are the job's `row_id`, which starts at 0: say so with the first
group, with the file line ("Row numbers start at 0, so rows 3 and 30 are lines 4 and 31 of the
dataset file"). Never load the whole scored file into the conversation.
