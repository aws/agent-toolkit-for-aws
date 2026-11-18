---
_fragment: delivery
_of_phase: clarify
_contributes:
  - preferences.json
---
# Clarify build, preview, and observability ownership
Ask only what the inventory leaves open. A discovered auto-deploy flag, Build Source, or preview setting is recorded as `discovered`. All rows use topic `delivery` and `resource_id` null.

| `question_id` | Ask when | Default and consequence | `decision_changed` | Consumer |
| --- | --- | --- | --- | --- |
| `delivery.ci_owner` | the inventory has a service or Build Source built from a repository | `github_actions`: the guide names GitHub Actions as the runner of build-once, promote-digest. | CI system that runs the promotion pipeline | Design delivery Build Sources and artifacts; Generate guide Build section and promote-image script usage. |
| `delivery.preview_policy` | the inventory shows pull-request previews or a preview environment | `shared_staging`: no per-PR stacks. Reviewers use one staging stack. | Preview delivery target: per-PR ephemeral stack or shared staging | Design delivery Preview environments; Generate guide Known limitations. |
| `observability.log_retention` | always | `30_days`: CloudWatch Logs retention of 30 days. | CloudWatch Logs retention and alarm scope | Design delivery Logs, metrics, and alarms; Estimate log line; Generate log groups in compute, workflow and data log exports (`generate-infra-compute.md`, `generate-infra-workflow.md`, `generate-infra-data.md`). |

When `delivery.preview_policy` is `per_pr_stack`, use the cost guard and cleanup facts from the global preview-environment answer. Do not re-ask them.
