# Migration Decision — Heroku to AWS

**Verdict: Go, with conditions** (full cutover · small complexity · medium confidence)

Execution shape: Full cutover: one migration window.

Recommendation: migrate to AWS on the Optimized pricing scenario as a full cutover in one migration window, once the open condition is confirmed.

## Share with your CFO

Go, with conditions, at medium confidence. Estimated AWS Balanced is $210 per month; the Heroku bill is not established, so no side-by-side saving is quoted. The migration shape is a full cutover in one migration window for this small estate. Confirm the open condition before treating the monthly figure as final.

## Current stack

2 Heroku resources on one app (acme-web) were mapped to AWS targets. No add-on is deferred.

| Heroku app | Heroku primitive                   | AWS target                                                  |
| ---------- | ---------------------------------- | ----------------------------------------------------------- |
| acme-web   | web formation (compute)            | Elastic Beanstalk — t3.small, load-balanced, 1 to 2 instances |
| acme-web   | Heroku Postgres add-on (database)  | RDS PostgreSQL — db.t4g.medium, Multi-AZ, 64 GB storage      |

## Costs (estimated monthly)

| Tier                                                                 | Est. Monthly AWS |
| -------------------------------------------------------------------- | ---------------- |
| Premium — equals Balanced: every line that can take a resilience uplift is already Multi-AZ (the RDS rate includes it), so there is no higher-availability variant to price | $210/mo |
| **Balanced** (compare Heroku to this row first)                      | **$210/mo**      |
| Optimized                                                            | $182/mo          |

💡 Review [AWS Activate credits](https://aws.amazon.com/startups/credits/) tiers (Founders for self-funded startups, Portfolio for VC- or accelerator-backed ones) — your funding stage was not confirmed in Clarify. Credits apply only to charges after approval, so apply before any deployment.

No Heroku baseline was available for this run (no invoice or contract was supplied), so no side-by-side comparison is shown.

## Migrate if

- You want the AWS control plane: your own account, network, IAM and the managed services around the app.

## Stay entirely if

- You need the Heroku developer experience indefinitely and will not fund the platform layer the Developer workflow section describes.

## Timeline

Shape: Full cutover: one migration window. Stage order: provision the AWS environment, migrate the database inside the migration window, then cut over every app in that same window. Duration drivers: a small estate (two services) and a Multi-AZ database. The cutover procedure stays in the migration guide; this is not a staffed schedule.

## Developer workflow

Developer workflow priority was not rated critical in Clarify.

| Heroku today                        | On AWS                                                          | Status                                                         | Your estate                         |
| ----------------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------- | ----------------------------------- |
| `git push heroku main` + buildpacks | CI builds a container image and deploys it to Elastic Beanstalk | **Will be generated** — a deploy workflow per app              | 1 buildpack app on Beanstalk        |
| Pipelines and promote               | Environments per stage with the same image promoted between them, approval-gated | **Will be generated** — an approval-gated `promote.yml` for the Beanstalk app with a generated deploy workflow | 1 app; no pipeline recorded          |
| Review apps                         | An ephemeral environment per pull request, torn down on merge   | **Build** (or buy)                                             | —                                   |
| Config vars                         | Parameter Store / Secrets Manager, injected at deploy           | **Covered** — bindings will be generated; you import the values | 1 app                              |
| `heroku run` / one-off dynos        | ECS Exec or `eb ssh`                                            | **Covered** — different command for the target                 | —                                   |
| `heroku logs --tail`                | CloudWatch Logs live tail                                       | **Covered**                                                    | —                                   |
| Release phase                       | A pre-deploy job in the workflow that runs before traffic shifts | **Build**                                                     | —                                   |
| Scheduler add-ons                   | EventBridge Scheduler                                           | **Covered** — schedules recreated by you; Generate emits no Terraform for the schedules themselves | 0 scheduler add-ons mapped, 0 deferred |
| `ps:scale`                          | Autoscaling policy or one CLI call                              | **Covered**                                                    | —                                   |
| Add-on marketplace                  | Each add-on becomes an AWS service wired by the Terraform that Generate will produce | **No equivalent** to the marketplace itself | 1 add-on mapped (Postgres), 0 deferred |

The rows marked Build are a platform layer your team owns: a deploy pipeline for Fargate, EKS and manual-deploy apps, a promote step for every app that gets no generated `promote.yml`, release steps, review-app automation, and a thin command wrapper. It is weeks of platform work, not months, and it is the same for every app.

## Top risks

| Risk                                                                                       | Impact | Likelihood | Mitigation                                                                                                                       |
| ------------------------------------------------------------------------------------------ | ------ | ---------- | -------------------------------------------------------------------------------------------------------------------------------- |
| The traffic pattern is not confirmed; a sustained always-on load would raise the compute estimate. | High   | Medium     | Confirm the dyno run pattern before cutover sizing; the Balanced figure assumes the current formation.                          |
| The maintenance window was left to the AWS default.                                        | Medium | Medium     | Choose a window at Generate; until then database patches and minor upgrades may land during business hours.                      |
| The database migration method defaulted to dump and restore.                               | Medium | Low        | Confirmed at Generate; dump and restore needs one downtime window sized to the 20 GB estimate — pick DMS if that window is too long. |

## What would flip this

- A confirmed always-on traffic pattern would raise the AWS compute estimate materially.

## What this assessment rests on

| Setting                          | Assumed value                              | Design consequence                                                                                                       |
| -------------------------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| Maintenance window               | Flexible (AWS default)                     | Database and Beanstalk maintenance happen in the AWS default window; asked for real at Generate.                         |
| Database migration method        | Dump and restore                           | One downtime window during cutover; the migration guide documents the dump and restore procedure. Asked for real at Generate. |
| Elastic Beanstalk deploy method  | GitHub Actions                             | A deploy workflow and an approval-gated promote step are generated for the Beanstalk app. Asked for real at Generate.    |
| Container registry               | Amazon ECR                                 | Images are published to one ECR repository (`ecr.tf`), which the Cloud Native Buildpacks path requires.                                            |
| Containerization method          | Cloud Native Buildpacks (Heroku builder)   | Images are built from the same source with the Heroku builder; no Dockerfile is needed.                                  |
| AWS Activate status              | Unknown                                    | The credits guidance stays neutral; no tier or amount is claimed.                                                        |

Confidence: medium — some material inputs assumed (the maintenance window and the migration method are defaults until Generate confirms them). Region, availability, database HA, compute target and the migration approach were confirmed by you; the containerization status was extracted from your Heroku inventory.

Estimates based on cached AWS pricing (us-east-1 cache), accuracy ±5–10%.

---

**Ready to execute?** Say "generate the Terraform and migration scripts" and I'll produce the full execution pack (Terraform, migration scripts, MIGRATION_GUIDE.md) from this same analysis. This decision report was generated without execution artifacts; the full migration report replaces it if you proceed.

_Draft for review._
