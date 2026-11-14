# Clarify — Cost-Optimization Appetite (canonical)

> Canonical cost-optimization-appetite question for Clarify's Global/Strategic
> category, vendored into each skill that runs a full-migration Clarify phase
> (`references/vendored/clarify/clarify-cost-appetite.md`) and kept
> byte-identical by `shared:sync`. This question is source-cloud-agnostic: how
> aggressively a customer wants to right-size does not depend on which cloud
> they are leaving.

## Why this file exists

`azure-to-aws` had a first-class, explicitly-named "cost optimization
appetite" question (its Q-A4 — Conservative / Balanced / Aggressive) feeding
`rightsizing-thresholds.json`. `gcp-to-aws` had no equivalent **named**
question — its cost posture was implicit, spread across the opt-in Category E
("Migration Posture," disabled by default) right-sizing toggle. Promoting
Azure's version into this shared file, and wiring GCP's Category E to read
from it, gives both skills one explicit, always-visible cost-appetite knob
instead of GCP's silently-disabled-by-default right-sizing toggle.

## The question

> How aggressively should we right-size your AWS design versus your current capacity?
>
> [A] Conservative — like-for-like capacity, lowest risk
> [B] Balanced — right-size where measured data supports it (default)
> [C] Aggressive — smallest defensible footprint

**Consequence line:** _Balanced right-sizes only where measurement supports it.
Aggressive can cut the estimate materially and needs load testing before cutover._

### Interpret

```
A -> cost_optimization: "conservative" — like-for-like capacity, no right-sizing
B -> cost_optimization: "balanced" — right-size only where utilization data supports it
C -> cost_optimization: "aggressive" — smallest defensible footprint; flag load-testing need
```

**Default:** `balanced`.

**With no utilization data, this answer changes nothing** — say so on the sheet row rather
than implying a right-sizing pass will run when there is no measured baseline to right-size
from. This is the single biggest trap with this knob: an "Aggressive" answer over an
inventory with no billing/utilization export produces the same design as "Balanced," and the
sheet must say that plainly rather than letting the user believe they bought a smaller
estimate.

## What a consuming skill supplies

1. **Where the knob feeds.** Azure feeds `knowledge/estimate/rightsizing-thresholds.json`
   directly. GCP feeds its Category E opt-in (`ha_upgrade`, `right_sizing`) — GCP's Category E
   questions (Q-E1/Q-E2) become **redundant with, and should be superseded by,** this single
   knob: a GCP run that answers `aggressive` here should behave as if the user opted into
   Category E's `right_sizing: true`, without asking Q-E2 separately. GCP's Q-E1 (HA upgrade
   opt-in) is a distinct decision — this question governs sizing/instance-class aggressiveness,
   not availability tier — and stays a separate opt-in.
2. **Disposition.** PROPOSED in both skills; never ESSENTIAL — a sensible default (Balanced)
   always exists and the consequence of guessing wrong is a report caveat, not a wrong
   architecture.
