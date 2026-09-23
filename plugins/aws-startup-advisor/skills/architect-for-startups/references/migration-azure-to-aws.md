# Migration Azure to AWS — Startup-Specific Guidance

## Why Startups Migrate from Azure to AWS

1. **AWS credits** — Activate Accelerate / startup program credits are often larger than Azure equivalents
2. **Team hires** — new engineers know AWS, not Azure
3. **Ecosystem** — most SaaS integrations, tutorials, and community support default to AWS
4. **Specific service** — need Bedrock, DynamoDB, Lambda ecosystem, or other AWS-specific capabilities

## Startup Migration Decision Framework

### Don't Migrate If:

- You have >$50K in remaining Azure credits with no AWS credits
- Your codebase has deep Azure SDK dependencies (>6 months to untangle)
- You're pre-PMF — migration is a distraction from finding product-market fit
- Only reason is "AWS is more popular" — that's not a technical reason

### Do Migrate If:

- AWS credits significantly exceed remaining Azure credits
- Team is growing and candidates know AWS (hiring signal)
- Hitting Azure service limitations your product needs to overcome
- Want to consolidate on one cloud (already using some AWS)

## Startup-Specific Migration Gotchas

### Azure AD (Entra ID) — Skip the Full Migration

Enterprise migrations map Azure AD → IAM Identity Center. Startups should NOT:

- Migrate complex Conditional Access policies (rebuild from scratch with simpler IAM)
- Migrate Azure AD B2C to Cognito (re-auth your 50 users, it's faster than migrating)
- Worry about PIM → IAM equivalent (you don't need PIM at 5 engineers)

**Startup approach**: Set up IAM Identity Center fresh. Re-invite your 3-10 team members. Total time: 1 hour.

### Cosmos DB — Don't Over-Think It

Enterprise guide says "Cosmos DB maps to 4+ services depending on API." For startups:

- If you use Cosmos DB Core (SQL API) → DynamoDB. Just port the queries.
- If you have <10GB of data → export JSON, import to DynamoDB. Done in a day.
- If you use MongoDB API → DocumentDB OR just DynamoDB (simpler, cheaper at startup scale)

### Azure App Service → What to Choose on AWS

| Your Situation                   | Choose                         | Why NOT the complex option         |
| -------------------------------- | ------------------------------ | ---------------------------------- |
| Simple web app, <1K daily users  | ECS Express Mode               | Don't need full ECS/EKS complexity |
| API with background jobs         | Lambda + SQS                   | Don't need always-on compute       |
| Need deployment slots equivalent | ECS with CodeDeploy blue/green | Built-in blue/green support        |
| Team has container experience    | ECS Fargate                    | Don't need Kubernetes              |

### Azure Functions → Lambda

Straightforward except:

- **Durable Functions** → Step Functions (different programming model — budget 1-2 weeks to rewrite orchestrations)
- **Bindings** → Replace with explicit SDK calls. Budget 1-2 days per function with complex bindings.
- **Timer triggers** → EventBridge Scheduler + Lambda (easy, 30 min per function)

## Startup Migration Execution Plan

### The "Weekend Migration" (< 10 Azure resources, < 5GB data)

1. Friday: Set up AWS account, IAM Identity Center, basic networking
2. Saturday: Deploy compute (Lambda/ECS Express Mode/Fargate), migrate database (export/import)
3. Sunday: DNS cutover, smoke test, keep Azure running for 1 week as rollback
4. Following Friday: Delete Azure resources

### The "Sprint Migration" (10-50 Azure resources, production traffic)

1. Week 1: Set up AWS foundation (accounts, networking, CI/CD)
2. Week 2: Deploy and validate in AWS (parallel running)
3. Week 3: Gradual traffic shift (Route 53 weighted routing)
4. Week 4: Decommission Azure (keep backups for 30 days)

## Cost Comparison Traps

| Azure Feature               | Looks Equivalent To       | But Watch Out For                                                                     |
| --------------------------- | ------------------------- | ------------------------------------------------------------------------------------- |
| Azure App Service free tier | ECS Express Mode / Lambda | App Service F1 free tier is more generous — AWS has no equivalent free container tier |
| Cosmos DB serverless        | DynamoDB on-demand        | Cosmos RU pricing vs DynamoDB WCU/RCU doesn't map 1:1 — benchmark first               |
| Azure SQL Basic ($5/mo)     | RDS t4g.micro ($12/mo)    | AWS cheapest RDS is more expensive than Azure's cheapest SQL                          |
| Azure Functions (1M free)   | Lambda (1M free)          | Equivalent — Lambda is slightly more generous on compute-seconds                      |
