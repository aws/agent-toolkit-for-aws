---
_fragment: governance
_of_phase: clarify
_contributes:
  - preferences.json
---
# Clarify data governance and budget
Run after the vendored compliance and cost-appetite questions. These rows narrow them only when a data store or a budget limit can change a design.

| `question_id` | Resource | Topic | Ask when | Default and consequence | `decision_changed` | Consumer |
| --- | --- | --- | --- | --- | --- | --- |
| `data.regulated_data` | each PostgreSQL, Key Value, persistent disk | `data` | compliance is anything other than the explicit answer `none` | none. Unresolved until the user says which stores hold regulated or personal data. | Customer-managed KMS key and in-Region-only backups for that store | Design data store configuration; Estimate KMS line; Generate guide Prerequisites. |
| `cost.budget_guardrail` | none | `global` | always, as one line | `no_budget_limit`: the baseline budget is created at the default `max(50, ceil(1.2 * balanced monthly estimate))`; the report recommends no separate alert. A stated number replaces that limit. | The AWS Budgets limit in `baseline.tf` and the report's alert threshold | Estimate explanation (known-cost floor against the limit); Generate baseline budget (`generate-artifacts-baseline.md`); Generate guide Known limitations. |

When compliance is `none`, mark every `data.regulated_data` row `not_applicable` with that fact as evidence.
