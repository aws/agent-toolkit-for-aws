# Lambda — Startup-Specific Guidance

## When Lambda is the Right Default for Startups

**Pre-seed to Series A**: Lambda should be your default compute unless you have a reason not to use it.

- Zero cost at idle — you only pay when code runs. A startup with 10K requests/day pays ~$0.20/month.
- No infrastructure to manage during the "build fast, validate hypothesis" phase.
- AWS free tier: 1M requests + 400K GB-seconds/month — most early startups never exceed this.

**The inflection point**: Lambda becomes expensive relative to containers at ~$300-500/month in Lambda spend with predictable, sustained traffic. At that point, a single Fargate task running 24/7 is cheaper.

## Startup Cost Traps

1. **Provisioned Concurrency before you need it**: Costs ~$15/month per provisioned instance even with zero traffic. Don't enable until you have latency SLAs requiring <100ms p99 cold starts AND paying customers who need them.

2. **Memory over-allocation**: Startups often set 1024MB "to be safe." At low traffic this barely matters, but at scale the difference between 256MB and 1024MB is 4x cost. Benchmark with [AWS Lambda Power Tuning](https://github.com/alexcasalboni/aws-lambda-power-tuning) once you have real traffic.

3. **Step Functions standard workflows for high-volume**: Standard Workflows cost $25 per million state transitions. If you're processing events at volume, Express Workflows cost $1 per million (but max 5-min duration). Most startups should start with Standard and switch to Express when the bill surprises them.

4. **VPC-attached Lambda + NAT Gateway**: A NAT Gateway costs $32/month + data processing fees — often more than the Lambda itself for early startups. Use VPC endpoints ($7/month each) for S3 and DynamoDB, or keep Lambda outside the VPC entirely until you need private resource access.

## Counterintuitive Startup Advice

- **Monolith Lambda is fine at your stage.** The "anti-pattern" of one Lambda handling multiple routes via API Gateway is actually optimal for a 1-3 person team. Split functions when: (a) you have different scaling/memory needs per route, or (b) cold starts on a bloated package exceed your latency budget. Don't prematurely decompose.

- **Skip Powertools until you have production traffic.** Structured logging and tracing matter when debugging distributed systems at scale. At pre-product-market-fit, `console.log` and CloudWatch Logs Insights are sufficient. Add Powertools when you have >5 Lambda functions in production.

- **Python or Node.js, period.** Unless your team is exclusively Java/Go developers, the startup hiring pool and example ecosystem for Lambda skews heavily Python/Node. Pick one and standardize. Language choice is a one-way door at the team level.

## When to Graduate from Lambda

| Signal                                                           | What to Do                                        |
| ---------------------------------------------------------------- | ------------------------------------------------- |
| Monthly Lambda bill > $500 with predictable traffic              | Evaluate ECS Fargate — likely 40-60% cheaper      |
| P99 latency >2s due to cold starts on critical path              | Add Provisioned Concurrency OR move to containers |
| Functions exceeding 15-min timeout                               | Move to ECS tasks or Step Functions               |
| Team spending >20% of time on Lambda packaging/deployment issues | Consider containers for developer experience      |
| Need WebSockets, long-lived connections, or >6MB response bodies | Lambda is architecturally wrong — use containers  |

## Credits-Specific Guidance

- Lambda compute is covered by AWS Activate credits. During the credits period, don't optimize Lambda cost — optimize developer velocity instead. Over-provision memory, use Provisioned Concurrency liberally, etc.
- When credits expire, expect Lambda bills to be the first "surprise" because teams never optimized during the free period. Budget 2 weeks for Lambda cost optimization before credits run out.

## ARM64 (Graviton) — Just Do It

20% cheaper, often faster. No config change needed for Python/Node.js. Set `arm64` on every function from day one. The only reason not to: native binary dependencies compiled for x86 (rare for startups).
