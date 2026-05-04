# evals

Set up evaluation for your AgentCore agent — from a single quality check to a full production monitoring pipeline.

## When to use

- You want to know if your agent is giving good answers
- You want continuous monitoring of live traffic
- You want a CI/CD quality gate that fails the build if quality drops
- You want to interpret eval scores you've already run
- You want to compare agent versions

Not for debugging a specific wrong answer — use the `agents-debug` skill for that.

## Input

`$ARGUMENTS` is optional. If provided, it scopes the skill:

```
/evals                          # interactive — asks what you want to set up
/evals quick                    # run a quick eval on the most recent session
/evals monitor                  # set up continuous online monitoring
/evals ci                       # generate a CI/CD quality gate script
```

## Process

### Step 1: Understand the goal

Ask (or infer from `$ARGUMENTS`):

> "What are you trying to do?
>
> 1. Run a one-time eval on recent sessions to see how my agent is doing
> 2. Set up continuous monitoring of live traffic
> 3. Add a quality gate to my CI/CD pipeline
> 4. Create a custom evaluator for my specific use case
> 5. Understand eval scores I've already run"

### Step 2: Check prerequisites — and know what actually needs a deploy

Read `agentcore/agentcore.json` if it exists. Check:

- Is there a deployed runtime? (not always required — see below)
- Are there existing evaluators configured?

**If no project context:** Ask which runtime they want to evaluate. They can use `--runtime-arn` for standalone mode.

**What actually requires a deployed runtime — and what doesn't:**

| Action | Deploy required? |
|---|---|
| Define an evaluator (`agentcore add evaluator`) — LLM-as-judge or custom code | **No.** Writes to `agentcore.json` only. |
| Author & iterate on LLM-as-judge instructions / rating scale | **No.** Text edits; try them against saved traces or manual fixtures. |
| Unit-test a custom code evaluator (the `@custom_code_based_evaluator` function) | **No.** Import the function and call it with an `EvaluatorInput` fixture — see Path D below. |
| Write / dry-run the CI/CD quality-gate script | **No** for the script itself; deploy only needed if you want the eval call inside to hit production traffic. |
| **`agentcore run eval` against local-dev traces** | **No.** `agentcore dev` emits OTEL spans to CloudWatch by default — see "Evaluating a local dev run" below. |
| **`Evaluate` API with hand-constructed spans** (boto3) | **No.** Submit `SessionSpans` directly, no runtime needed at all. |
| `agentcore run eval` against production-runtime traces | Yes — operates on traces the deployed runtime produced. |
| `OnDemandEvaluationDatasetRunner` (SDK dataset runner) | Yes — the runner invokes an AgentCore Runtime agent in its pipeline. |
| Online monitoring (`agentcore add online-eval`) | Yes — continuous ingestion from the deployed runtime. |

**The local-dev eval loop is a real option.** `agentcore dev` auto-instruments OTEL and ships spans to CloudWatch the same way deployed runtimes do — this isn't a deployed-only feature. You can iterate on evaluators against your own local invocations, with a short round-trip and no AWS CDK churn.

**For the dataset runner and online monitoring, deploy is genuinely required.** Those paths invoke or ingest from a live AgentCore Runtime agent — there's no local equivalent.

**Don't tell the developer to fully deploy before they can make progress on evals.** Definition, authoring, and unit-testing are local. Running `agentcore run eval` is local too, given the prerequisites below.

#### Evaluating a local dev run

Requirements:

1. **AWS credentials available locally** (e.g., `aws sso login` for the account you want spans to land in).
2. **CloudWatch Transaction Search enabled** on the account. One-time setup — either in the CloudWatch console (Settings → X-Ray traces → Transaction Search) or via:

   ```bash
   aws xray update-trace-segment-destination --destination CloudWatchLogs
   ```

