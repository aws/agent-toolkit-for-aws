# Step Functions — Startup Decision Guide

## Stage-Based Recommendation

### Pre-PMF (Seed / <$1M ARR)

- **Don't use Step Functions for simple workflows.** If your flow is "Lambda A → Lambda B → Lambda C" with basic error handling, just chain them in code. Step Functions adds ASL complexity and $0.025/1000 transitions overhead.
- **Use Step Functions when:** You have human approval steps, waiting (hours/days for callbacks), complex branching, or need visual debugging of multi-step processes.
- **Express workflows for high-volume data processing** where you'd otherwise write a Lambda orchestrator.

### Post-PMF / Growth ($1M-$10M ARR)

- Step Functions becomes valuable when you have business-critical workflows that need auditability (payment processing, order fulfillment, onboarding flows).
- Replace homegrown state machines (status columns in databases, Lambda chains with SQS in between) with Step Functions when debugging them takes more than 30 minutes.

## Cost Traps

| Trap                                    | Impact                                                                                                                        | Fix                                                                                    |
| --------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| Standard for high-volume short tasks    | At 100K executions/day × 10 transitions = 1M transitions = $25/day = $750/month                                               | Switch to Express ($1.00/million requests + duration — typically 90% cheaper at scale) |
| Pass states "for clarity"               | Each Pass counts as a billed transition in Standard                                                                           | Eliminate unnecessary Pass states; combine logic                                       |
| Lambda wrapper for AWS SDK calls        | Pay Lambda invocation ($0.20/million) + transition ($25/million) instead of just transition                                   | Use direct SDK integrations (200+ supported services)                                  |
| Standard workflows for cron jobs        | Paying per-transition for scheduled tasks with no need for execution history                                                  | Use EventBridge Scheduler → Lambda directly                                            |
| Not setting TimeoutSeconds on callbacks | Execution stays open for up to 1 YEAR — you pay nothing per-se but accumulate orphaned executions that hit concurrency limits | Always set TimeoutSeconds on `.waitForTaskToken`                                       |

## Counterintuitive Advice

- **A Lambda function with try/catch is often better than Step Functions for 2-3 step workflows.** The overhead of learning ASL, managing IAM for Step Functions, and the state machine definition doesn't pay off until you have branching, parallel execution, or wait states.
- **Express workflows are underused by startups.** If you're writing a Lambda that orchestrates 3 other Lambdas and you're spending time on error handling — Express workflow does this natively at lower cost for short (<5 min) flows.
- **Distributed Map is free at low volume and massively valuable.** Processing 10K items in parallel with automatic batching and error handling — building this yourself in Lambda takes weeks.
- **Don't use Workflow Studio in production pipelines.** Great for prototyping, but export to ASL JSON and version control it. Console-only workflows are undocumented infrastructure.

## Decision Framework: Should You Use Step Functions?

**Yes, clearly worth it:**

- Workflow has wait states (human approval, callback patterns, timers)
- 5 steps with complex branching/parallel execution
- You need visual execution history for debugging/auditing
- Saga pattern with compensating transactions
- Processing large datasets (Distributed Map)

**Probably not worth it:**

- Linear A→B→C with basic retry (just use Lambda with try/catch)
- Simple cron job (use EventBridge Scheduler → Lambda)
- Request/response within API latency budget (Step Functions adds 50-200ms overhead)
- You have 1-2 engineers and nobody knows ASL (learning curve vs shipping speed)

**Express vs Standard decision:**

- <5 min duration AND >1000 executions/day → Express
- Need execution history in console → Standard
- Long-running (>5 min) → Standard (no choice)
- Cost-sensitive high-volume → Express (calculate breakeven: ~50 transitions/execution = equal cost)

## When to Graduate

| Trigger                                             | Action                                      |
| --------------------------------------------------- | ------------------------------------------- |
| Debugging Lambda chains takes >30min                | Wrap in Step Functions for visual debugging |
| You built a status column state machine in DynamoDB | Replace with Step Functions                 |
| Processing >10K items in batch jobs                 | Use Distributed Map                         |
| Compliance requires workflow audit trail            | Standard workflows (full execution history) |
| >100K executions/day on Standard                    | Evaluate Express for cost savings           |
