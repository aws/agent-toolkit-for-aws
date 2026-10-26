# Observability Setup

Set up logging, tracing, and monitoring for your AgentCore agent.

## What's auto-enabled

For **deployed** agents (`agentcore deploy` + invoke), AgentCore automatically enables:

- **X-Ray tracing** — every invocation generates a trace
- **CloudWatch logging** — agent logs ship to CloudWatch
- **CloudWatch Transaction Search** — `agentcore deploy` turns it on for the target account and region if it isn't already (best-effort: if it can't, deploy prints `skipping Transaction Search: ...` and continues). Opt out globally with `agentcore config transactionSearch false`. Without it, spans are ingested but not searchable, so `agentcore traces ... list` and `agentcore eval` commands return nothing.

AgentCore Runtime auto-instruments the deployed agent, so you don't need to configure OTEL exporters in your code — but the OTEL distro must be in your dependencies (`aws-opentelemetry-distro` for Python; the CLI's Python templates already include it). A runtime with `"instrumentation": { "enableOtel": false }` in `agentcore/agentcore.json` opts out.

**Harnesses** (`agentcore add harness`) are fully managed — there's no code to instrument; use the `harness` forms of the `logs` and `traces` commands below.

**Locally** (`agentcore dev`), traces don't go to CloudWatch. The dev server starts an in-process OTLP collector and points the agent's OTEL SDK at it (OTLP endpoint and service-name env vars). Traces are written to `agentcore/.cli/traces/otlp/` and shown in the Agent Inspector:

```bash
agentcore dev --mode browser          # Agent Inspector web UI, including traces
agentcore dev --no-traces             # turn local trace collection off
```

For Python CodeZip runtimes the dev server injects the OTEL auto-instrumentation via `PYTHONPATH` (so uvicorn's reloaded workers are traced too). If it prints "OTEL auto-instrumentation is not installed in the agent environment", add `aws-opentelemetry-distro` to the runtime's dependencies.

## Ensuring logs appear in CloudWatch

Three things must be true for logs to appear:

### 1. OTEL entrypoint wrapper in Dockerfile

Your Dockerfile CMD must use the OpenTelemetry wrapper:

```dockerfile
CMD ["opentelemetry-instrument", "python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

For CodeZip builds, this is handled automatically. For Container builds, you must add it (the `agent-python-strands-container` template's Dockerfile already does).

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

If you bring your own role with `executionRoleArn` on the runtime in `agentcore.json`, make sure it includes these.

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

Traces show the full execution path of one agent invocation — model calls, tool calls, and timing. Run these from the project directory; `--name` can be omitted when the project has only one Runtime (or harness).

```bash
# List recent traces (default window: last 12h, 20 traces)
agentcore traces runtime list --name <RuntimeName> --since 1h --limit 10

# Download a specific trace's records to a JSON file (default: <traceId>.json)
agentcore traces runtime get <traceId> --name <RuntimeName> --output trace.json

# Harness equivalents
agentcore traces harness list --name <HarnessName>
agentcore traces harness get <traceId> --name <HarnessName>
```

Add `--target <name>` for a non-default deployment target and `--qualifier <endpoint>` for a non-default endpoint.

**Trace delay:** Traces appear **~10 seconds** after invocation (previously 30–60s). Don't panic if they're not immediate, and don't bake longer waits into scripts — older skills and docs that say "30–60 seconds" or "2–5 minutes" are stale.

## Viewing logs

```bash
# Search recent logs
agentcore logs runtime --name <RuntimeName> --since 30m

# Follow new log records
agentcore logs runtime --name <RuntimeName> --tail

# Filter by level
agentcore logs runtime --name <RuntimeName> --level error --since 1h

# CloudWatch Logs filter pattern
agentcore logs runtime --name <RuntimeName> --query "timeout" --since 2h

# Harness logs
agentcore logs harness --name <HarnessName> --since 30m
```

Online-eval results have their own log stream — see `agentcore eval online-eval logs` in [`references/evals.md`](evals.md).

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
4. **Deploy AgentCore agents in the source accounts with observability enabled** — same default OTEL setup as single-account. No code changes needed.
5. **View from the monitoring account.** AgentCore Observability in the CloudWatch console now shows data from all linked accounts side-by-side, identified by source account ID.

**Order-of-operations trap:** if you deploy agents in source accounts *before* linking, the telemetry still flows correctly — it just won't be visible from the monitoring account until the link is active. You don't need to redeploy, just wait a few minutes after linking.

**Traces:** cross-account trace viewing uses X-Ray's existing cross-account sharing model. If the CloudWatch cross-account link is set up correctly for Logs and Metrics but traces don't show, check X-Ray's cross-account config separately.

**IAM:** no extra IAM on the agent execution roles for cross-account observability. The cross-account feature operates at the CloudWatch/X-Ray layer, not at the source of the telemetry.

See [cross-account observability](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-cross-account.html) for the current console flow and edge cases.

## Cross-references

- If logs aren't appearing at all, check the three requirements above or use `agents-debug`
- For production observability setup, see `agents-harden`
- For measuring agent quality (not just operational health), load [`references/evals.md`](evals.md)
