---
_fragment: global
_of_phase: clarify
_contributes:
  - preferences.json (global section; created here, finalized by the assembler)
---

# Clarify — Global Preferences

> **Fragment unit.** See `clarify.md` for how it is composed into the phase.

Gathers the estate-wide answers every Azure migration needs regardless of what the
inventory contains: target AWS region (mapped from the estate's Azure regions rather
than assumed), user geography, compliance requirements, multi-cloud portability,
migration window, environment scope (which of the discovered subscriptions and
environments are in scope), CPU architecture, and cost-optimization appetite.

**Four of these questions are canonical, shared with `gcp-to-aws`** — see
`references/vendored/clarify/`. Read the linked file for the question text, options,
and interpretation rule; this fragment supplies only the Azure-specific
auto-extraction signal, default, and disposition escalation.

**The architecture default is `x86_64`, and that is a deliberate divergence from the
rest of this repo.** Graviton is the default in the GCP and Heroku skills. Azure
fleets carry Windows and .NET routinely, which is exactly the escape path in
`references/shared/graviton.md`, so defaulting to Graviton here would produce a
recommendation that has to be walked back on a large fraction of real estates.
Graviton is offered as an optimization with its own savings line.

## Step: Return rows

> **This fragment asks nothing.** `clarify-assemble.md` owns the conversation — see
> `clarify.md` § Step: Run the phase for why presentation is centralised.

### Q-A1 — Target AWS region

**Disposition:** DETECTED when every resource shares one Azure region and the map resolves
it; **ESSENTIAL** when the estate spans regions (there is no defensible way to pick one for
someone). **Default when DETECTED:** the mapped region.

Map from the estate's Azure regions via `knowledge/design/azure-region-map.json` — do not
assume `us-east-1` when the estate is plainly European. `westeurope` → `eu-west-1`.

