# Challenger — Startup-Specific Guidance

## Startup Challenge Framework

When challenging an architecture recommendation for a startup, apply these lenses in order:

### 1. The "Can You Operate This?" Test

For a team of N engineers, how many services require operational expertise?

| Team Size     | Max Operational Complexity                                           |
| ------------- | -------------------------------------------------------------------- |
| 1 engineer    | Fully managed services only (Lambda, DynamoDB, S3, ECS Express Mode) |
| 2-3 engineers | Managed services + 1 "complex" service (RDS, ECS Fargate)            |
| 4-7 engineers | Add ECS, custom networking, CI/CD pipelines                          |
| 8+ engineers  | Can consider EKS, multi-region, custom infrastructure                |

**If the proposed architecture exceeds the team's operational budget, it's wrong regardless of how "correct" it is technically.**

### 2. The "What If You Succeed?" Test

Challenge every architecture with: "If traffic 10x's next month, what breaks and what does it cost?"

Red flags:

- Architecture that requires manual intervention to scale (fixed EC2 instances without ASG)
- Architecture where cost is non-linear with traffic (NAT Gateway data charges, cross-AZ chatter)
- Architecture that requires re-architecture to scale (monolith on a single RDS instance with no read path)

### 3. The "What If Credits Expire Tomorrow?" Test

- Is the monthly cost sustainable on revenue alone?
- Are there Savings Plans or RIs purchased during credits that'll now cost real money?
- Is there over-provisioning that was "free" during credits but now costs $$$?

### 4. The "Simpler Alternative" Test

For every complex component proposed, name the simpler alternative and what you give up:

| Proposed                   | Simpler Alternative       | What You Lose                                | When It Matters                      |
| -------------------------- | ------------------------- | -------------------------------------------- | ------------------------------------ |
| EKS                        | ECS Fargate               | K8s ecosystem, Helm charts                   | Team already uses K8s                |
| Aurora Serverless v2       | RDS t4g.micro             | Auto-scaling, storage auto-growth            | >$50/mo in DB costs                  |
| Step Functions             | Lambda calling Lambda     | Visual debugging, built-in retries           | Workflows >3 steps                   |
| EventBridge + SNS + SQS    | Direct Lambda invocations | Decoupling, replay, fan-out                  | >2 consumers or need replay          |
| Multi-region active-active | Single region + backups   | <5 min recovery in regional failure          | 99.99%+ SLA required                 |
| Microservices              | Modular monolith          | Independent deployment, language flexibility | Team >5 AND clear service boundaries |

### 5. The "Premature Optimization" Detector

Challenge if you see ANY of these in a pre-PMF architecture:

- Multi-region anything
- Kubernetes
- Data lake / data warehouse
- Event sourcing
- CQRS
- Service mesh
- Custom observability platform (use CloudWatch)
- Multi-account beyond prod/dev split
- More than 3 microservices

Each of these is valid at scale. None of them are valid before product-market fit.

## Startup Challenger Verdict Scale

| Verdict       | Meaning                                                                           |
| ------------- | --------------------------------------------------------------------------------- |
| **SHIP IT**   | Architecture matches stage, team, and budget. Go.                                 |
| **SIMPLIFY**  | Right direction, but over-engineered for current stage. Remove components.        |
| **RETHINK**   | Fundamental mismatch between architecture complexity and team/stage/budget        |
| **DANGEROUS** | Architecture has a cost cliff, operational burden, or security gap that will hurt |
