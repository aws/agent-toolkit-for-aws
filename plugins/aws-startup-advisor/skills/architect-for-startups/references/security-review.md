# Security Review — Startup-Specific Guidance

## Startup Security Tiers

Don't apply enterprise security to a pre-seed startup. Apply the RIGHT security for the stage:

### Tier 1: Non-Negotiable (All Stages, Day 1)

These take <1 hour combined and prevent company-ending events:

| Control                                | Why It's Non-Negotiable                                        | Effort                   |
| -------------------------------------- | -------------------------------------------------------------- | ------------------------ |
| S3 Block Public Access (account-level) | Public data breach = death                                     | 2 min                    |
| Root account MFA                       | Account takeover = everything lost                             | 5 min                    |
| No access keys in source code          | Leaked keys = crypto mining bills + data breach                | 10 min (use git-secrets) |
| Database backups enabled               | Data loss = start over                                         | 5 min (usually default)  |
| Budget alert at ceiling + 50%          | Surprise bill eats runway                                      | 10 min                   |
| TLS on all public endpoints            | API Gateway/CloudFront/ALB default to HTTPS — don't disable it | 0 min                    |

### Tier 2: First Paying Customer

| Control                               | Why Now                                          | Effort                     |
| ------------------------------------- | ------------------------------------------------ | -------------------------- |
| IAM Identity Center (not IAM users)   | Audit trail, no shared credentials               | 1-2 hours                  |
| Encryption at rest on databases       | Customer data protection, contractual            | Default on modern services |
| VPC for datastores (RDS, ElastiCache) | Network isolation for sensitive data             | 30 min if not already      |
| CloudTrail (default trail)            | Audit log — already on by default, DON'T disable | 0 min                      |
| Secrets in SSM/Secrets Manager        | No .env files, no hardcoded passwords            | 1-2 hours migration        |

### Tier 3: Enterprise Customer / SOC2 Prep

| Control                       | Why Now                                          | Effort                     |
| ----------------------------- | ------------------------------------------------ | -------------------------- |
| GuardDuty                     | Threat detection, SOC2 expects it                | 5 min to enable, $15-30/mo |
| Security Hub                  | Centralized findings, auditor-friendly           | 15 min, cost varies        |
| Config rules                  | Drift detection, compliance evidence             | Hours to tune properly     |
| VPC Flow Logs                 | Network audit trail                              | 5 min, $0.50/GB            |
| Custom KMS keys with rotation | Customer-managed encryption, compliance evidence | 30 min per key             |
| SCPs (multi-account)          | Prevent lateral damage                           | Hours to design properly   |

### Tier 4: Series B+ / Regulated Industry

Full enterprise security stack: Security Hub, custom Config rules, AWS Firewall Manager, automated remediation, security incident response playbook, penetration testing, etc.

## Startup Security Anti-Patterns

| Anti-Pattern                                | Why Startups Do It                | What to Do Instead                                                                                        |
| ------------------------------------------- | --------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Skip ALL security                           | "We'll add it later"              | Apply Tier 1. It takes 30 minutes. No excuses.                                                            |
| Apply ALL security                          | "We need to be enterprise-ready"  | You'll spend 2 weeks on security tooling nobody asked for. Apply your tier.                               |
| `AdministratorAccess` for app roles         | "We'll scope it later"            | At minimum, scope to the services you use. `s3:*`, `dynamodb:*` is bad but survivable. `*:*` is never ok. |
| Shared IAM users                            | "We only have 2 people"           | Use IAM Identity Center. It's free. Shared creds = no audit trail.                                        |
| Security groups: all traffic from 0.0.0.0/0 | "It works"                        | Allow only the ports your app uses. Takes 5 minutes.                                                      |
| No encryption because "it's just dev"       | Dev data often mirrors production | All modern AWS services default to encryption. Don't disable it.                                          |

## The "First Enterprise Deal" Security Checklist

When your first enterprise customer sends a security questionnaire, you need these ready:

```
□ Data encrypted at rest (all datastores)
□ Data encrypted in transit (TLS everywhere)
□ Access logging (CloudTrail enabled)
□ No shared credentials (IAM Identity Center or per-engineer roles)
□ Backup and recovery tested (restore a DB backup once)
□ Incident response plan (even a 1-page doc counts)
□ Penetration test completed (use AWS-approved vendor)
□ SOC2 Type I started (if SaaS) — takes 3-6 months
```

**Start SOC2 3-6 months BEFORE you think you'll need it.** Every startup we've seen regrets not starting earlier.

## IaC Security Checklist

When reviewing infrastructure code (CDK, Terraform, CloudFormation):

### IAM

- [ ] No `*` in Action or Resource (unless scoped with conditions)
- [ ] No inline policies on users — use roles and groups
- [ ] Cross-account access uses external ID
- [ ] Lambda execution roles scoped to specific log groups

### Networking

- [ ] No security groups with 0.0.0.0/0 on non-HTTP(S) ports
- [ ] Private subnets for databases and internal services
- [ ] NACLs as defense-in-depth, not primary control

### Data

- [ ] Encryption at rest enabled (S3, RDS, EBS, DynamoDB)
- [ ] S3 buckets: Block Public Access enabled, no public ACLs
- [ ] RDS: no public accessibility
- [ ] Secrets in Secrets Manager or SSM Parameter Store, never in code

## Cost of Security Controls

| Control                  | Monthly Cost                      | Startup Stage to Add                 |
| ------------------------ | --------------------------------- | ------------------------------------ |
| S3 Block Public Access   | $0                                | Day 1                                |
| IAM Identity Center      | $0                                | First hire                           |
| CloudTrail (default)     | $0 (first copy free)              | Day 1 (already on)                   |
| AWS-managed encryption   | $0                                | Day 1 (already on for most services) |
| GuardDuty                | $15-30/mo typical for startups    | First enterprise customer            |
| Security Hub             | $5-20/mo typical                  | SOC2 prep                            |
| Config rules (basic set) | $10-50/mo                         | SOC2 prep                            |
| VPC Flow Logs            | $0.50/GB stored                   | Enterprise customer requirement      |
| WAF                      | $5/mo + $1/rule + request charges | Public API under attack              |
