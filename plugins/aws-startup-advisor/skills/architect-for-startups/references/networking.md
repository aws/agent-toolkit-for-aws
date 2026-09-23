# Networking — Startup Decision Guide

## Stage-Based Recommendation

### Pre-PMF (Seed / <$1M ARR)

- **Single NAT Gateway is fine.** The HA argument ($32/month per NAT Gateway × 3 AZs = $97/month) doesn't matter when your revenue is zero and downtime during an AZ failure costs you nothing in SLA penalties.
- **2 AZs, not 3.** You don't need 99.99% availability. 2 AZs gives you 99.95% and costs 33% less in NAT Gateways and other AZ-distributed resources.
- **Skip VPC entirely if you can.** Lambda, DynamoDB, S3, API Gateway — all work without VPC. Only add VPC when you need RDS, ElastiCache, ECS, or EC2.
- **If you must VPC:** Use the CDK/CF starter template with /16 CIDR, 2 AZs, 1 NAT Gateway. Don't bikeshed on CIDR planning until you need multi-VPC.

### Post-PMF / Growth ($1M-$10M ARR)

- Expand to 3 AZs when you have SLA commitments to customers.
- Add NAT Gateway per AZ when a single AZ failure would breach your SLA.
- Start planning CIDR allocation only when you need a second VPC (staging/prod split or microservice isolation).

### Scale ($10M+ ARR)

- Transit Gateway when you hit 3+ VPCs.
- Centralized egress through shared services VPC.
- This is when you hire a network engineer.

## Cost Traps

| Trap                          | Impact                                                                                            | Fix                                                                                                                                                             |
| ----------------------------- | ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| NAT Gateway data processing   | $0.045/GB — invisible tax on ALL traffic from private subnets to internet or AWS services         | Add S3 + DynamoDB gateway endpoints (free). Add interface endpoints for services with >1GB/month traffic ($7.20/month per endpoint per AZ vs $0.045/GB via NAT) |
| 3 NAT Gateways in dev/staging | $97/month × number of non-prod environments                                                       | 1 NAT Gateway for all non-prod. Accept the AZ risk.                                                                                                             |
| VPC endpoints "just in case"  | $7.20/month per endpoint per AZ — 10 endpoints in 3 AZs = $216/month                              | Only add interface endpoints when the NAT Gateway data processing cost for that service exceeds the endpoint cost. Breakeven: ~160GB/month per service.         |
| Unused Elastic IPs            | $3.60/month per unattached EIP (post-Feb 2024: $3.60/month for ALL public IPs including attached) | Audit monthly. Each public IPv4 costs money whether used or not.                                                                                                |
| VPC for serverless workloads  | NAT Gateway cost for Lambda/ECS calling AWS services                                              | Use VPC endpoints or keep serverless outside VPC entirely                                                                                                       |

## Counterintuitive Advice

- **Don't follow the "3 AZs, 3 tiers" best practice until Series B.** That's 9 subnets minimum. For a seed-stage startup, 2 AZs with public + private subnets (4 subnets total) is correct. You can add the third AZ in 30 minutes when you need it.
- **VPC endpoints have a breakeven point.** An interface endpoint costs $7.20/month/AZ. NAT Gateway processes data at $0.045/GB. If a service sends <160GB/month through NAT, the endpoint costs MORE than the NAT data processing. Only add interface endpoints when the math works (except for security-isolated subnets where there's no NAT alternative).
- **NAT Gateway is your biggest hidden cost.** A startup running ECS in private subnets pulling Docker images from ECR can easily spend $50-100/month just on NAT data processing for image pulls alone. Add ECR VPC endpoints early.
- **"No VPC" is a valid architecture.** API Gateway → Lambda → DynamoDB with IAM auth requires zero networking. Many startups don't need VPC until they add RDS or Redis.

## VPC Endpoint Decision Framework

Add these FREE endpoints always (zero cost):

- S3 Gateway Endpoint
- DynamoDB Gateway Endpoint

Add these PAID endpoints when math justifies (each $7.20/month/AZ):

| Endpoint          | Add when...                                                                            |
| ----------------- | -------------------------------------------------------------------------------------- |
| ecr.api + ecr.dkr | Running containers in private subnets (saves ~$5-20/month in NAT data for image pulls) |
| logs              | Sending >160GB/month of logs from private subnets                                      |
| secretsmanager    | Running in isolated subnets (no NAT alternative)                                       |
| sts               | Running in isolated subnets                                                            |

## When to Graduate from Simple to Complex Networking

| Trigger                         | Action                                           |
| ------------------------------- | ------------------------------------------------ |
| First SLA commitment (99.9%)    | Add 3rd AZ + NAT per AZ                          |
| NAT data processing >$100/month | Add interface endpoints for top traffic services |
| 3+ VPCs                         | Transit Gateway                                  |
| SOC2/HIPAA requirement          | Isolated subnets + VPC Flow Logs + all endpoints |
| Multi-region requirement        | CIDR planning, Transit Gateway Inter-Region      |

## Key Design Decisions

### Security Groups vs NACLs

- **Security groups are your primary network control.** They're stateful, allow-only, and evaluated together.
- **NACLs are defense-in-depth only.** Stateless, ordered rules, allow+deny — harder to manage and debug.
- Reference security groups by ID (not CIDR) for inter-resource traffic. Chain them: ALB-sg → App-sg → DB-sg.
- One security group per logical role. Never use 0.0.0.0/0 on port 22/3389 in production — use Systems Manager Session Manager.

### VPC Peering (for 2-3 VPCs before Transit Gateway)

- Point-to-point only, not transitive (A↔B and B↔C does NOT mean A↔C)
- CIDRs must not overlap — plan allocation upfront
- Works cross-region and cross-account

### Route53

- **Public hosted zone** for internet-facing DNS. NS records must be at your registrar.
- **Private hosted zone** for internal service discovery (associated with VPCs, not resolvable from internet).
- Always attach health checks to failover and latency routing records.
- Use Route53 + private hosted zones instead of hardcoding IPs. IPs change; DNS names persist.
