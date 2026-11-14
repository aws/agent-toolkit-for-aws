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
| `cutover.downtime_window` | none | `delivery` | always | `short_window`: a planned maintenance window with traffic stopped, then switched. | Traffic cutover pattern (staged weighted shift or single switch) | Generate guide Deployment and DNS cutover sections. |
| `domain.ttl_control` | each custom domain | `network` | the inventory has a public custom domain | `ttl_lowered_24h_ahead`: the DNS owner lowers TTL a day before cutover. | Whether staged DNS shift is available | Design networking Domains and TLS; Generate guide DNS cutover. |
| `cutover.source_retention` | none | `delivery` | always | `retain_14_days`: keep Render running until sign-off. | Rollback window and Render overlap period | Generate guide Rollback and source retention. |

A `domain.ttl_control` answer of `cannot_lower` blocks staged shift. The guide must then state the hard-switch exposure window as the current TTL.
