# Well-Architected — Startup Lens

## The Startup Well-Architected Trade-off

AWS Well-Architected assumes you optimize all 6 pillars simultaneously. Startups can't. Here's the priority order by stage:

### Pre-Seed Priority Stack

1. **Cost Optimization** — you die if you run out of money
2. **Security** — but ONLY: no public data exposure, no hardcoded creds, basic IAM
3. **Performance** — just "fast enough" for the user experience
4. ~~Operational Excellence~~ — you ARE the operations team
5. ~~Reliability~~ — single-AZ is fine, manual recovery is fine
6. ~~Sustainability~~ — irrelevant at this stage

### Seed Priority Stack

1. **Security** — first customer data means you can't leak it
2. **Cost Optimization** — credits are running out or gone
3. **Reliability** — first SLA commitments need basic redundancy
4. **Performance** — user expectations rise with a real product
5. **Operational Excellence** — basic CI/CD, basic monitoring
6. ~~Sustainability~~ — still not the priority

### Series A+ Priority Stack

All 6 pillars matter. Use the standard Well-Architected framework. But still weight Cost and Security highest — board reporting requires cost visibility, and enterprise customers require security posture.

## Startup-Specific "High Risk" Redefinitions

Standard WA rates these as HRI (High Risk Issue). For pre-seed startups, they're actually acceptable:

| Standard HRI         | Startup Reality                                        | Acceptable Until                                            |
| -------------------- | ------------------------------------------------------ | ----------------------------------------------------------- |
| Single-AZ database   | Fine — manual restore from backup if AZ fails          | First paying customer with SLA                              |
| No multi-region DR   | Fine — total regional failure is extremely rare        | >$100K ARR or compliance requires it                        |
| Manual deployments   | Fine — you're deploying 10x/day, a simple script works | Team >3 engineers                                           |
| No runbooks          | Fine — you wrote the code, you know how to fix it      | Team >5 or on-call rotation starts                          |
| No chaos engineering | Absurd at this stage                                   | Team >10 and production stability is a customer requirement |

## Startup-Specific ACTUAL High Risk Issues (any stage)

These are genuinely dangerous regardless of stage:

| Issue                               | Why It Kills Startups                      | Fix Time                     |
| ----------------------------------- | ------------------------------------------ | ---------------------------- |
| Public S3 bucket with customer data | Data breach = company-ending event         | 5 minutes                    |
| IAM user access keys in git         | Same                                       | 30 minutes (rotate + remove) |
| No backups of primary database      | Corruption/deletion = game over            | 15 minutes to enable         |
| Root account without MFA            | Account takeover = everything lost         | 5 minutes                    |
| No cost alerts                      | $10K surprise bill eats 2 months of runway | 10 minutes                   |

## Minimum Viable Well-Architected (Pre-Seed Checklist)

Instead of 50+ WA review questions, pre-seed startups need exactly these:

```
□ S3 Block Public Access enabled (account-level)
□ No IAM users with console passwords or access keys (use SSO or IAM Identity Center)
□ RDS/DynamoDB backups enabled (default retention is fine)
□ Root account has MFA
□ AWS Budget alert set at expected + 50%
□ CloudTrail default trail enabled (it is by default — don't disable it)
□ All secrets in SSM Parameter Store or Secrets Manager (never in code/env files committed to git)
```

That's it. Seven items. Everything else can wait.

## "When to Do a Full WA Review" Triggers

- Preparing for SOC2 audit
- First enterprise customer with security questionnaire
- Monthly spend > $10K (optimization has real ROI)
- Series A due diligence
- Post-incident (something broke in production affecting customers)
- Annual cadence once you're past Series A
