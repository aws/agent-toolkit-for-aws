# Free Tier

## July 2025 Transition

AWS transitioned from time-based to credit-based free tier on July 15, 2025:

| Account Type | Model | Details |
|-------------|-------|---------|
| Legacy (before July 15, 2025) | 12-month free tier + Always Free | Original offers, complete naturally. Always Free services available. |
| Free Plan (after July 15, 2025) | $200 credits for 6 months | No charges during free period. Upgrade to Paid Plan after. Always Free services available. |
| Paid Plan (after July 15, 2025) | $200 credits for 6 months | Charged for usage exceeding credits. Always Free services available. |

~30 Always Free services remain available indefinitely for all account types.

## Recommended Workflow

1. First: `aws freetier get-account-plan-state` — determine account type and eligibility
2. Then: `aws freetier get-free-tier-usage` — check current usage for active services

## Critical Rules

- NEVER cite specific free tier limits from training data — offers changed July 15, 2025 and vary by account type
- `getFreeTierUsage` only returns services with usage > 0. Missing service means either no free tier offer exists OR customer hasn't used it yet.
- For questions about available offers before using a service, direct to https://aws.amazon.com/free/
- Legacy accounts: former 12-month services stop appearing after their period expires
- Free Plan/Paid Plan: $200 credit replaced 12-month offers. Always Free services tracked individually.

```bash
# Check account plan state
aws freetier get-account-plan-state

# Check current free tier usage
aws freetier get-free-tier-usage
```
