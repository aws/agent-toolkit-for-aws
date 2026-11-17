# Post-Annotation Metrics

Computed after annotation is complete. Measures data improvement from the low-confidence correction path.

## Correction rate

```python
corrected = sum(1 for r in annotations
                if (r.get("corrected_completion") or "").strip() != "")
correction_rate = corrected / len(annotations)
```

Interpretation:

- > 0.5: most records had real problems — human-in-the-loop review was warranted
- 0.2–0.5: some records had problems — thresholds may be slightly aggressive
- < 0.2: few records had real problems — thresholds are too aggressive, sending too many records to human-in-the-loop review

### Auto-labeling input

Auto-labeling's `review.jsonl` and its cold-start sample carry no model answer, so every reviewed row comes back with the reviewer's own label: the correction rate above, and the corrected and acceptable-as-is counts and side-by-side examples of the summary (Step 6b), do not apply to them. For `review.jsonl`, auto-labeling's fold counts, per review reason (`_review_reason`), the rows whose label confirmed the model's and the rows that corrected it (`auto-labeling/references/full-loop.md`, Step 7b). Its `calibration` rows are a random draw from the auto-accepted band, so their correction rate is the human-alignment figure for the auto-accepted set; the rest measure the low-confidence corrections. Do not pool them, and do not apply the interpretation bands above to the `calibration` rate.

## Fill rate (for missing value tasks)

The filled value is in `corrected_completion`, as in the captured row schema (`references/local-review-guide.md` → Step 3b: Captured row schema).

```python
filled = sum(1 for r in annotations
             if (r.get("corrected_completion") or "").strip() != "")
fill_rate = filled / len(annotations)
```

## Rejection rate

```python
rejected = sum(1 for r in annotations
               if "unfixable" in (r.get("issues") or []))
rejection_rate = rejected / len(annotations)
```

High rejection rate = generator is producing fundamentally wrong outputs that can't be fixed by editing. Action: update the generator prompt.

## Score delta (requires re-running `dataset-quality` on corrected records)

Compare aggregate `dataset-quality` scores before and after correction. The headline metric for the full human-in-the-loop cycle.

## Cycle improvement rate

```
cycle_improvement = (post_hil_score_mean - pre_hil_score_mean) / pre_hil_score_mean
```

## Human-in-the-loop ROI (track from cycle 2+)

```
hil_roi = records_with_real_problems / total_records_sent_to_hil
```

Low ROI = thresholds are too aggressive. Raise the confidence threshold for routing to human-in-the-loop review.
