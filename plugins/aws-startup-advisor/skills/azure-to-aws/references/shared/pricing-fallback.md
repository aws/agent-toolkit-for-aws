# Pricing Fallback

> Cache-only policy for when a service is not found in the pricing cache.
> There is no live pricing MCP — the cache is the authoritative source.

## Policy

When a service is NOT in `references/shared/pricing-cache.md` (AI models) or
`references/vendored/pricing/aws-infra-pricing.json` (infrastructure):

1. If the cost engine's own formulas carry a well-known published rate (stated verbatim), set `pricing_source: "estimated"` and include a warning naming the rate and its source.
2. Otherwise set `pricing_source: "unavailable"`, add the service to `services_with_missing_fallback`, and warn the user: "Pricing unavailable for [service] — not in cache and no formula constant. Exclude from totals or provide a manual estimate."

## Do Not Guess

Never emit fabricated prices. A missing cost estimate is better than a wrong one. Infrastructure prices (Fargate, RDS, S3, etc.) from the cached rate card may still be used — infrastructure prices change rarely and the cache remains reliable.
