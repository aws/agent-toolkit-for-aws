---
_fragment: cutover
_of_phase: clarify
_contributes:
  - preferences.json
---
# Clarify cutover and rollback
Cutover facts are never discovered. Ask them together in one batch near the end of the interview.

| `question_id` | Resource | Topic | Ask when | Default and consequence | `decision_changed` | Consumer |
| --- | --- | --- | --- | --- | --- | --- |
| `cutover.downtime_window` | none | `delivery` | always | `short_window`: a planned maintenance window with traffic stopped, then switched once. The other value is `staged_shift`: a weighted traffic shift with both stacks serving. | Traffic cutover pattern (single switch or staged weighted shift) | Generate guide Deployment and DNS cutover sections. |
| `domain.ttl_control` | each custom domain | `network` | the inventory has a public custom domain | `ttl_lowered_24h_ahead`: the DNS owner lowers TTL a day before cutover. | Whether staged DNS shift is available | Design networking Domains and TLS; Generate guide DNS cutover. |
| `cutover.source_retention` | none | `delivery` | always | `retain_14_days`: keep Render running until sign-off. | Rollback window and Render overlap period | Generate guide Rollback and source retention. |

Precedence: `cutover.downtime_window` selects the pattern and `domain.ttl_control` only limits it.

- `short_window` with `ttl_lowered_24h_ahead`: lower TTL ahead, then one single switch with traffic stopped.
- `short_window` with `cannot_lower`: one single switch; state the exposure window as the current TTL.
- `staged_shift` with `ttl_lowered_24h_ahead`: staged weighted shift, observe, then move fully.
- `staged_shift` with `cannot_lower`: staging is unavailable. Fall back to one single switch, state the exposure window as the current TTL, and tell the user the staged request was not honored.

When the domain row is `not_applicable` (no public custom domain), `downtime_window` alone applies.
