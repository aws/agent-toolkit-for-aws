# Maturity & Readiness

Use this reference for the target maturity collected in Intake. It governs launch readiness,
not runtime scoring: a deployable proof-of-concept is not automatically ready for a beta or
production launch.

## Tiers and required controls

| Target maturity | Minimum controls                                                                                                                                                                           | Evaluation and release gate                                                                                                                                   |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `prototype`     | Isolated test account, synthetic or approved test data, basic logs, named owner                                                                                                            | Demonstrate the intended task on representative prompts; record known failure modes and rollback/delete instructions.                                         |
| `private_beta`  | Prototype controls plus authenticated, allowlisted users, tenant/data boundaries, feedback path, cost guardrail, and human escalation/rollback                                             | Pass representative task and safety evaluation; confirm beta audience, monitoring owner, rollback, and feedback triage before admitting users.                |
| `production`    | Private-beta controls plus least-privilege access, secrets/retention review, SLOs and alerts, incident/runbook ownership, capacity/load evidence, and compliance evidence where applicable | Pass release evaluation and load/safety gates; close all critical readiness gaps; approve rollout, rollback, and on-call ownership before production traffic. |

## Evaluation rules

- Record each control as `met`, `gap`, `not_applicable`, or `unknown`; `gap` and `unknown`
  remain readiness gaps unless the reference explicitly marks the control not applicable.
- `prototype` may proceed as a deployable POC with open launch-readiness gaps, but its report
  must label the target as prototype rather than a beta or production launch.
- `private_beta` and `production` recommendations list the unmet controls and their release
  gates. Do not state that a tier is launch-ready while a required control is a gap.
- Current-run service limits, regional availability, and pricing/billing claims are separate
  verification gates. A cached value may guide exploration but cannot close a launch gate.
