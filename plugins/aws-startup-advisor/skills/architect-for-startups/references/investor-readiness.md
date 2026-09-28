# Investor Readiness

## What Investors Actually Ask (and How to Answer)

### Seed Pitch: Speed + Capital Efficiency Story

**Template**:

> "We built on serverless AWS infrastructure that costs near-zero at current scale and grows linearly with users. Monthly cost is $X, credits give us Y months of runway before infra becomes a line item. Architecture handles 100x current load without changes."

**Don't say**: anything about Kubernetes, microservices, or complex architecture (signals over-engineering). Don't say "we'll need to rewrite at scale" (signals poor planning).

### Series A Pitch: Unit Economics + Reliability

Key metrics to have ready:

| Metric                           | Target               |
| -------------------------------- | -------------------- |
| Infra cost / active user / month | Decreasing over time |
| Deploy frequency                 | Daily or more        |
| Uptime (last 90 days)            | >99.5%               |
| Mean time to recovery            | <1 hour              |
| Infra cost as % of MRR           | <10% for SaaS        |

---

## Red Flags Investors Look For

| Red Flag                               | What It Signals                         |
| -------------------------------------- | --------------------------------------- |
| "We'll need to rewrite at scale"       | Poor planning, future capital sink      |
| Very high infra cost vs revenue        | Capital inefficiency                    |
| Single engineer who "knows everything" | Bus factor = 1                          |
| No uptime data                         | Operational immaturity                  |
| Over-engineered for current scale      | Wasted capital, slow shipping           |
| Vendor lock-in without rationale       | Strategic risk (acknowledge trade-offs) |

---

## How to Present AWS Costs to Investors

**Don't** show a raw AWS bill with 47 line items.

**Do** present in business terms:

```
Monthly Infrastructure: $X,XXX
├── Compute (API + background): XX%
├── Database: XX%
├── AI/ML (Bedrock): XX%
├── Storage + CDN: XX%
└── Other: XX%

Cost per active user: $X.XX/month
Cost as % of MRR: X%
Credits remaining: $XX,XXX (X months at current burn)
```

## Unit Economics Healthy Ranges (SaaS)

| Metric                                               | Healthy Range     |
| ---------------------------------------------------- | ----------------- |
| Infra cost per user                                  | $0.50-5.00/month  |
| Infra as % of revenue                                | 5-15%             |
| Gross margin (after infra COGS)                      | >70%              |
| Cost scaling factor (% infra growth / % user growth) | <1.0 (sub-linear) |

---

## Due Diligence Prep (Series A+)

Have these ready for technical DD:

1. One-page architecture diagram (components + data flow)
2. Scaling plan at 10x and 100x (ideally: "nothing changes" for serverless)
3. Honest list of single points of failure + mitigation plan
4. RTO/RPO targets
5. Technical debt acknowledgment + paydown plan
6. No single person is a blocker for any system
7. Historical cost trajectory + projection at target scale
