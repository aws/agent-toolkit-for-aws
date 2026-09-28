# IaC Scaffold — Startup-Specific Guidance

## When to Introduce IaC (Not Day 1 for Everyone)

| Stage                      | IaC Recommendation                                     | Why                                                                                  |
| -------------------------- | ------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| Pre-seed solo founder      | Skip IaC. Console + CLI.                               | You're iterating daily. IaC slows you down at this stage. Document what you clicked. |
| Pre-seed with 2+ engineers | Minimal IaC (CDK or Terraform for the main stack only) | Reproducibility matters when 2 people touch infra                                    |
| Seed                       | IaC required for production resources                  | You need a second environment and can't recreate from memory                         |
| Series A+                  | Everything in IaC, no exceptions                       | Audit trail, repeatability, team onboarding                                          |

## Framework Selection for Startups

| Factor                      | CDK (TypeScript)               | Terraform                                   | SAM                                     |
| --------------------------- | ------------------------------ | ------------------------------------------- | --------------------------------------- |
| Startup default             | ✅ If team writes TypeScript   | ✅ If multi-cloud possible or team knows it | ✅ If pure serverless (Lambda + API GW) |
| Learning curve for web devs | Low (it's TypeScript)          | Medium (new DSL)                            | Low (YAML + familiar)                   |
| Footgun risk                | Medium (generates complex CFN) | Low (explicit)                              | Low (simple scope)                      |
| Operational overhead        | Low (CDK CLI)                  | Medium (state management)                   | Lowest                                  |
| When to switch away         | Never needed for most startups | If going all-in AWS (CDK advantage)         | When you add non-serverless resources   |

**Opinionated startup default**:

- Pure serverless app → SAM (simplest, fastest iteration with `sam local`)
- Full-stack app → CDK in TypeScript (same language as your app, likely)
- Multi-cloud or Terraform-experienced team → Terraform

## Startup IaC Anti-Patterns

| Anti-Pattern                            | Why It Hurts                                            | Do This Instead                                                                          |
| --------------------------------------- | ------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| Separate repo for IaC                   | Context switching, drift between app and infra          | Monorepo: `/infra` next to `/src`                                                        |
| One stack per resource                  | Deployment takes forever, circular dependencies         | One stack per LIFECYCLE (stateful data, stateless compute, networking)                   |
| Custom constructs/modules before needed | Abstraction without understanding = debugging nightmare | Use L2 constructs (CDK) or official modules (Terraform). Write custom only on third use. |
| IaC for developer sandboxes             | Over-engineering for ephemeral environments             | `cdk deploy --context env=dev` with cheaper defaults, or just use console for scratch    |
| Parameterizing everything               | 50 parameters nobody understands                        | Hardcode sensible defaults. Parameterize only what CHANGES between environments          |

## Startup-Optimized Stack Separation

```
stack-1: foundation (VPC if needed, DNS zone, shared secrets)
  → Deploys once, changes rarely
  → Even for pre-seed: just DNS zone + maybe a VPC

stack-2: data (databases, S3 buckets, DynamoDB tables)
  → Deploys rarely, NEVER destroyed (data loss)
  → Enable deletion protection on everything here

stack-3: compute (Lambda functions, ECS services, API Gateway)
  → Deploys frequently (every PR merge)
  → Safe to destroy and recreate
```

**Key rule**: Never put databases and compute in the same stack. A botched compute deploy should never risk your data.

## Minimum Viable IaC for Startups

If you're scaffolding for the first time, include ONLY:

1. The compute + API layer
2. The data layer (separate stack)
3. A `Makefile` with: `deploy`, `destroy`, `diff`, `logs`
4. Environment config: `dev` and `prod` (not `staging`, `qa`, `perf`, etc.)

Skip until needed:

- CI/CD pipeline IaC (use GitHub Actions with `aws-actions/configure-aws-credentials` — simple YAML)
- Monitoring/alerting IaC (click 3 alarms in the console — faster than writing CDK for them)
- Multi-account bootstrap (until you actually have multiple accounts)
- Custom domains + ACM certs (until you need them for customers)
