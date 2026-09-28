# CloudFront — Startup Decision Guide

## Stage-Based Recommendation

### Pre-PMF (Seed / <$1M ARR)

- **Deploy CloudFront from day one for static assets.** It's effectively free at low traffic (1TB free tier) and gives you global performance without multi-region infrastructure.
- Skip WAF until you see abuse. WAF adds $5/month minimum + per-request costs.
- Use versioned filenames (`app.abc123.js`) from the start — never rely on invalidations.

### Post-PMF / Growth ($1M-$10M ARR)

- Add WAF when you have traffic worth protecting or compliance requirements.
- Add CloudFront in front of API Gateway only if you need geographic caching of API responses or need to combine static + API under one domain.
- Consider CloudFront Functions (not Lambda@Edge) for header manipulation — 1/6th the cost.

## Cost Traps

| Trap                            | Impact                                                                                       | Fix                                                                                                                              |
| ------------------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Invalidation as deploy strategy | Free only for first 1,000 paths/month, then $0.005/path. Daily deploys with `/*` = waste.    | Use content-hashed filenames. Zero invalidation cost.                                                                            |
| Lambda@Edge for simple tasks    | Charged per request + duration at 3x Lambda pricing                                          | Use CloudFront Functions for header manipulation, redirects, URL rewrites ($0.10/million vs $0.60/million)                       |
| Data transfer out to internet   | $0.085/GB after 1TB free tier — this is often the biggest line item for media-heavy startups | Enable compression (saves 60-80% on text), use appropriate image formats, consider S3 Transfer Acceleration only if upload-heavy |
| Origin Shield without need      | Additional caching layer at $0.0090/10K requests                                             | Only valuable if you have 3+ edge locations hitting origin frequently                                                            |

## Counterintuitive Advice

- **CloudFront in front of Lambda Function URLs is often better than API Gateway.** You get custom domains, caching, and WAF at CloudFront cost ($0.085/GB + $0.01/10K requests) instead of API Gateway cost ($1.00/million requests). For a startup doing 10M requests/month on small payloads: CloudFront = ~$10, HTTP API = $10, REST API = $35. But CloudFront gives you the caching layer for free.
- **Don't use edge-optimized API Gateway endpoints.** They silently create a CloudFront distribution you can't configure. Use regional + your own CloudFront if you need CDN.
- **The free tier (1TB/month transfer, 10M requests) is generous.** Most pre-PMF startups never exceed it. Don't optimize what costs you $0.

## When to Add CloudFront (if not already using it)

You're paying too much for origin compute/bandwidth when:

- Your origin (ALB, API Gateway, S3) data transfer exceeds $50/month
- You're serving the same API response to many users within a time window (cacheable)
- You need to serve users on multiple continents without multi-region deployment

## Configuration Decisions (Get These Right on Day 1)

### Origins

- Use **Origin Access Control (OAC)** — not the legacy Origin Access Identity (OAI). OAC supports SSE-KMS and all S3 features; OAI does not.
- For S3 static website hosting endpoints, use custom origin (not S3 origin type) — the website endpoint is HTTP-only.
- For API origins, use **CachingDisabled** managed policy unless you explicitly control TTLs and cache keys.
- Use **regional** API Gateway endpoints, not edge-optimized (avoids double CloudFront hop).

### Caching

- Forward only what the origin needs — extra headers/cookies/query strings destroy cache hit ratio. Use separate cache and origin request policies.
- Enable automatic compression (Gzip + Brotli) in cache behavior — saves 60-80% on text assets.

### Security

- ACM certificate must be in **us-east-1** for CloudFront. They're free and auto-renew.
- Add security response headers via response headers policy: HSTS, X-Content-Type-Options, X-Frame-Options.
- Never use self-signed certs with custom domains.

## Credits Consideration

CloudFront data transfer is covered by AWS Activate credits. If you have $100K in credits, don't optimize CloudFront costs — optimize for developer velocity instead. Revisit when credits are within 6 months of expiring.
