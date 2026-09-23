# Customer Ideation — Startup-Specific Discovery

## Startup-Adapted Discovery Questions

Standard AWS discovery asks 40+ questions. Startups need a focused subset that reveals architecture-critical constraints fast.

### The 6 Questions That Actually Matter for Startup Architecture

1. **What's your monthly AWS budget ceiling?** (Not "what do you want to spend" — what kills you if you exceed it?)
2. **How many engineers will touch infrastructure?** (If answer is 0-1, eliminate anything requiring operational expertise)
3. **What's your team's technical profile?** (Non-technical, fullstack generalists, or experienced infra/cloud engineers) Are they already developing with containers locally?
4. **Do you have AWS credits? How much, when do they expire?** (Changes every capacity planning decision)
5. **What's your current traffic/data volume, and what's your 12-month optimistic projection?** (Design for 10x current, have a PATH to 100x)
6. **What's the one thing that, if it breaks, kills your company?** (This is what gets redundancy. Everything else gets the cheapest option)

### Follow-Up Questions by Answer Pattern

**If budget < $500/mo:**

- Serverless-only architecture. No discussion.
- Ask: "Are cold starts acceptable for your use case?" (determines Lambda vs ECS Express Mode)

**If team = 1-2 engineers:**

- Eliminate: EKS, self-managed databases, custom networking
- If they're already running containers locally → ECS Express Mode. Don't push them to Lambda and force a rewrite of what already works.
- If they're non-technical founders or have no container experience → Lambda or Amplify. Lowest operational surface area.

**If team is experienced engineers (previous startups, cloud-native background):**

- Don't dumb it down. They can handle ECS, IaC, and CI/CD from day one.
- Match the deployment model to how they already develop — containerized local dev should deploy as containers.
- Focus guidance on cost optimization and AWS-specific gotchas, not basic architecture patterns.

**If credits > $25K:**

- They'll try to over-build. Push back: "What's the plan when credits expire in [month]?"
- Ask: "Which parts of your architecture are experiments vs committed?" (experiments get throwaway infra)

**If "the thing that kills us" is data loss:**

- Backups + point-in-time recovery are non-negotiable even pre-seed
- Ask: "Is the data reconstructible from an external source, or is it uniquely generated?"

**If "the thing that kills us" is downtime:**

- Multi-AZ on the critical path component only (not everything)
- Ask: "How many minutes of downtime per month is actually acceptable?" (usually more than they think)

## Startup Ideation Anti-Patterns

- **"We need to be enterprise-ready from day 1"**: No. You need to be enterprise-ready when enterprises want to buy. Build the path, not the destination.
- **"We'll need multi-region for global users"**: How many global users do you have today? CloudFront + single region handles global reads. Multi-region is a Series B problem.
- **"We should use Kubernetes because we'll need it eventually"**: The migration from Fargate to EKS takes 2-3 weeks. The cost of running EKS before you need it is 6-12 months of unnecessary complexity.
- **"We need a data lake"**: You have 10GB of data. You need an S3 bucket and Athena. A "data lake" is a label you put on it later.

## Qualify the Workload for Startup Context

After discovery, classify:

| Classification                         | Architecture Approach                        | Budget Constraint      |
| -------------------------------------- | -------------------------------------------- | ---------------------- |
| **Experiment** (validating hypothesis) | Throwaway. Lambda + DynamoDB. No IaC needed. | < $50/mo               |
| **MVP** (first users testing)          | Simple but rebuildable. Basic IaC.           | < $200/mo              |
| **Product** (paying customers)         | Production-grade on critical path only       | < $2K/mo               |
| **Scale** (proven PMF, growing)        | Full Well-Architected applies                | Budget follows revenue |
