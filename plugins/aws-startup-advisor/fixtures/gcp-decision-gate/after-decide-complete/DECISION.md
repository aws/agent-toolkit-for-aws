# Migration Decision — GCP to AWS

**Verdict: Go, with conditions** (phased migration · moderate complexity · medium confidence)

Proceed with a phased migration on the Balanced cost scenario once the availability assumption is confirmed.

## Costs (estimated monthly)

| Tier                                         | Est. Monthly AWS |
| -------------------------------------------- | ---------------- |
| Premium                                      | $212/mo          |
| **Balanced** (compare GCP to this row first) | **$155/mo**      |
| Optimized                                    | $118/mo          |

GCP baseline: estimated from resource configs (±20–30%, standing charges only). The stated $1K–$5K/mo spend band measures the whole bill and is not directly comparable.

## Migrate if / Stay if

- **Migrate if:** you want managed compute without Kubernetes operations; consolidating AI usage onto Bedrock matters this year.
- **Stay if:** your GCP committed-use discounts run through 2027.

## Timeline

Phased in dependency order if you execute — long pole: database migration, then cutover in a maintenance window (medium-complexity drivers; no week estimates — uncalibrated).

## Top risks

- Availability posture assumed single-AZ — confirm before cutover sizing.
- BigQuery deferred to specialist engagement; excluded from combined totals.

## What this rests on

Region, database size, and model detection extracted from Terraform and code; availability defaulted to single-AZ per dev-tier signals. Cached pricing dated 2026-07 (±5–10% infra).

---

**Ready to execute?** Say "generate the Terraform and migration scripts" for the full execution pack. _Draft for review._
