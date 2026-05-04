# Observability Setup

Set up logging, tracing, and monitoring for your AgentCore agent.

## What's auto-enabled

AgentCore automatically enables:

- **X-Ray tracing** — every invocation generates a trace
- **CloudWatch logging** — agent logs ship to CloudWatch

These are on by default whether you're running **deployed** (`agentcore deploy` + invoke) or **locally** (`agentcore dev`). The dev server auto-instruments your agent with the AWS OpenTelemetry distro the same way the deployed runtime does; opt out with `agentcore dev --no-traces`.

Two prerequisites for the local path to work end-to-end:

1. **AWS credentials available locally** — the OTEL exporter needs them to ship spans.
2. **CloudWatch Transaction Search is enabled on the account** (one-time setup per account) — see "Viewing traces" below. Without it, spans are ingested but not searchable, so `agentcore traces list` and `agentcore run eval --session-id` return empty.

After deploy, AgentCore Runtime also auto-instruments the container (the default CMD wraps the app with `opentelemetry-instrument`). You don't need to configure OTEL in your code for either path — but you do need your agent code to be instrumented correctly.

## Ensuring logs appear in CloudWatch

Three things must be true for logs to appear:

### 1. OTEL entrypoint wrapper in Dockerfile

Your Dockerfile CMD must use the OpenTelemetry wrapper:

```dockerfile
CMD ["opentelemetry-instrument", "python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

For CodeZip builds, this is handled automatically. For Container builds, you must add it.

### 2. IAM permissions for CloudWatch and X-Ray

Your runtime execution role needs:

```json
{
  "Effect": "Allow",
  "Action": [
    "logs:CreateLogGroup",
    "logs:CreateLogStream",
    "logs:PutLogEvents",
    "xray:PutTraceSegments",
    "xray:PutTelemetryRecords"
  ],
  "Resource": "*"
}
```

### 3. Use the `logging` module, not `print()`

AgentCore captures structured logs via the Python `logging` module. `print()` statements go to stdout but are not captured by the OTEL pipeline.

```python
import logging
logger = logging.getLogger(__name__)

# Good — captured by CloudWatch
logger.info("Processing request", extra={"session_id": session_id})

# Bad — not captured
print(f"Processing request {session_id}")
```

## Viewing traces

Traces show the full execution path of one agent invocation — model calls, tool calls, and timing.

```bash
# List recent traces
agentcore traces list --runtime <AgentName> --since 1h --limit 10

# Get a specific trace
agentcore traces get <traceId> --runtime <AgentName>
```

**Trace delay:** Traces appear **~10 seconds** after invocation (previously 30–60s). Don't panic if they're not immediate, and don't bake longer waits into scripts — older skills and docs that say "30–60 seconds" or "2–5 minutes" are stale.

Also verify **Transaction Search** is enabled in CloudWatch — this is a prerequisite for trace visibility in the console.

## Viewing logs

```bash
# Stream recent logs
agentcore logs --runtime <AgentName> --since 30m

# Filter by level
agentcore logs --runtime <AgentName> --level error --since 1h

# Search for specific text
agentcore logs --runtime <AgentName> --query "timeout" --since 2h
```

## CloudWatch dashboard

For production agents, set up a CloudWatch dashboard with:

- Invocation count and error rate
- P50/P90/P99 latency
- Memory and CPU utilization
- Error log count by type

These metrics are available in the `AWS/BedrockAgentCore` namespace after deploy.

## Multi-account observability

If your agents are spread across accounts (typical setup: separate prod / staging / dev accounts), use **CloudWatch cross-account observability** to view metrics, traces, and logs from one central monitoring account.

The setup order matters — do it in this sequence or the console won't show source-account data:

1. **Pick a monitoring account.** This is where you'll view everything. Often a central observability account, not a workload account.
2. **Configure the monitoring account first.** CloudWatch console → Settings → Monitoring account configuration → Configure. Choose which telemetry types to share (enable Metrics **and** Logs — traces go through X-Ray's own cross-account mechanism).
3. **Link each source account.** Either via AWS Organizations (if your accounts are in one) or via individual linking. Source accounts must accept the link.
4. **Deploy AgentCore agents in the source accounts with observability enabled** — same default OTEL wrap-up as single-account. No code changes needed.
5. **View from the monitoring account.** AgentCore Observability in the CloudWatch console now shows data from all linked accounts side-by-side, identified by source account ID.

**Order-of-operations trap:** if you deploy agents in source accounts *before* linking, the telemetry still flows correctly — it just won't be visible from the monitoring account until the link is active. You don't need to redeploy, just wait a few minutes after linking.

**Traces:** cross-account trace viewing uses X-Ray's existing cross-account sharing model. If the CloudWatch cross-account link is set up correctly for Logs and Metrics but traces don't show, check X-Ray's cross-account config separately.

**IAM:** no extra IAM on the agent execution roles for cross-account observability. The cross-account feature operates at the CloudWatch/X-Ray layer, not at the source of the telemetry.

See [cross-account observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-cross-account.html) for the current console flow and edge cases.

## Cross-references

- If logs aren't appearing at all, check the three requirements above or use `agents-debug`
- For production observability setup, see `agents-harden`
- For measuring agent quality (not just operational health), load [`references/evals.md`](evals.md)
