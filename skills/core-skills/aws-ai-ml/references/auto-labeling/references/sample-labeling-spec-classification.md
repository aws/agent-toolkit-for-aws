# Auto-Labeling Specification: Customer Support Intent Classification

## Use Case Context
Classify incoming customer support messages by intent so they can be routed to the correct team. Labels will be used to fine-tune a classification model for real-time ticket routing.

## Quality Standards

- Label accuracy ≥ 90% on held-out data
- Consistent labeling across messages with similar phrasing but different surface keywords
- Multi-intent messages should be labeled by primary intent

## Input Data

- **Source:** s3://my-bucket/support/unlabeled_tickets.jsonl
- **Input field:** `message`
- **Size:** ~5,000 rows
- **Domain:** Customer support tickets for a SaaS product (billing, technical issues, account management, feature requests, general inquiries)

### Labelled Seed (required for full loop and refinement)

- **Source:** s3://my-bucket/support/labelled_seed.jsonl
- **Ground-truth field:** `gt_label`
- **Size:** 40 rows (8 per class; enough to refine the spec, too few for an accuracy promise, which needs about 200)

## Input Data Preparation (optional)

- Remove duplicate messages (exact match)
- Filter out messages shorter than 10 characters (likely noise)

## Labelling Configuration
### Label Set

| Label | Definition |
|---|---|
| billing | Questions or issues related to charges, invoices, payment methods, refunds, or pricing plans |
| technical_issue | Reports of bugs, errors, outages, or unexpected system behavior |
| account_management | Requests to change account settings, add/remove users, update permissions, or manage subscriptions |
| feature_request | Suggestions for new features or improvements to existing functionality |
| general_inquiry | Questions about the product, company, or process that don't fit other categories |

### Labelling Rules

- **billing:** Message mentions money, charges, pricing, plans, invoices, or refunds.
- **technical_issue:** User describes something not working as expected - errors, bugs, broken features.
- **account_management:** Requests about who has access, account settings, or subscription changes without mentioning cost.
- **feature_request:** User asks for functionality that doesn't exist yet ("it would be nice if...", "can you add...").
- **general_inquiry:** Questions about how things work, support hours, or company info - nothing broken, no action requested.
- **billing vs account_management:** If the message is about changing a plan tier (involves pricing), it's `billing`. If it's about changing who has access without mentioning cost, it's `account_management`.
- **technical_issue vs general_inquiry:** If something is not working as expected, it's `technical_issue`. If they're asking how to do something that works fine, it's `general_inquiry`.
- **feature_request vs technical_issue:** If functionality doesn't exist yet, it's `feature_request`. If it used to work or should work but is broken, it's `technical_issue`.
- **Multi-intent:** Label by the primary intent (what they want resolved).

## Output Schema
Per record: a short reasoning chain, then the final label (one of the label set). Ground truth, if present in the input data, is for scoring only and must not be read when predicting. This is the labeling job's own reply format; the job appends it after the spec and reads only these keys.

```
{"reasoning": "<one short sentence explaining the label choice>", "label": "<one of the labels from the Label Set above>"}
```

## Data Verification

### Verification Mode
deterministic

Do not use LLM to verify samples. All verification must be pure Python only. Do not make any LLM calls in the verification function.

### Checks

1. **Structural checks**:
    - Output is a single JSON object with "reasoning" and "label" keys
    - label value is one of: billing, technical_issue, account_management, feature_request, general_inquiry (exact match, case-sensitive)
    - reasoning is non-empty
