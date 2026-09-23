# Migration Decision — Heroku to AWS

**Verdict: Go, with conditions** (phased migration · medium complexity · medium confidence)

Execution shape: Phased migration.

## Costs (estimated monthly)

| Tier                                            | Est. Monthly AWS |
| ----------------------------------------------- | ---------------- |
| Premium                                         | $265/mo          |
| **Balanced** (compare Heroku to this row first) | **$210/mo**      |
| Optimized                                       | $178/mo          |

Heroku baseline (from your Heroku invoice): Est. $340/mo.

## Timeline

~6–10 weeks if you execute (medium complexity).

## What would flip this

- A confirmed always-on traffic pattern would raise the AWS compute estimate materially.

---

**Ready to execute?** Say "generate the Terraform and migration scripts" and I'll produce the full execution pack (Terraform, migration scripts, MIGRATION_GUIDE.md) from this same analysis. This decision report was generated without execution artifacts; the full migration report replaces it if you proceed.

_Draft for review._
