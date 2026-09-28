# API Gateway — Startup Decision Guide

## Stage-Based Recommendation

### Pre-Product-Market-Fit (Seed / <$1M ARR)

- **Use HTTP API exclusively**. It's 70% cheaper than REST API and faster to configure.
- Don't set up custom domains until you have paying customers. The default `execute-api` URL is ugly but free.
- Skip WAF until you have traffic worth protecting (~1000 RPM sustained). WAF minimum is ~$5/month + $1/million requests.

### Post-PMF / Growth ($1M-$10M ARR)

- Add custom domain when you have external API consumers or need stable URLs for partners.
- Add WAF when you see bot traffic or abuse patterns in logs.
- Consider REST API **only** if you now need request validation, API keys for usage plans (monetizing your API), or caching.

## Cost Traps

| Trap                            | Impact                                                         | Fix                                                                                        |
| ------------------------------- | -------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| REST API "just in case"         | 3.5x cost vs HTTP API ($3.50 vs $1.00 per million)             | Start HTTP API, migrate only specific routes that need REST features                       |
| Uncached Lambda authorizer      | Authorizer invoked on EVERY request — doubles your Lambda bill | Set 300s TTL cache; a user making 20 requests/min triggers 1 authorizer call instead of 20 |
| 4xx from bad clients            | You still pay for invalid requests                             | Add rate limiting early; monitor 4xx rate                                                  |
| REST API caching left on unused | $14.40/month minimum (0.5GB cache) even with zero hits         | Only enable caching on routes with >100 RPM and cacheable responses                        |

## Counterintuitive Advice

- **Don't add API Gateway at all if you're using a single Lambda behind CloudFront.** Lambda function URLs are free and CloudFront handles caching/custom domains. API Gateway adds cost with no value for simple cases.
- **Skip request validation in API Gateway.** Validate in your Lambda instead — it's easier to test, debug, and change. API Gateway validation errors produce cryptic messages for your API consumers.
- **The 29-second timeout is actually your friend.** If you're hitting it, your architecture is wrong. Use it as a forcing function to move to async patterns (SQS + webhook) which scale better anyway.

## When to Graduate from HTTP API to REST API

Trigger ANY of these:

- You need to monetize your API with usage plans and API keys for billing
- You need WAF integration (bot protection, geo-blocking, rate limiting by IP)
- You need request body validation at the gateway level (compliance requirement)
- You have >50 routes and need VTL transforms to avoid Lambda invocations on simple mappings

If none apply at $10M ARR, you probably never need REST API.
