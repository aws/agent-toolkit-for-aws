# Migration Decision — Heroku to AWS

**Verdict: Go, with conditions** (phased migration · small complexity · medium confidence)

Execution shape: Phased migration.

## Share with your CFO

Go, with conditions, at medium confidence. Estimated AWS Balanced is $210 per month against an estimated Heroku baseline of $340 per month. The migration shape is phased, and the planning band for this small estate is 2-6 weeks. Confirm the open condition before treating the monthly figure as final.

## Costs (estimated monthly)

| Tier                                            | Est. Monthly AWS |
| ----------------------------------------------- | ---------------- |
| Premium                                         | $265/mo          |
| **Balanced** (compare Heroku to this row first) | **$210/mo**      |
| Optimized                                       | $178/mo          |

💡 Review [AWS Activate credits](https://aws.amazon.com/startups/credits/) tiers (Founders for self-funded startups, Portfolio for VC- or accelerator-backed ones) — your funding stage was not confirmed in Clarify. Credits apply only to charges after approval, so apply before any deployment.

Heroku baseline (from your Heroku invoice): Est. $340/mo.

## Timeline

Planning band: 2-6 weeks (small). This is the complexity-tier planning range, not a staffed schedule.

## What would flip this

- A confirmed always-on traffic pattern would raise the AWS compute estimate materially.

---

**Ready to execute?** Say "generate the Terraform and migration scripts" and I'll produce the full execution pack (Terraform, migration scripts, MIGRATION_GUIDE.md) from this same analysis. This decision report was generated without execution artifacts; the full migration report replaces it if you proceed.

_Draft for review._