This is the region-**mapping** half of the canonical region question
(`references/vendored/clarify/clarify-region.md`). Read that file for the
"where are your users" half. **Disposition (Q-A1b):** PROPOSED when Q-A1 resolves to a
single mapped region (default: `"single-region"`, matching the canonical file's default
answer 1 — the shortcut is the same one GCP's Q1 documents: a single detected
infrastructure region does not by itself prove single-region users, but it is a reasonable
default, correctable on the sheet); **ESSENTIAL** when the estate spans multiple Azure
regions (the map cannot pick one AND geography genuinely needs a direct answer, mirroring
GCP's Q1 escalation rule). A CDN / Front Door / Traffic Manager resource in the inventory is
a DETECTED signal for `"multi-region"` or `"global"` — read it before proposing
`"single-region"`.

### Q-A1c — Compliance and regulatory requirements — **ESSENTIAL, always**

Canonical question: `references/vendored/clarify/clarify-compliance.md`. **This
question always fires for a full-infrastructure Azure migration** — there is no
Azure-specific auto-extraction signal (compliance status is never inferable from
ARM/Bicep/Terraform), so this fragment supplies no override to the canonical file's
disposition, options, or default. Ask it exactly as written there.

This closes a real gap: before this fragment referenced the canonical file, Azure's
infrastructure Clarify flow asked no compliance question at all, and `estimate-infra.md`
had to carry a permanent `compliance: null` special case as a result. Now that this
question fires, `estimate-infra.md`'s Part 7 hard-trigger-1 first clause is no longer
permanently true — it evaluates normally against the recorded `compliance` array.

### Q-A1d — Multi-cloud portability

**Disposition:** PROPOSED when compute resources are present; N/A otherwise.
**Default:** per the canonical file — no constraint, full compute decision tree.

Canonical question: `references/vendored/clarify/clarify-multicloud.md`. On this
skill, a "yes" answer's early exit routes to EKS and skips **Q-C1** (compute target)
in `clarify-compute.md` — any App-Service-Plan compute that would otherwise default
to Elastic Beanstalk routes to EKS instead, overriding Q-C1's normal default. Record
the resolved value as `design_constraints.compute_target: { value: "eks", chosen_by:
"user", forced_by: "multi_cloud_required" }` so Q-C1 can detect the early exit and
skip its own row entirely rather than emitting a second, conflicting compute-target
row.

### Q-A2 — Environment scope

**Disposition:** DETECTED from the resource groups and name patterns present.
**Default:** every environment found.

Under an obfuscated RDfA report the `prod_` / `nonprod_` prefixes give this directly. From
Terraform it is a name-pattern heuristic (`-dev`, `-prod`, `d-`, `t-`, `s-`), so treat it as
a strong hint and show what was inferred rather than asserting it.

### Q-A3 — Migration window

**Disposition:** PROPOSED. **Default:** `null` — unstated.

Left null rather than guessed. It shapes the timeline in the report and nothing in the
design, so an invented window would add false precision to the one output people quote.

### Q-A4 — Cost optimization appetite

Canonical question: `references/vendored/clarify/clarify-cost-appetite.md`. **Disposition:**
PROPOSED. **Default:** `balanced` (per the canonical file).

Feeds the aggressiveness slider in `knowledge/estimate/rightsizing-thresholds.json`. With no
utilization data it changes nothing — say so on the row rather than implying it will (the
canonical file states this same caveat; repeat it on the sheet, do not drop it).

### Q-A5 — Azure baseline spend

**Disposition:** DETECTED when a billing export was discovered; **ESSENTIAL** otherwise —
there is no way to infer what someone pays.

Anchors the migrate-versus-stay comparison. With no billing source the whole comparison is
absent from the report, which is worth stating rather than leaving the reader to notice.

## Rows returned

```jsonc
"global": {
  "target_region":     { "disposition": "DETECTED", "value": "eu-west-1", "default": "eu-west-1" },
  "user_geography":    { "disposition": "PROPOSED", "value": "single-region", "default": "single-region" },
  "environment_scope": { "disposition": "DETECTED", "value": ["prod"],   "default": ["prod"] },
  "migration_window":  { "disposition": "PROPOSED", "value": null,       "default": null }
},
"design_constraints": {
  "compliance":        { "disposition": "ESSENTIAL", "value": null, "default": null },
  "cost_optimization": { "disposition": "PROPOSED", "value": null, "default": "balanced" }
},
"baseline": {
  "azure_monthly_spend": { "disposition": "ESSENTIAL", "value": null, "default": null }
}
```

`cpu_architecture` and `compute_target` are **not** here — they belong to
`clarify-compute.md`'s Q-C3 and Q-C1. **This fragment writes `design_constraints
.compute_target` itself ONLY when Q-A1d (multi-cloud) resolves to "yes"** — in that case it
writes `{ "value": "eks", "chosen_by": "user", "forced_by": "multi_cloud_required" }` and
Q-C1 in `clarify-compute.md` becomes N/A. When multi-cloud resolves to "no" (the default),
this fragment writes **no** `compute_target` key at all — Q-C1 is the sole owner of that row
in the ordinary case, exactly as before this restructure.

## Who consumes these

| Row                   | Consumer                                                                                         |
| --------------------- | ------------------------------------------------------------------------------------------------ |
| `target_region`       | Design's region selection; every downstream cost figure                                          |
| `user_geography`      | Design's CDN / Route 53 strategy (`networking.md` §2.3), and Q-D1's Catastrophic → Aurora Global |
| `compliance`          | Estimate complexity + hard-trigger 1; Design catalog/region gate; Generate hardening posture     |
| `cost_optimization`   | Estimate's aggressiveness slider (`rightsizing-thresholds.json`)                                 |
| `azure_monthly_spend` | Estimate's migrate-vs-stay comparison                                                            |

## Status — build step 5

Implemented. `knowledge/design/azure-region-map.json` **exists** — look the region up
there, and do NOT emit a "table absent" flag. Where the row's `same_country` is false the
move crosses a border: surface that as a residency warning rather than resolving it
silently.
