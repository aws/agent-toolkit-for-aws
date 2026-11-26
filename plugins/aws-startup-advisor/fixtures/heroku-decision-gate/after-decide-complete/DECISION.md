# Migration Decision — Heroku to AWS

**Verdict: Go, with conditions** (phased migration · small complexity · medium confidence)

Execution shape: Phased migration.

## Share with your CFO

Go, with conditions, at medium confidence. Estimated AWS Balanced is $210 per month against an estimated Heroku baseline of $340 per month. The migration shape is phased for this small estate. Confirm the open condition before treating the monthly figure as final.

## Costs (estimated monthly)

| Tier                                            | Est. Monthly AWS |
| ----------------------------------------------- | ---------------- |
| Premium                                         | $265/mo          |
| **Balanced** (compare Heroku to this row first) | **$210/mo**      |
| Optimized                                       | $178/mo          |

💡 Review [AWS Activate credits](https://aws.amazon.com/startups/credits/) tiers (Founders for self-funded startups, Portfolio for VC- or accelerator-backed ones) — your funding stage was not confirmed in Clarify. Credits apply only to charges after approval, so apply before any deployment.

Heroku baseline (from your Heroku invoice): Est. $340/mo.

## Timeline

Shape: Phased migration. Stage order: provision the AWS environment, migrate the database, then cut over DNS per app. Duration drivers: a small estate (two services) and a single-AZ database. The cutover procedure stays in the migration guide; this is not a staffed schedule.

## Developer workflow

Developer workflow priority was not rated critical in Clarify.

| Heroku today                        | On AWS                                                          | Status                                                         | Your estate                         |
| ----------------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------- | ----------------------------------- |
| `git push heroku main` + buildpacks | CI builds a container image and deploys it to Elastic Beanstalk | **Will be generated** — a deploy workflow per app              | 1 buildpack app on Beanstalk        |
| Config vars                         | Parameter Store / Secrets Manager, injected at deploy           | **Covered** — bindings will be generated; you import the values | 1 app                              |
| `heroku run` / one-off dynos        | ECS Exec or `eb ssh`                                            | **Covered** — different command for the target                 | —                                   |
| `heroku logs --tail`                | CloudWatch Logs live tail                                       | **Covered**                                                    | —                                   |
| Release phase                       | A pre-deploy job in the workflow that runs before traffic shifts | **Build**                                                     | —                                   |
| Add-on marketplace                  | Each add-on becomes an AWS service wired by the Terraform that Generate will produce | **No equivalent** to the marketplace itself | 1 add-on mapped (Postgres), 0 deferred |

The rows marked Build are a platform layer your team owns: release steps and a thin command wrapper. It is a bounded piece of platform work, and it is the same for every app.

## What would flip this

- A confirmed always-on traffic pattern would raise the AWS compute estimate materially.

---

**Ready to execute?** Say "generate the Terraform and migration scripts" and I'll produce the full execution pack (Terraform, migration scripts, MIGRATION_GUIDE.md) from this same analysis. This decision report was generated without execution artifacts; the full migration report replaces it if you proceed.

_Draft for review._
