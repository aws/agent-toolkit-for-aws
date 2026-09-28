# Clarify — Region & User Geography (canonical)

> Canonical region-selection question for Clarify's Global/Strategic category,
> vendored into each skill that runs a full-migration Clarify phase
> (`references/vendored/clarify/clarify-region.md`) and kept byte-identical by
> `shared:sync`. This file owns the **question text, answer options, and
> interpretation rule** — the part that does not change by source cloud. Each
> skill's own `clarify-global.md` owns the **auto-extraction signal** (which
> source-cloud resource field resolves it) and the **disposition** (DETECTED /
> ESSENTIAL), because those genuinely differ: GCP has a single-region-vs-multi
> extraction path over `gcp-resource-inventory.json`; Azure resolves the same
> question two ways — a region MAP lookup (`Q-A1`, always fires) plus this
> user-geography question, asked only when the map alone cannot decide a CDN /
> replication strategy.

## Why this file exists

Before this file, `gcp-to-aws`'s Q1 ("Where are your users located?") did double
duty — it drove target-region selection AND CDN/replication strategy — while
`azure-to-aws`'s Q-A1 only mapped Azure regions to AWS regions and had no
equivalent geography question. Extracting the question here means a wording or
answer-option fix lands for every skill in one commit, and it makes the
"Azure has no user-geography question" gap a one-file fix instead of a
from-scratch design.

## The question

> I need to understand your user base to recommend the right AWS region and CDN strategy.
> (This question is about where your **users** are — latency and placement. If you have
> **data residency** obligations, GDPR or similar, that's handled by the compliance
> question, not this one.)
>
> 1. Single region (e.g., US-only, EU-only)
> 2. Multi-region (2–3 regions, e.g., US + EU)
> 3. Global (users worldwide, latency critical)
> 4. I don't know

| Answer        | Recommendation Impact                                                                                                                                                                                                                                           |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Single region | Deploy in closest AWS region to users; standard Route 53 routing                                                                                                                                                                                                |
| Multi-region  | Primary region closest to majority; CloudFront for static assets and API caching; Route 53 latency-based routing — multi-region infrastructure deferred to the availability question                                                                            |
| Global        | Primary region by largest user concentration; CloudFront globally distributed; Route 53 geolocation routing — Aurora Global Database and multi-region compute only if the availability answer is Catastrophic AND write latency is a confirmed hard requirement |

### Interpret

```
1 -> user_geography: "single-region", target_region: "<closest AWS region to the estate's source-cloud region>"
2 -> user_geography: "multi-region", target_region: "<closest AWS region>", replication: "cross-region"
3 -> user_geography: "global", target_region: "<closest AWS region>", replication: "cross-region", cdn: "required"
4 -> same as default (1)
```

**Default:** 1 — single region, closest AWS region to the estate's primary source-cloud
region.

## What a consuming skill supplies

Each skill's `clarify-global.md` (or equivalent) fills in:

1. **The region-mapping table** — GCP maps GCP regions to AWS regions from
   inventory; Azure maps Azure regions to AWS regions via
   `knowledge/design/azure-region-map.json`. This file has no opinion on the
   mapping table itself, only on the question that decides _when_ a single
   answer suffices versus when geography needs asking directly.
2. **Auto-extraction / skip rule** — when the estate's resources all agree on
   one source-cloud region, a skill MAY treat that as `user_geography:
   "single-region"` with `chosen_by: "extracted"` and skip presenting this
   question, PROVIDED the skill also asks (or has already asked) where the
   _users_ are when the estate spans regions — a single Azure/GCP region does
   not, by itself, prove users are single-region; a skill that skips outright
   on region-count alone must say so as a documented shortcut, not silently
   claim `chosen_by: "extracted"` for the geography row.
3. **Cross-border / residency framing** — a skill whose source estate can span
   country borders (Azure explicitly does — see `clarify-global.md`'s
   `same_country` handling) states the residency warning; this file's
   question is deliberately silent on legal residency, which belongs to the
   compliance question (`clarify-compliance.md`).
