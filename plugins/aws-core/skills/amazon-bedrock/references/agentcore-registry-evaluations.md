# AgentCore Registry & Evaluations

## Table of Contents

- Agent Registry (Preview)
- Evaluations Service

## Agent Registry (Preview)

Catalog, discover, and govern AI agents and tools across an organization.

### Governance Workflow

The key non-obvious behavior — two modes:

| Mode | Behavior | Use For |
|------|----------|---------|
| **Auto-approve** | Records become discoverable immediately | Development environments (isolated accounts only) |
| **Manual approval** | Records require explicit approval before discovery | Production environments |

Status transitions: `PENDING` → `APPROVED` → `ACTIVE` (or `REJECTED`)

**Common failure**: Record stuck in `PENDING` — governance workflow is set to manual approval but no one has approved. Check governance configuration or switch to auto-approve for dev.

### Registering Resources

Resource types: MCP servers, A2A agents, agent skills, custom types.

**Constraints:**

- You MUST specify resource type, name, description, and invocation endpoint
- You MUST register: `aws bedrock-agentcore-control create-registry-record --registry-id <registry-id> --name <name> --descriptor-type <MCP|A2A|CUSTOM|AGENT_SKILLS> --description "<desc>"`
- Tags and capabilities metadata improve discoverability

### Searching and Discovery

- CLI: `aws bedrock-agentcore-control list-registry-records --registry-id <registry-id>`
- MCP endpoint: programmatic discovery via MCP protocol
- Filter by resource type, tags, capabilities

### Available Regions

Verify availability: `aws bedrock-agentcore-control list-registry-records --registry-id <registry-id> --region <region>`. Registry is a Preview feature — region availability is expanding.

## Evaluations Service

Automated agent quality assessment using LLM-as-a-Judge.

### Setup Workflow

```
Evaluation Setup:
- [ ] Step 1: Instrument agent with OTEL (see [memory & observability](agentcore-memory-observability.md))
- [ ] Step 2: Create evaluators (built-in or custom)
- [ ] Step 3: Configure online evaluation (sampling rate, data source)
- [ ] Step 4: Monitor scores in CloudWatch
```

### Built-in Evaluators

| Evaluator | What It Measures |
|-----------|-----------------|
| `Builtin.Helpfulness` | Does the response help the user? |
| `Builtin.Faithfulness` | Is the response grounded in provided context? |
| `Builtin.Harmfulness` | Does the response contain harmful content? |

Refer to the latest AWS documentation on AgentCore Evaluations built-in evaluators for the full current list.

### Custom Evaluators

Define your own evaluation criteria:

- Rubric: what constitutes a good/bad response for your use case
- Scoring scale: numeric (1-5) or binary (pass/fail)
- Custom prompt template: the LLM-as-a-Judge prompt

Create custom evaluators: `aws bedrock-agentcore-control create-evaluator --evaluator-name <name> --level <TOOL_CALL|TRACE|SESSION> --evaluator-config '{"llmAsAJudge":{"instructions":"<criteria>","ratingScale":{"numerical":[{"value":1,"description":"Poor"},{"value":5,"description":"Excellent"}]}}}'`

### Online vs On-Demand Evaluation

| Type | When | Use For |
|------|------|---------|
| **Online** | Continuous, samples production traffic | Monitoring quality over time |
| **On-demand** | Batch, against a test dataset | Regression testing, A/B comparison |

**Online evaluation constraints:**

- Configure sampling rate — evaluating every invocation is expensive (each evaluation is a model invocation)
- Start with 5-10% sampling, increase if quality issues detected
- Data source: which OTEL traces to evaluate

### Monitoring Scores

- Evaluation scores publish to CloudWatch automatically
- Create alarms for quality degradation: score drops below threshold
- Investigate low-scoring sessions: trace → evaluation result → root cause
- Create quality alarms — first discover the exact namespace (CloudWatch namespaces are case-sensitive):
  1. `aws cloudwatch list-metrics --namespace "Bedrock-AgentCore"` — if no results, try `--namespace "Bedrock-Agentcore"`
  2. Use the namespace that returns metrics in subsequent commands:

  `aws cloudwatch put-metric-alarm --alarm-name <name> --metric-name <metric> --namespace "<discovered-namespace>" --statistic Average --period 300 --threshold <value> --comparison-operator LessThanThreshold --evaluation-periods 3 --alarm-actions "<sns-topic-arn>"`

## Security Considerations

**Registry access control:**

- You MUST use least-privilege IAM policies — separate read (`list-registry-records`) from write (`create-registry-record`) permissions. Avoid `bedrock-agentcore:*`
- You MUST use IAM roles (not IAM users) for programmatic registry access
- You SHOULD add `aws:SourceArn` and `aws:SourceAccount` conditions to resource policies on registry resources
- You MUST restrict auto-approve governance mode to isolated development accounts — use manual approval in shared or production environments

**Evaluation data protection:**

- OTEL traces sent to evaluations contain user queries, agent responses, and tool call parameters — these may include PII
- You MUST ensure OTEL trace data is encrypted in transit (TLS) and at rest
- You SHOULD implement PII scrubbing in OTEL instrumentation before traces reach the evaluation service
- You MUST restrict access to evaluation results to authorized personnel only
- Encrypt CloudWatch log groups storing evaluation results with KMS

**Monitoring security:**

- You MUST encrypt SNS topics used for alarm actions with KMS
- You MUST validate that SNS topic subscribers are authorized to receive evaluation data
- You MUST enable CloudTrail for all `bedrock-agentcore-control` API calls — tracks who registered resources, who approved/rejected records, and who modified evaluations

- Refer to the latest AWS documentation on Bedrock AgentCore security best practices.