3. **OTEL is already on.** `agentcore dev` auto-instruments with the AWS OpenTelemetry distro by default. If you've passed `--no-traces`, remove it.
4. **Wait ~10 seconds** after invoking — CloudWatch put-to-get latency is ~10s end-to-end (covers both trace reads and eval queries; it's one ingestion step, not two).

The loop:

```bash
# Terminal 1 — start local dev with OTEL on (default)
agentcore dev

# Terminal 2 — invoke a few times, noting the session ID
agentcore dev --invoke "What's the weather in Seattle?" --stream
# or: agentcore invoke "..." once dev is running
# Note the session ID from the response / logs.

# Wait ~10 seconds for CloudWatch ingestion, then evaluate
agentcore run eval \
  --runtime MyAgent \
  --session-id <session-id-from-local-run> \
  --evaluator "Builtin.Helpfulness"
```

The evaluator runs in AWS (it's a managed evaluation service — the model call happens there, not locally), but the **agent run being evaluated happened on your laptop**. This is the fastest iteration loop for tuning an evaluator's instructions or rating scale.

#### Hand-constructed spans (no runtime at all)

For the tightest unit-test loop — or when you want to evaluate a saved snapshot without running the agent — call the `Evaluate` API directly with spans you construct:

```python
import boto3

client = boto3.client("bedrock-agentcore", region_name="<REGION>")

response = client.evaluate(
    evaluatorId="Builtin.Helpfulness",
    sessionSpans=[
        # Minimum shape matches the OTEL span schema for AgentCore traces.
        # Easiest way to produce a fixture: download one real span via
        # `agentcore traces get <traceId> --output trace.json`, then mutate it.
        {"name": "agent.invoke", "attributes": {"gen_ai.prompt": "What's the weather?", "gen_ai.response.content": "Sunny, 72°F."}},
    ],
)
print(response["evaluatorResults"])
```

The full span schema and field list is in the [`Understanding input spans`](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/understanding-input-spans.html) doc. This path is overkill for a one-time eval but invaluable when a custom code evaluator needs regression-test fixtures that don't depend on CloudWatch at all.

---

### Path A: Run a one-time eval

#### Step A1: Choose an evaluator

Start with built-in evaluators — they require no setup and cover the most common quality dimensions:

| Evaluator | Level | What it measures |
|---|---|---|
| `Builtin.Helpfulness` | TRACE | How useful was each response? |
| `Builtin.Correctness` | TRACE | Is the information factually accurate? (supports ground truth) |
| `Builtin.Faithfulness` | TRACE | Does the response stay grounded in provided context? |
| `Builtin.ResponseRelevance` | TRACE | Does the response address what was asked? |
| `Builtin.InstructionFollowing` | TRACE | Does the agent follow system-prompt instructions? |
| `Builtin.Conciseness` | TRACE | Is the response appropriately concise? |
| `Builtin.Coherence` | TRACE | Is the response logically coherent? |
| `Builtin.Refusal` | TRACE | Did the agent appropriately refuse out-of-scope requests? |
| `Builtin.ToolSelectionAccuracy` | TOOL_CALL | Did the agent pick the right tool for the task? |
| `Builtin.GoalSuccessRate` | SESSION | Did the agent complete the user's goal? (supports ground truth) |

**Built-in evaluator names may change.** Check the AgentCore docs for the current list — new evaluators are added across releases.

**Recommendation:** Start with `Builtin.Helpfulness` for a general quality check. Add `Builtin.GoalSuccessRate` for task completion. Use `Builtin.ToolSelectionAccuracy` when your agent uses tools. Use `Builtin.Correctness` or `Builtin.Faithfulness` when you have ground truth to compare against.

#### Step A2: Run the eval

```bash
# Run against the most recent session (auto-detected from project)
agentcore run eval --evaluator "Builtin.Helpfulness"

# Run against multiple evaluators
agentcore run eval \
  --evaluator "Builtin.Helpfulness" \
  --evaluator "Builtin.GoalSuccessRate"

# Run against a specific runtime (standalone mode, no project needed)
agentcore run eval \
  --runtime-arn arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/myagent-abc123 \
  --evaluator "Builtin.Helpfulness"

# Extend the lookback window (default is 7 days)
agentcore run eval --evaluator "Builtin.Helpfulness" --days 14
```

#### Step A3: Interpret the results

Scores are normalized to 0–1:

- **0.8–1.0** — Good. Agent is performing well on this dimension.
- **0.6–0.8** — Acceptable. Worth monitoring but not urgent.
- **Below 0.6** — Investigate. Check recent traces for patterns.

Results are saved to `agentcore/.cli/eval-runs/`. View history:

```bash
agentcore evals history
agentcore evals history --limit 10
```

---

### Path B: Set up continuous monitoring

#### Step B1: Create an evaluator (if needed)

For continuous monitoring, built-in evaluators are usually sufficient. If you need a custom evaluator for your specific use case, see Path D first.

#### Step B2: Add an online eval config

```bash
agentcore add online-eval \
  --name my_quality_monitor \
  --runtime MyAgent \
  --evaluator "Builtin.Helpfulness" \
  --evaluator "Builtin.GoalSuccessRate" \
  --sampling-rate 5
```

**Important naming rule:** Config names must use underscores only — no hyphens. `my-monitor` will fail with a validation error; `my_monitor` works.

**Sampling rate guidance:**

- `1–5` — Good for production (1–5% of requests evaluated)
- `10–20` — Good for staging or low-traffic agents
- `100` — Evaluate every request (dev/testing only, adds latency and cost)

#### Step B3: Deploy to activate

```bash
agentcore deploy -y
```

The online eval config starts in `CREATING` state and becomes `ACTIVE` within a few seconds after deploy.

#### Step B4: View results

Results stream to CloudWatch Logs:

```
/aws/bedrock-agentcore/evaluations/results/<config-id>
```

View in the AWS console: CloudWatch → GenAI Observability → Bedrock AgentCore → Evaluations tab.

Stream eval logs from the CLI:

```bash
agentcore logs evals --runtime MyAgent --since 1h
agentcore logs evals --follow
```

**Pause/resume without redeploying:**

```bash
agentcore pause online-eval my_quality_monitor
agentcore resume online-eval my_quality_monitor
```

---

### Path C: CI/CD quality gate

Generate a script that runs evals and fails the build if quality drops below a threshold.

```bash
#!/bin/bash
# quality-gate.sh — run after deploy in CI/CD

set -e

RUNTIME="MyAgent"
EVALUATOR="Builtin.Helpfulness"
THRESHOLD="0.7"

echo "Running quality gate eval..."
result=$(agentcore run eval \
  --runtime "$RUNTIME" \
  --evaluator "$EVALUATOR" \
  --days 1 \
  --json)

score=$(echo "$result" | jq -r '.run.results[0].aggregateScore // empty')

if [ -z "$score" ]; then
  echo "⚠️  No eval data found. Has the agent been invoked recently?"
  echo "   Invoke the agent at least once, wait ~10 seconds, then re-run."
  exit 1
fi

echo "Quality score: $score (threshold: $THRESHOLD)"

if awk -v s="$score" -v t="$THRESHOLD" 'BEGIN{exit !(s<t)}'; then
  echo "❌ Quality gate FAILED: score $score < $THRESHOLD"
  exit 1
fi

echo "✅ Quality gate PASSED"
```

**Note:** CloudWatch put-to-get latency is **~10 seconds end-to-end** — the same ingestion step unlocks both trace reads and eval queries; there's no extra indexing wait. In CI/CD, invoke the agent as part of your integration tests, then add a short `sleep 10` (or `sleep 15` for headroom) before running the quality gate. The old `sleep 300` pattern from earlier skills/docs is 30× longer than needed now.

For standalone mode (no project context in CI):

```bash
agentcore run eval \
  --runtime-arn arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/myagent-abc123 \
  --evaluator "Builtin.Helpfulness" \
  --days 1 \
  --json
```

---

### Path D: Custom evaluator

Use a custom evaluator when built-ins don't cover your specific quality criteria — domain accuracy, tone, format compliance, safety for your use case.

#### Step D1: Choose the evaluator type

- **LLM-as-a-judge** — An LLM scores each response against your instructions. Most flexible.
- **Code-based** — A Lambda function scores responses programmatically. Use for deterministic checks (format validation, required fields, etc.).

#### Step D2: Create an LLM-as-a-judge evaluator

Choose the right level first:

- `SESSION` — evaluate the whole conversation (goal completion, overall quality)
- `TRACE` — evaluate each individual response (helpfulness, accuracy, tone)
- `TOOL_CALL` — evaluate tool selection and parameters

Check the AgentCore docs for additional evaluator levels — new levels may be added across releases.

```bash
agentcore add evaluator \
  --name ResponseQuality \
  --level TRACE \
  --model "global.anthropic.claude-sonnet-4-5-20250929-v1:0" \
  --instructions "Evaluate the assistant's response for helpfulness and accuracy. Context: {context}. Response to evaluate: {assistant_turn}" \
  --rating-scale 1-5-quality
```

Note: The evaluator model ID above is an example — check the AgentCore docs for current supported evaluator model IDs and cross-region inference profiles.

**Placeholder rules by level:**

| Level | Required placeholder | Optional |
|---|---|---|
| `SESSION` | `{context}` | `{available_tools}` |
| `TRACE` | `{context}` | `{assistant_turn}`, `{available_tools}` |
| `TOOL_CALL` | `{context}` | `{tool_turn}`, `{available_tools}` |

**Rating scale presets** (pass as literal strings to `--rating-scale`):

- `1-5-quality` — Poor/Fair/Good/Very Good/Excellent (default)
- `1-3-simple` — Low/Medium/High
- `pass-fail` — Pass/Fail
- `good-neutral-bad` — Good/Neutral/Bad

**Custom rating scale:**

```bash
--rating-scale "0:Incorrect:Factually wrong or misleading, 0.5:Partial:Partially correct, 1:Correct:Accurate and complete"
```

#### Step D3: Create a code-based evaluator (for deterministic checks)

```bash
agentcore add evaluator \
  --name FormatChecker \
  --level TRACE \
  --type code-based \
  --lambda-arn arn:aws:lambda:<REGION>:<YOUR_ACCOUNT_ID>:function:check-response-format \
  --timeout 30
```

Your Lambda receives the trace context and must return a score between 0 and 1. Use the SDK's `@custom_code_based_evaluator()` decorator to handle the Lambda event parsing and response contract for you:

```python
# lambda_function.py
from bedrock_agentcore.evaluation.custom_code_based_evaluators import (
    custom_code_based_evaluator,
    EvaluatorInput,
    EvaluatorOutput,
)

@custom_code_based_evaluator()
def handler(evaluator_input: EvaluatorInput, context) -> EvaluatorOutput:
    # evaluator_input.session_spans contains the trace data
    # Implement your deterministic check (regex, schema validation, rule engine, etc.)
    response_text = _extract_response(evaluator_input.session_spans)

    if _matches_required_format(response_text):
        return EvaluatorOutput(value=1.0, label="Pass")
    return EvaluatorOutput(value=0.0, label="Fail", reasoning="Response did not match expected format")
```

The decorator handles parsing the raw Lambda event, extracting trace/span IDs, and serializing the response — write your check against typed `EvaluatorInput` and return a typed `EvaluatorOutput`.

#### Step D3.5: Unit-test the evaluator locally before deploying

The `@custom_code_based_evaluator` function is a plain Python function. Import it directly and exercise the logic with fixtures — no deploy, no AWS credentials needed:

```python
# test_evaluator.py
from bedrock_agentcore.evaluation.custom_code_based_evaluators import EvaluatorInput
from lambda_function import handler  # the decorated function above

def _fake_input(response_text: str) -> EvaluatorInput:
    # Construct the minimum EvaluatorInput shape the handler reads.
    # Use a saved real trace for higher-fidelity fixtures — download one via
    # `agentcore traces get <traceId> --output trace.json` after a single deploy+invoke.
    return EvaluatorInput(
        session_spans=[{"attributes": {"gen_ai.response.content": response_text}}],
        # ...fill remaining fields the SDK expects for your level
    )

def test_matches_format():
    out = handler(_fake_input('{"status": "ok"}'), context=None)
    assert out.value == 1.0

def test_rejects_free_text():
    out = handler(_fake_input("Here's your answer: ok"), context=None)
    assert out.value == 0.0
    assert "did not match" in (out.reasoning or "").lower()
```

Run with `pytest test_evaluator.py`. Iterate the logic until the fixtures pass. Only **then** deploy — the deploy step is about wiring the Lambda into AgentCore, not about debugging the check.

For **LLM-as-judge** evaluators, there's no equivalent unit-test surface (the model call happens in the eval service), but you can iterate on the instructions against saved traces by dry-running the prompt in Bedrock console or in a one-off script before `agentcore add evaluator`.

#### Step D4: Deploy and run against a real trace

```bash
agentcore deploy -y
agentcore run eval --evaluator ResponseQuality --days 7
```

**Evaluator name rules:** alphanumeric + underscores only, max 48 chars. No hyphens.

---

## Troubleshooting

### "No spans found for session"

- Wait ~10 seconds after invoking the agent — CloudWatch put-to-get is ~10s end-to-end (there's no separate eval-indexing step beyond that)
- Check that observability was enabled when the agent was deployed
- Extend the lookback: `--days 14` or `--days 30`

### "No agent specified" or agent ID not found

- Run from inside your AgentCore project directory, or
- Use `--runtime-arn` to specify the agent explicitly

### Online eval config stuck in CREATING

- Run `agentcore status --type online-eval` to check status
- Usually resolves within 30 seconds of deploy

### `remove evaluator` fails

- An online eval config is referencing this evaluator
- Remove the online eval config first: `agentcore remove online-eval --name <name>`
- Then remove the evaluator

## Cross-region inference (data residency)

Both built-in and LLM-as-judge evaluators use **cross-region inference** by default. The data being evaluated stays in your primary region, but the inference call that runs the judge model may execute in another AWS region within the same geography (e.g., `us-east-1` → `us-east-2`/`us-west-2`; EU stays in EU).

There's no extra cost, and logs don't include the inference region. But if data-residency rules require pinning inference to a single region:

- **Built-in evaluators:** they're managed by AgentCore and use cross-region inference as-configured. If single-region inference is required, use a custom evaluator instead.
- **Custom LLM-as-judge evaluators:** pin the model by choosing a region-specific model ID for `--model` instead of a cross-region inference profile ID. Check the docs for current single-region model IDs in your region.
- **Code-based evaluators:** not affected. The Lambda runs wherever you deployed it.

See [cross-region inference](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/cross-region-inference.html) for the current geography/region mapping rather than baking it in here — it expands across releases.

## When to use the dataset runner vs. `agentcore run eval`

Two different tools for two different workflows — developers confuse them.

| You want to... | Tool | Where it runs |
|---|---|---|
| Evaluate one session or trace from a recent run | `agentcore run eval --session-id <id>` | CLI, against CloudWatch-ingested spans |
| Evaluate *everything* from the last N days and track score drift | `agentcore run eval --days 7` | CLI, against CloudWatch |
| Run a curated benchmark / regression suite (20–500 scenarios, CI/CD) | `OnDemandEvaluationDatasetRunner` (SDK) | Your Python process, orchestrates invoke + wait + evaluate |
| Check that every production invocation meets quality thresholds | `agentcore add online-eval` | Platform, continuous sampling |

**Use `agentcore run eval`** when you're iterating on an evaluator, investigating a specific regression, or running a quality gate against recent traffic. It's fast, cheap, and doesn't invoke the agent itself — it only scores existing traces.

**Use `OnDemandEvaluationDatasetRunner`** when you have a dataset of scenarios with expected responses / trajectories / assertions and you want to run them as a batch. The runner **invokes the agent** for each scenario, waits for telemetry ingestion (default 180 seconds, paid once per run not per scenario), then evaluates. This requires a deployed runtime. Typical use: regression pack in CI before promoting a new version.

**Use online eval** for continuous production monitoring at a sampling rate — not the same as a benchmark.

## Output

- CLI commands to run evals or set up monitoring
- Quality gate script (for CI/CD path)
- Evaluator config (for custom evaluator path)
- Interpretation of scores if reviewing existing results
