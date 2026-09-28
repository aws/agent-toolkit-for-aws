# Estimate — Pricing Mode Selection (canonical Step 0)

> Canonical pricing-mode procedure for estimate cost engines, vendored into
> each skill (`references/vendored/estimate/pricing-mode.md`) and kept
> byte-identical by hand — copy this file over every vendored copy in the same
> change (see `references/vendored/README.md`). The `cached_stale` enum bug happened because
> two copies of this logic evolved separately — do not fork this text again.
> Skill cost engines execute this file AS their Step 0, then own everything
> after it (baseline rungs, service formulas, tiers).

## Step 0a: Load the pricing cache

Read `references/vendored/pricing/aws-infra-pricing.json`. Check
`_meta.last_updated` against `_meta.staleness_days` (default 30):

- Within the window: **cached prices are the primary source.** No MCP calls
  needed for services in the file. Set `pricing_source: "cached"`.
- Past the window: infrastructure prices remain reliable. Use cached rates as
  fallback with `pricing_source: "cached_stale"`. A cache-miss now goes
  straight to `estimated` (if the engine states the formula rate) or
  `unavailable` — never to a live lookup.

Each service object carries its rates and (where relevant) a
`multi_az_handling` key. Look rates up from the file — never hardcode them.

## Step 0b: Display the pricing mode

Before any calculation, surface the status:

- Cache fresh + all services covered: "Pricing source: cached (updated
  [date], ±5-10% accuracy). No live pricing API required."
- Cache stale + services covered: "Pricing source: stale cache (updated
  [date], ±5-10% accuracy for infrastructure). No live pricing API available."
- Service not in cache: "Some services not in pricing cache. Those services
  will show `pricing_source: unavailable` in the estimate."

## Pricing hierarchy (per-service lookup order)

| Priority | Source                                               | Condition                                                                          | `pricing_source` value |
| -------- | ---------------------------------------------------- | ---------------------------------------------------------------------------------- | ---------------------- |
| 1        | `references/vendored/pricing/aws-infra-pricing.json` | Service found in the pricing file                                                  | `"cached"`             |
| 2        | Formula constants / well-known published rate        | NOT in file, but the cost engine's own formulas carry the rate (state it verbatim) | `"estimated"`          |
| 3        | Unavailable                                          | NOT in file, no formula constant                                                   | `"unavailable"`        |

Row 2 is the documented home of the `services_by_source.estimated` bucket the
shared schema and assemblers carry: a service priced from a rate the cost
engine itself states (never a guessed or remembered number) is `"estimated"`,
always accompanied by a warning naming the rate and its source. Only a service
with no cache entry AND no stated formula rate is `"unavailable"` and
excluded from totals.
