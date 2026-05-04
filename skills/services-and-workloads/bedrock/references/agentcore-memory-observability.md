# AgentCore Memory & Observability

## Table of Contents

- Memory Service
- Observability (AgentCore-Specific)

## Memory Service

Provides conversation state persistence for agents deployed on AgentCore Runtime.

### When to Enable

- Agents that need conversation context across multiple invocations (multi-turn chat)
- Agents that accumulate knowledge during a session
- Per-session lifecycle agents (see [runtime reference](agentcore-runtime.md))
- NOT needed for stateless per-request agents

### Runtime Integration

The key non-obvious behavior: Runtime passes session IDs to the Memory service automatically when configured. You don't call Memory directly from your agent code — Runtime handles the plumbing.

**Configuration:**

- Session TTL: how long sessions persist after last activity (default varies). Set to the minimum required for your use case — longer TTLs increase the window of exposure for sensitive conversation data
- Memory types: session memory (conversation history), semantic memory (long-term knowledge)
- Refer to the latest AWS documentation on AgentCore Memory service configuration for current options

### Common Failures

**Session not found (expired TTL):**
Session expired between invocations. Increase TTL or handle gracefully in agent logic.

**Session ID not passed from Runtime:**
Agent loses context between requests. Verify Memory service is enabled in Runtime configuration and the client passes `sessionId` in invocation requests.

**Memory capacity exceeded:**
Session has too much accumulated context. Configure memory capacity limits or implement context summarization in agent logic.

## Observability (AgentCore-Specific)

Only the AgentCore-specific parts — agents already know generic OTEL/CloudWatch patterns.

### Required Trace Attributes for Evaluations

This is the key non-obvious requirement. AgentCore Evaluations service reads specific OTEL trace attributes to score agent quality. Without these, Evaluations can't work.

**Required attributes:**

- Agent input (user query)
- Agent output (response)
- Tool calls (which tools were invoked, with inputs/outputs)
- Latency per step

**Instrumentation:**

- Use AWS Distro for OpenTelemetry (ADOT) collector
- You MUST use an IAM role (not access keys) for ADOT collector authentication — attach to the ECS task, EC2 instance profile, or pod service account
- You MUST NOT hardcode AWS credentials in ADOT collector configuration files
- Configure sampling rate for evaluation (not every invocation needs evaluation)
- Refer to the latest AWS documentation on AgentCore observability OTEL instrumentation for current attribute names and collector configuration

### AgentCore-Specific CloudWatch Metrics

AgentCore publishes these metrics automatically (you don't need to instrument):

| Metric | What It Measures |
|--------|-----------------|
| Invocation count | Number of agent invocations |
| Invocation latency | End-to-end response time (p50/p90/p99) |
| Error rate | Percentage of failed invocations |
| Token usage | Input/output tokens consumed |

**Recommended alarms:**

- Error rate > 5% for 5 minutes
- p99 latency > SLA threshold
- Token usage approaching quota (80%)

Create alarms — first discover the exact namespace (CloudWatch namespaces are case-sensitive):

1. `aws cloudwatch list-metrics --namespace "Bedrock-AgentCore"` — if no results, try `--namespace "Bedrock-Agentcore"`
2. Use the namespace that returns metrics in subsequent commands:

`aws cloudwatch put-metric-alarm --alarm-name <name> --metric-name <metric> --namespace "<discovered-namespace>" --statistic Average --period 300 --threshold <value> --comparison-operator GreaterThanThreshold --evaluation-periods 3 --dimensions "Name=Resource,Value=<resource-arn>" --alarm-actions "<sns-topic-arn>"`

### Common Failures

**Traces not appearing:**
OTEL collector not configured for AgentCore Runtime. Verify ADOT configuration in Runtime settings.

**Evaluations can't score:**
Missing required trace attributes. Verify instrumentation includes input, output, and tool call attributes.

## Security Considerations

**Encryption:**

- Enable KMS encryption at rest for Memory resources — customer-managed keys preferred for compliance workloads (HIPAA, GDPR)
- Memory data is encrypted in transit via TLS by default — do not disable TLS
- Encrypt CloudWatch Logs log groups receiving trace data with a KMS key

**Sensitive data:**

- Session memory stores conversation history which may contain PII, credentials, or business-sensitive data
- Trace attributes capture user queries and agent responses — treat as sensitive
- You MUST NOT log raw API keys, secrets, or credentials in trace attributes — sanitize tool call inputs before instrumentation
- Configure CloudWatch Logs retention limits — do not retain trace data indefinitely

**IAM — least privilege:**

- Scope Memory permissions to specific actions (`bedrock-agentcore:CreateMemory`, `bedrock-agentcore:GetMemory`) — avoid `bedrock-agentcore:*`
- Scope CloudWatch permissions to specific alarm and log group ARNs — avoid `cloudwatch:*` or `logs:*`
- Use IAM roles (not IAM users) for all service access

**Alarm notifications:**

- Encrypt SNS topics used for alarm actions with a KMS key
- Restrict SNS topic subscriptions to authorized personnel
- Include `aws:SourceAccount` condition in the SNS topic access policy
