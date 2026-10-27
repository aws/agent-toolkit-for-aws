# evals

Set up evaluation for your AgentCore agent — from a single quality check to a full production monitoring pipeline.

## When to use

- You want to know if your agent is giving good answers
- You want continuous monitoring of live traffic
- You want a CI/CD quality gate that fails the build if quality drops
- You want to run a fixed regression suite (a dataset of scenarios) against a new version
- You want to interpret eval scores you've already run
- You want to compare agent versions or configurations (A/B test)
- You want AgentCore to suggest a better system prompt or tool descriptions

Not for debugging a specific wrong answer — use the `agents-debug` skill for that.

## Input

`$ARGUMENTS` is optional. If provided, it scopes the skill:

```
/evals                          # interactive — asks what you want to set up
/evals quick                    # run an on-demand eval on recent sessions
/evals monitor                  # set up continuous online monitoring
/evals ci                       # generate a CI/CD quality gate script
/evals regression               # dataset + batch evaluation regression run
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
> 5. Run a regression suite from a dataset of test scenarios
> 6. Compare two configurations with an A/B test, or get prompt / tool-description recommendations
> 7. Understand eval scores I've already run"

### Step 2: Check prerequisites — and know what actually needs a deploy

Read `agentcore/agentcore.json` if it exists. Check:

- Which agents exist — `runtimes` (your own code) and/or `harnesses` (config-defined agents) — and whether they're deployed
- Existing `evaluators` and `onlineEvalConfigs`

**Project commands vs. `eval` commands.** `agentcore add evaluator ...` and `agentcore add online-eval ...` write to `agentcore.json` and take effect on `agentcore deploy`; they use **project names**. The `agentcore eval ...` command group calls the service directly, works outside a project, and takes **deployed IDs**. Get the IDs from:

```bash
agentcore status --json
```

`status` lists each resource with `resourceType`, `name`, `deploymentState`, and its deployed `arn` (`id` is usually `null`, so use the ARN). A Runtime ID is the last path segment of the Runtime ARN (`arn:aws:bedrock-agentcore:<region>:<account>:runtime/<runtimeId>`). For example:

```bash
RUNTIME_ID=$(agentcore status --json \
  | jq -r '.resources[] | select(.resourceType=="runtime" and .name=="MyAgent") | .arn | split("/") | last')
```

Built-in evaluators are referenced as `Builtin.<Name>` everywhere. Project-defined custom evaluators are referenced by name inside `agentcore.json` (e.g. in `add online-eval --evaluators`) but by their deployed evaluator ID in `agentcore eval ...` commands — look them up the same way (`resourceType=="evaluator"`).

**If no project context:** Ask for the deployed Runtime ID or harness ID and use the `agentcore eval ...` commands directly.

**What actually requires a deployed agent — and what doesn't:**

| Action | Deploy required? |
|---|---|
| Define an evaluator (`agentcore add evaluator llm-as-a-judge` / `code-based`) | **No.** Writes to `agentcore.json` (a code-based evaluator without `--lambda-arn` also scaffolds `app/<name>/`). |
| Author & iterate on LLM-as-a-Judge instructions / rating scale | **No.** Text edits; try them against saved traces or manual fixtures. |
| Unit-test a custom code evaluator (the `@custom_code_based_evaluator` function) | **No.** Import the function and call it with an `EvaluatorInput` fixture — see Path D below. |
| Write / dry-run the CI/CD quality-gate script | **No** for the script itself; the eval call inside needs a deployed agent. |
| **`Evaluate` API with hand-constructed spans** (boto3) | **No.** Submit session spans directly, no runtime needed at all. |
| Score a local `agentcore dev` run with `agentcore eval ...` | **Not supported.** `agentcore dev` sends spans to a local collector, not CloudWatch — see "Local dev traces" below. |
| `agentcore eval ondemand evaluate` / `agentcore eval batch-evaluation evaluate` | Yes — scores spans a deployed Runtime or harness wrote to CloudWatch. |
| `agentcore eval ondemand simulate` / `agentcore eval batch-evaluation simulate` (dataset replay) | Yes — invokes a deployed Runtime once per dataset example. |
| Online monitoring (`agentcore add online-eval`) | Yes — continuous sampling from the deployed agent. |
| A/B tests (`agentcore eval ab-test ...`) | Yes — needs a deployed Gateway and online-eval configs. |

**Don't tell the developer to fully deploy before they can make progress on evals.** Definition, authoring, and unit-testing are local. Scoring real sessions needs one deploy and a few invocations.

#### Local dev traces

`agentcore dev` starts an in-process OTLP collector and points the agent's OTEL SDK at it. Traces are persisted under `agentcore/.cli/traces/otlp/` and shown in the Agent Inspector (`agentcore dev --mode browser`); `--no-traces` turns collection off. Python CodeZip runtimes are auto-instrumented when `aws-opentelemetry-distro` is in the runtime's dependencies (the Python templates include it); a runtime with `"instrumentation": { "enableOtel": false }` in `agentcore.json` is skipped.

These local traces are useful for checking *what the agent did* while you iterate, but they never reach CloudWatch, so `agentcore eval` commands can't score them. To score real sessions, deploy and invoke:

```bash
agentcore deploy
SESSION_ID=$(uuidgen)   # Runtime session IDs must be at least 33 characters
agentcore invoke --runtime MyAgent --session-id "$SESSION_ID" --payload '{"prompt": "What is the weather in Seattle?"}'

# Traces take 30–90s to land in CloudWatch: poll until the session shows up, then evaluate
found=
for i in $(seq 1 18); do   # up to 3 minutes
  if agentcore traces runtime list --name MyAgent --since 10m --json \
      | jq -e --arg s "$SESSION_ID" 'any(.traces[]; .sessionId == $s)' > /dev/null; then
    found=1; break
  fi
  sleep 10
done
[ -n "$found" ] || { echo "No trace for session $SESSION_ID after 3 minutes; check logs and Transaction Search" >&2; exit 1; }
agentcore eval ondemand evaluate \
  --agent "$RUNTIME_ID" \
  --session-ids "$SESSION_ID" \
  --evaluators Builtin.Helpfulness
```

The evaluator runs in AWS (it's a managed evaluation service — the model call happens there, not locally).

Two account prerequisites for deployed traces: **AWS credentials** for the account, and **CloudWatch Transaction Search** enabled. `agentcore deploy` enables Transaction Search automatically (best-effort; it prints `skipping Transaction Search: ...` if it can't, and it is skipped when `agentcore config transactionSearch false` is set). To enable it manually:

```bash
aws xray update-trace-segment-destination --destination CloudWatchLogs
```

#### Hand-constructed spans (no runtime at all)

For the tightest unit-test loop — or when you want to evaluate a saved snapshot without running the agent — call the `Evaluate` API directly with spans you construct:

```python
import json
import boto3

client = boto3.client("bedrock-agentcore", region_name="<REGION>")

# Download one real trace after a single deploy+invoke:
#   agentcore traces runtime get <traceId> --output trace.json
# Each record's "@message" is a raw ADOT span or log record. Pass them as-is (or edit
# the text in them to build variants) — don't hand-write spans from scratch.
spans = [r["@message"] for r in json.load(open("trace.json"))]

response = client.evaluate(
    evaluatorId="Builtin.Helpfulness",
    evaluationInput={"sessionSpans": spans},
)
print(response["evaluationResults"])
```

Minimal hand-written spans are rejected: every span needs at least `traceId`, `spanId`, and `startTimeUnixNano` (plus the `session.id` attribute and the `gen_ai.*` content the evaluator reads), which is why copying a real trace is the practical route. The input shape is in the [`EvaluationInput`](https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_EvaluationInput.html) API reference. This path is overkill for a one-time eval but invaluable when a custom code evaluator needs regression-test fixtures that don't depend on CloudWatch at all.

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
| `Builtin.ToolParameterAccuracy` | TOOL_CALL | Did the agent pass the right parameters to the tool? |
| `Builtin.GoalSuccessRate` | SESSION | Did the agent complete the user's goal? (supports ground truth) |
| `Builtin.TrajectoryExactOrderMatch` / `InOrderMatch` / `AnyOrderMatch` | SESSION | Did the agent call the tools in `expected_trajectory` (exact order / in order / any order)? |

**Built-in evaluator names may change.** Check the AgentCore docs for the current list — new evaluators are added across releases.

**Recommendation:** Start with `Builtin.Helpfulness` for a general quality check. Add `Builtin.GoalSuccessRate` for task completion. Use `Builtin.ToolSelectionAccuracy` when your agent uses tools. Use `Builtin.Correctness` when you have ground truth (`expected_response`) to compare against, and `Builtin.Faithfulness` to check the response stays grounded in retrieved context.

#### Step A2: Run the eval

`agentcore eval ondemand evaluate` reads the agent's sessions from CloudWatch and scores them synchronously, printing JSON. It needs exactly one session filter: `--lookback-days`, `--start-time`/`--end-time`, `--session-ids`, or `--trace-id`.

```bash
# Evaluate the last day of sessions for a deployed Runtime (or pass a harness ID)
agentcore eval ondemand evaluate \
  --agent "$RUNTIME_ID" \
  --evaluators Builtin.Helpfulness Builtin.GoalSuccessRate \
  --lookback-days 1

# Specific sessions
agentcore eval ondemand evaluate \
  --agent "$RUNTIME_ID" \
  --session-ids <session-id-1> <session-id-2> \
  --evaluators Builtin.Helpfulness

# A single trace (its session ID is read off the span)
agentcore eval ondemand evaluate \
  --agent "$RUNTIME_ID" \
  --trace-id <trace-id> \
  --evaluators Builtin.Helpfulness

# An explicit window, scored against expected answers
agentcore eval ondemand evaluate \
  --agent "$RUNTIME_ID" \
  --start-time 2026-10-20T00:00:00Z --end-time 2026-10-21T00:00:00Z \
  --evaluators Builtin.Correctness \
  --ground-truth file://ground-truth.json
```

Add `--endpoint <qualifier>` to score a non-`DEFAULT` Runtime endpoint. `--ground-truth` takes `EvaluationReferenceInput[]` JSON — run `agentcore eval ondemand evaluate --help` for the exact shape.

For large windows, run the same evaluation service-side instead. It's asynchronous, returns a job ID, and the job's results persist in the service:

```bash
agentcore eval batch-evaluation evaluate \
  --name quality_2026_10_26 \
  --agent "$RUNTIME_ID" \
  --start-time 2026-10-19T00:00:00Z --end-time 2026-10-26T00:00:00Z \
  --evaluators Builtin.Helpfulness Builtin.GoalSuccessRate

agentcore eval batch-evaluation get --id <batch-evaluation-id>
agentcore eval batch-evaluation list --json
```

`batch-evaluation list` opens an interactive view by default and fails without a terminal (`interactive mode requires a TTY`), so pass `--json` in scripts and agent sessions. Batch evaluation names must be unique in the account. Instead of `--agent`, `--online-eval <id>` re-scores the sessions an online-eval config already sampled.

#### Step A3: Interpret the results

On-demand output is JSON: `sessionsRequested`, `sessionsEvaluated`, and a `results` array. Each result carries `evaluatorId`, `value`, `label`, and `explanation` (or `errorCode`/`errorMessage` if that evaluation failed). The scale of `value` depends on the evaluator — a custom LLM-as-a-Judge evaluator returns values from its rating scale. For evaluators that score 0–1:

- **0.8–1.0** — Good. Agent is performing well on this dimension.
- **0.6–0.8** — Acceptable. Worth monitoring but not urgent.
- **Below 0.6** — Investigate. Read the `explanation` and check recent traces for patterns.

`sessionsEvaluated` lower than `sessionsRequested` means some sessions produced no result (for example, a TRACE-level evaluator on a session with no traces).

There's no local eval history in v1 — save the JSON yourself (`... > eval-$(date +%F).json`) or use batch evaluations, which you can list and re-read with `agentcore eval batch-evaluation list --json` / `get`.

---

### Path B: Set up continuous monitoring

#### Step B1: Create an evaluator (if needed)

For continuous monitoring, built-in evaluators are usually sufficient. If you need a custom evaluator for your specific use case, see Path D first.

#### Step B2: Add an online eval config

```bash
agentcore add online-eval \
  --name my_quality_monitor \
  --agent MyAgent \
  --evaluators Builtin.Helpfulness Builtin.GoalSuccessRate \
  --sampling-rate 5
```

`--agent` is the project Runtime name. `--evaluators` (up to 10) accepts project evaluator names, `Builtin.*` IDs, or evaluator ARNs. Other useful flags: `--endpoint <qualifier>` to monitor one Runtime endpoint, `--enable-on-create false` to deploy it paused, and `--log-group-name` / `--service-name` (instead of `--agent`) for a custom trace source.

To monitor a harness, or an agent that isn't in this project, create the config service-side instead (not tracked in `agentcore.json`):

```bash
agentcore eval online-eval create \
  --name my_harness_monitor \
  --agent <harness-or-runtime-id> \
  --evaluators Builtin.Helpfulness \
  --sampling-rate 5
```

**Important naming rule:** Config names must start with a letter and use only letters, digits, and underscores (max 48) — no hyphens. `my-monitor` fails validation; `my_monitor` works. Project resources are deployed as `<project>_<target>_<name>` (e.g. `MyProj_default_my_monitor`) — that's the name you'll see in `agentcore status`, the console, and log group names — so the CLI also rejects names whose deployed form would exceed 48 characters.

**Sampling rate guidance** (`--sampling-rate` accepts 0.01–100):

- `1–5` — Good for production (1–5% of sessions evaluated)
- `10–20` — Good for staging or low-traffic agents
- `100` — Evaluate every session (dev/testing only, adds cost)

#### Step B3: Deploy to activate

```bash
agentcore deploy
```

The online eval config starts in `CREATING` state and becomes `ACTIVE` shortly after deploy.

#### Step B4: View results

Results are not immediate. A session is scored only after it has been idle for the config's session timeout — 5 minutes by default for `agentcore add online-eval`, 15 minutes by default for `agentcore eval online-eval create` (`--session-timeout-minutes`). In practice, first results take 10–15+ minutes after the last invocation — poll `agentcore eval online-eval logs` rather than waiting a fixed time. The deploy honors `sessionTimeoutMinutes` (1–1440) on the `onlineEvalConfigs` entry in `agentcore.json`, but the CLI's own schema doesn't declare it, so the next `agentcore add` or `agentcore remove` silently rewrites the file without it. If you set it, re-check the entry after every CLI edit before deploying — or leave the 5-minute default. Sessions that already existed in the trace source when the config became active can be sampled and scored too, so the first results may be for traffic sent before the deploy.

Results stream to CloudWatch Logs:

```
/aws/bedrock-agentcore/evaluations/results/<config-id>
```

View in the AWS console: CloudWatch → GenAI Observability → Bedrock AgentCore → Evaluations tab.

Read eval logs from the CLI (the config ID is the last `/` segment of the `arn` for `resourceType=="online-eval"` in `agentcore status --json`):

```bash
agentcore eval online-eval logs --id <online-eval-id> --since 1h
agentcore eval online-eval logs --id <online-eval-id> --tail
```

**Pause/resume without redeploying:**

```bash
agentcore eval online-eval pause --id <online-eval-id>
agentcore eval online-eval resume --id <online-eval-id>
```

These change the deployed config directly; they don't edit `agentcore.json`.

---

### Path C: CI/CD quality gate

Two kinds of gate — pick based on what you're protecting:

- **Recent-traffic gate** — score only the sessions your integration tests just produced (`agentcore eval ondemand evaluate --session-ids`). Cheap; reflects whatever the tests sent.
- **Dataset regression gate** — replay a fixed dataset against the new version and score it (`agentcore eval ondemand simulate`). Same scenarios every run, so scores are comparable across versions. Preferred for promotion gates — see Path E for building the dataset.

Generate a script that runs evals and fails the build if quality drops below a threshold:

```bash
#!/bin/bash
# quality-gate.sh — run after deploy in CI/CD
set -euo pipefail

RUNTIME_ID="${RUNTIME_ID:?set RUNTIME_ID to the deployed Runtime ID}"
EVALUATOR="Builtin.Helpfulness"
THRESHOLD="0.7"

# Recent-traffic gate: the integration tests must invoke with these session IDs,
# e.g. agentcore invoke --runtime <RuntimeName> --session-id "$SESSION_ID" --payload '...'
# (session IDs are 33-100 characters; a UUID plus a prefix works).
SESSION_IDS="${SESSION_IDS:?set SESSION_IDS to the space-separated session IDs your tests used}"

echo "Running quality gate eval..."
# shellcheck disable=SC2086  # split SESSION_IDS into separate arguments
result=$(agentcore eval ondemand evaluate --json \
  --agent "$RUNTIME_ID" \
  --evaluators "$EVALUATOR" \
  --session-ids $SESSION_IDS) || { echo "⚠️  Eval failed or found none of the test sessions. Did the tests use these session IDs, and have their traces landed?" >&2; exit 1; }
# Dataset regression gate (instead of the above):
# result=$(agentcore eval ondemand simulate \
#   --runtime-id "$RUNTIME_ID" \
#   --dataset ./evals/regression.jsonl \
#   --payload-template '{"prompt":"{input}"}' \
#   --evaluators "$EVALUATOR") || { echo "⚠️  Dataset replay failed" >&2; exit 1; }

# A result that failed to evaluate carries errorCode/errorMessage and no value.
# Fail on those instead of dropping them, or errors would look like a pass.
errors=$(echo "$result" | jq '[.results[] | select(.errorCode != null or .value == null)] | length')
if [ "$errors" -gt 0 ]; then
  echo "❌ $errors evaluation(s) errored:" >&2
  echo "$result" | jq -r '.results[] | select(.errorCode != null or .value == null) | "  \(.evaluatorId): \(.errorCode // "no value") \(.errorMessage // "")"' >&2
  exit 1
fi

score=$(echo "$result" | jq -r '[.results[].value] | if length == 0 then empty else add / length end')
if [ -z "$score" ]; then
  echo "⚠️  No eval results. Invoke the agent, wait for its traces (up to ~90s), then re-run." >&2
  exit 1
fi

echo "Quality score: $score (threshold: $THRESHOLD)"

if awk -v s="$score" -v t="$THRESHOLD" 'BEGIN{exit !(s<t)}'; then
  echo "❌ Quality gate FAILED: score $score < $THRESHOLD"
  exit 1
fi

echo "✅ Quality gate PASSED"
```

**Note:** Traces take **30–90 seconds** after an invocation to become readable, and the same ingestion step unlocks both trace reads and eval queries. For the recent-traffic gate, invoke the agent as part of your integration tests with known `--session-id` values (pass the same IDs to the gate as `SESSION_IDS`), then poll `agentcore traces runtime list --json` until the test sessions appear (as in Step 2's example) before running the gate — don't rely on a short fixed `sleep`. The `simulate` commands wait for ingestion themselves (`--ingestion-wait-ms`, default 180000).

The gate needs no project checkout — every command above takes the deployed Runtime ID, so pass it to CI as a variable.

---

### Path D: Custom evaluator

Use a custom evaluator when built-ins don't cover your specific quality criteria — domain accuracy, tone, format compliance, safety for your use case.

#### Step D1: Choose the evaluator type

- **LLM-as-a-Judge** — An LLM scores each response against your instructions. Most flexible.
- **Code-based** — A Lambda function scores responses programmatically. Use for deterministic checks (format validation, required fields, etc.).

#### Step D2: Create an LLM-as-a-Judge evaluator

Choose the right level first:

- `SESSION` — evaluate the whole conversation (goal completion, overall quality)
- `TRACE` — evaluate each individual response (helpfulness, accuracy, tone)
- `TOOL_CALL` — evaluate tool selection and parameters

```bash
agentcore add evaluator llm-as-a-judge \
  --name ResponseQuality \
  --level TRACE \
  --model "global.anthropic.claude-sonnet-4-5-20250929-v1:0" \
  --instructions "Evaluate the assistant's response for helpfulness and accuracy. Context: {context}. Response to evaluate: {assistant_turn}" \
  --rating-scale 1-5-quality
```

`--instructions` also accepts `file://<path>` or `-` (stdin) — easier for long prompts. `--model-provider OpenResponses` uses an OpenResponses model ID instead of Bedrock. To create the evaluator directly in the account without a project, use `agentcore eval evaluator llm-as-a-judge create` with the same flags except `--description` (it has none); update a deployed one with `agentcore eval evaluator llm-as-a-judge update --id <evaluator-id>`.

Pick the judge model carefully: some newer models (e.g. `global.anthropic.claude-sonnet-5-5`) reject the evaluator's inference config (`temperature` is deprecated for this model) at `CreateEvaluator`, so the deploy rolls back. There's no CLI flag to change that config, so use a model that accepts it, like the one above.

**Placeholder rules by level.** Instructions must contain at least one placeholder from the evaluator's level, and none from outside it. The CLI doesn't check this — the service does, and with `agentcore add` a bad prompt only surfaces as a failed `agentcore deploy`. Allowed placeholders at the time of writing:

| Level | Allowed placeholders |
|---|---|
| `SESSION` | `{context}`, `{available_tools}`, `{actual_tool_trajectory}`, `{expected_tool_trajectory}`, `{assertions}` |
| `TRACE` | `{context}`, `{assistant_turn}`, `{expected_response}`, `{system_instructions}` |
| `TOOL_CALL` | `{context}`, `{available_tools}`, `{tool_turn}`, `{system_instructions}` |

The service may add placeholders over time — check the AgentCore Evaluations docs if a deploy rejects your instructions.

**Rating scale presets** (pass as literal strings to `--rating-scale`). Labels for `agentcore add evaluator`; `eval evaluator llm-as-a-judge create` uses different ones (in parentheses):

- `1-5-quality` — Very Poor/Poor/Fair/Good/Excellent (Poor/Fair/Good/Very Good/Excellent)
- `1-3-simple` — Poor/Acceptable/Good (Low/Medium/High)
- `pass-fail` — pass/fail (Pass/Fail)
- `good-neutral-bad` — good/neutral/bad (Good/Neutral/Bad)

**Custom rating scale:** pass a JSON rating scale with either a `numerical` list (integer `value` + `label` + `definition`) or a `categorical` list (`label` + `definition`) — not both:

```bash
--rating-scale '{"numerical":[{"value":0,"label":"Incorrect","definition":"Factually wrong or misleading"},{"value":1,"label":"Partial","definition":"Partially correct"},{"value":2,"label":"Correct","definition":"Accurate and complete"}]}'
```

#### Step D3: Create a code-based evaluator (for deterministic checks)

Let the CLI scaffold and deploy the Lambda for you:

```bash
agentcore add evaluator code-based \
  --name FormatChecker \
  --level TRACE \
  --timeout-seconds 30
```

This writes `app/FormatChecker/` (`lambda_function.py`, `pyproject.toml`, `execution-role-policy.json`) and a `managed` code-based evaluator in `agentcore.json`; `agentcore deploy` packages the directory into the evaluator Lambda. The stub returns `Pass` for every session until you implement it. Add IAM statements for anything your logic calls to `execution-role-policy.json`.

To use a Lambda you already deploy yourself, pass its ARN instead (`--timeout-seconds` isn't valid with it):

```bash
agentcore add evaluator code-based \
  --name FormatChecker \
  --level TRACE \
  --lambda-arn arn:aws:lambda:<REGION>:<YOUR_ACCOUNT_ID>:function:check-response-format
```

The Lambda receives the trace context and returns a score. The SDK's `@custom_code_based_evaluator()` decorator handles the Lambda event parsing and response contract for you.

`input.session_spans` holds the raw ADOT span and log records — the same shape as the `@message` objects in a `agentcore traces runtime get` file. There is no response-text attribute on them: Strands/ADOT put the assistant's reply in `gen_ai.choice`, both as an event on the `invoke_agent` span (`attributes.message`) and as a log record (`eventName: "gen_ai.choice"`, text under `body.message.content[].text`). Read it from there:

```python
# app/FormatChecker/lambda_function.py
import json

from bedrock_agentcore.evaluation.custom_code_based_evaluators import (
    custom_code_based_evaluator,
    EvaluatorInput,
    EvaluatorOutput,
)


def _extract_response(spans, trace_id=None) -> str:
    """Return the agent's final reply for a trace from its `gen_ai.choice` event or log record."""
    for s in spans:
        if trace_id and s.get("traceId") != trace_id:
            continue
        if (s.get("attributes") or {}).get("gen_ai.operation.name") == "invoke_agent":
            for ev in s.get("events") or []:
                if ev.get("name") == "gen_ai.choice":
                    return ev.get("attributes", {}).get("message", "")
    for s in spans:
        if trace_id and s.get("traceId") != trace_id:
            continue
        if s.get("eventName") == "gen_ai.choice":
            content = (s.get("body") or {}).get("message", {}).get("content", [])
            return "".join(c.get("text", "") for c in content)
    return ""


def _matches_required_format(text: str) -> bool:
    # Your deterministic check (regex, schema validation, rule engine, etc.)
    try:
        json.loads(text)
        return True
    except ValueError:
        return False


@custom_code_based_evaluator()
def handler(input: EvaluatorInput, context) -> EvaluatorOutput:
    # input.target_trace_id / input.target_span_id identify what to grade at TRACE / TOOL_CALL level.
    response_text = _extract_response(input.session_spans, input.target_trace_id)

    if _matches_required_format(response_text):
        return EvaluatorOutput(value=1.0, label="Pass")
    return EvaluatorOutput(value=0.0, label="Fail", explanation="Response did not match expected format")
```

Other frameworks may name things differently — open one downloaded trace and check where your agent's reply text lives before writing the extractor.

The decorator handles parsing the raw Lambda event, extracting trace/span IDs, and serializing the response — write your check against typed `EvaluatorInput` and return a typed `EvaluatorOutput`.

#### Step D3.5: Unit-test the evaluator locally before deploying

The decorated `handler` is the Lambda entry point: it expects the raw Lambda event dict and returns a plain dict. Your undecorated function is available as `handler.__wrapped__` — call that with a typed `EvaluatorInput` to test the logic directly. No deploy, no AWS credentials needed:

```python
# test_evaluator.py
import json

from bedrock_agentcore.evaluation.custom_code_based_evaluators import EvaluatorInput
from lambda_function import handler  # the decorated function above


def _fake_input(response_text: str) -> EvaluatorInput:
    # A minimal agent span carrying the reply as a `gen_ai.choice` event, the shape real
    # Strands/ADOT spans use. evaluation_level is required.
    span = {
        "traceId": "t1",
        "spanId": "s1",
        "name": "invoke_agent Strands Agents",
        "attributes": {"gen_ai.operation.name": "invoke_agent"},
        "events": [{"name": "gen_ai.choice", "attributes": {"message": response_text}}],
    }
    return EvaluatorInput(evaluation_level="TRACE", session_spans=[span], target_trace_id="t1")


def test_matches_format():
    out = handler.__wrapped__(_fake_input('{"status": "ok"}'), None)
    assert out.value == 1.0


def test_rejects_free_text():
    out = handler.__wrapped__(_fake_input("Here's your answer: ok"), None)
    assert out.value == 0.0
    assert "did not match" in (out.explanation or "").lower()


def test_raw_lambda_event():
    # The decorated handler takes the event the eval service sends and returns a dict.
    event = {"evaluationLevel": "TRACE", "evaluationInput": {"sessionSpans": _fake_input("{}").session_spans}}
    assert handler(event, None)["value"] == 1.0
```

For higher-fidelity fixtures, use a real trace: after a single deploy+invoke, `agentcore traces runtime get <traceId> --output trace.json`, then pass `[r["@message"] for r in json.load(open("trace.json"))]` as `session_spans`.

Run with `uv run --with pytest pytest test_evaluator.py` from the evaluator directory. Iterate the logic until the fixtures pass. Only **then** deploy — the deploy step is about wiring the Lambda into AgentCore, not about debugging the check.

For **LLM-as-a-Judge** evaluators, there's no equivalent unit-test surface (the model call happens in the eval service), but you can iterate on the instructions against saved traces by dry-running the prompt in the Bedrock console or in a one-off script before `agentcore add evaluator llm-as-a-judge`.

#### Step D4: Deploy and run against a real trace

```bash
agentcore deploy
# The evaluator ID is the last / segment of the arn for resourceType=="evaluator" in agentcore status --json
agentcore eval ondemand evaluate --agent "$RUNTIME_ID" --evaluators <evaluator-id> --lookback-days 7
```

**Evaluator name rules:** start with a letter; letters, digits, and underscores only; max 48 chars including the `<project>_<target>_` prefix added on deploy (`FormatChecker` in project `MyProj` deploys as `MyProj_default_FormatChecker`). No hyphens.

---

### Path E: Regression suite (dataset + batch evaluation)

Use this when you have a set of scenarios with expected answers and want to replay them against every new version.

#### Step E1: Write the dataset

A dataset is JSONL — one example per line. For the `predefined` schema, each example has a `scenario_id`, one or more turns (sent in order in one session), and optional expectations:

```jsonl
{"scenario_id": "order_status", "turns": [{"input": "Where is my order 1234?", "expected_response": "Order 1234 shipped on Tuesday."}], "assertions": ["mentions the ship date"], "expected_trajectory": ["lookup_order"]}
{"scenario_id": "refund_policy", "turns": [{"input": "Can I return shoes after 40 days?"}], "assertions": ["states the 30-day return window"]}
```

Use `scenario_id`: `agentcore eval dataset create` rejects examples without it (`Required field 'scenario_id' is missing`). The local `--dataset ./file.jsonl` path also accepts `example_id`, but the same file then can't be uploaded. `expected_response` feeds trace-level evaluators like `Builtin.Correctness`; `assertions` and `expected_trajectory` (tool names) feed session-level evaluators. `simulated` datasets carry scenarios used to generate full conversations instead — the schema type can't be changed after creation.

#### Step E2: Run it

The quickest loop uses the local file directly:

```bash
agentcore eval ondemand simulate \
  --runtime-id "$RUNTIME_ID" \
  --dataset ./evals/regression.jsonl \
  --payload-template '{"prompt":"{input}"}' \
  --evaluators Builtin.Correctness Builtin.GoalSuccessRate
```

`--payload-template` is the request body your agent expects; `{input}` is replaced with each turn's input. The command invokes the Runtime per example, waits for ingestion (`--ingestion-wait-ms`, default 180000), scores the sessions, and prints JSON with `results` plus `examplesInvoked`, `examplesFailed`, and the `sessions` it created.

For a shared, versioned suite, upload the dataset and run it service-side:

```bash
agentcore eval dataset create --name support_regression --source file://evals/regression.jsonl --schema-type predefined
agentcore eval dataset publish --id <dataset-id>            # freezes the DRAFT; prints the datasetVersion

agentcore eval batch-evaluation simulate \
  --name support_regression_v42 \
  --runtime-id "$RUNTIME_ID" \
  --dataset <dataset-id> --dataset-version <version> \
  --payload-template '{"prompt":"{input}"}' \
  --evaluators Builtin.Correctness Builtin.GoalSuccessRate

agentcore eval batch-evaluation get --id <batch-evaluation-id>
```

Pass the `datasetVersion` that `publish` printed to `--dataset-version` (`dataset get` keeps showing the DRAFT). Edit a dataset with `agentcore eval dataset update --id <dataset-id> --file-path evals/regression.jsonl` (reconciles the DRAFT), then publish again. `--bearer-token` is needed for Runtimes using CUSTOM_JWT auth.

---

### Path F: A/B tests and recommendations

- **Recommendations** — `agentcore eval recommendation start` starts an asynchronous job that analyzes the agent's traces against an evaluator and proposes an improved system prompt (`SYSTEM_PROMPT_RECOMMENDATION`) or tool descriptions (`TOOL_DESCRIPTION_RECOMMENDATION`). `--help` doesn't show the config shape; a minimal system-prompt config that reads a deployed Runtime's traces from CloudWatch:

  ```json
  {
    "systemPromptRecommendationConfig": {
      "systemPrompt": { "text": "<the agent's current system prompt>" },
      "agentTraces": {
        "cloudwatchLogs": {
          "logGroupArns": ["arn:aws:logs:<region>:<account>:log-group:/aws/bedrock-agentcore/runtimes/<runtimeId>-DEFAULT"],
          "serviceNames": ["<project>_<target>_<RuntimeName>.DEFAULT"],
          "startTime": "2026-10-26T00:00:00Z",
          "endTime": "2026-10-26T12:00:00Z"
        }
      },
      "evaluationConfig": {
        "evaluators": [{ "evaluatorArn": "arn:aws:bedrock-agentcore:::evaluator/Builtin.GoalSuccessRate" }]
      }
    }
  }
  ```

  The service name is the `service.name` on the agent's spans (visible in any downloaded trace). Then:

  ```bash
  agentcore eval recommendation start --name prompt_rec_1 --type SYSTEM_PROMPT_RECOMMENDATION \
    --recommendation-config file://recommendation-config.json
  agentcore eval recommendation get --id <recommendation-id> --json   # poll until status is COMPLETED
  ```

  The time window must contain sessions from the deployed agent. For tool-description recommendations, a config-bundle source for the prompt, or inline spans, see [Start a system prompt recommendation](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/recommendations-system-prompt.html) and its sibling pages. Recommendations are LLM-generated — review and test them before applying.
- **Configuration bundles** — versioned bundles of component configuration (e.g. a system prompt). Declare one in the project with `agentcore add config-bundle --name <name> --components file://components.json`, or manage them service-side with `agentcore eval config-bundle ...`.
- **A/B tests** — split live Gateway traffic between a control and a treatment and compare per-evaluator metrics from online evals:
  - `agentcore eval ab-test config-based run --name <name> --gateway <gateway-id> --control '{"config-bundle":"<id>","bundle-version":"<v>"}' --treatment '{...}' --online-eval <online-eval-id>` — two config-bundle versions on one Gateway
  - `agentcore eval ab-test target-based run --name <name> --gateway <gateway-id> --control '{"gateway-target":"<name>","online-eval":"<id>"}' --treatment '{...}'` — two Gateway Targets, each with its own online eval
  - `--treatment-weight` (1–99, default 50) sets the split. Inspect with `agentcore eval ab-test get --id <id>`; `pause`, `resume`, `stop` (terminal), and `delete` (after stop) manage it.

**This skill doesn't take you through an A/B test end to end.** The commands above are real, but before `ab-test ... run` will work you need:

- A deployed **Gateway with an HTTP target pointing at the agent Runtime**, and clients sending traffic through the Gateway (traffic that calls the Runtime directly isn't split). See `agents-connect` if the agent isn't behind a Gateway yet.
- **Config-based tests:** one Runtime and two configuration-bundle versions (or two bundles), plus agent code that reads its configuration from the bundle the Gateway passes it, and one online-eval config on that Runtime.
- **Target-based tests:** two Gateway targets backed by separate Runtime endpoints or Runtimes, each with its own online-eval config.
- The `bedrock-agentcore` SDK 1.8+ in the agent (it tags spans with the experiment and variant), Transaction Search enabled, and evaluators that return a numeric value (a custom LLM-as-a-Judge evaluator needs a `numerical` rating scale).

The `components.json` shape for a bundle and how the agent reads the active bundle aren't covered by `--help`; follow [Run an A/B test with configuration bundles](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ab-testing-config-bundle.html) and the [A/B testing prerequisites](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/ab-testing-prereqs.html) for the end-to-end walkthrough.

---

## Troubleshooting

### "No telemetry found for agent" / no results

- Wait 30–90 seconds after invoking the agent — that's how long traces take to reach CloudWatch (there's no separate eval-indexing step beyond that). Poll `agentcore traces runtime list` until the session appears; its session ID can show as `-` at first
- For online-eval results, also wait for the session timeout: a session is only scored after it has been idle for `sessionTimeoutMinutes` (see Path B, Step B4)
- Confirm you passed the deployed Runtime or harness **ID**, not the project name
- Confirm the sessions came from the deployed agent — `agentcore dev` runs never reach CloudWatch
- Check that the runtime wasn't deployed with `"instrumentation": { "enableOtel": false }` and that Transaction Search is enabled (see Step 2)
- Widen the window: `--lookback-days 14` or `--lookback-days 30`

### "specify a session source"

- `agentcore eval ondemand evaluate` needs one of `--session-ids`, `--trace-id`, `--lookback-days`, or `--start-time`/`--end-time`

### Deploy fails after adding an LLM-as-a-Judge evaluator

- Usually the instructions: check the placeholders against the level table in Path D. The CLI accepts any text; the service rejects invalid placeholders at deploy.
- `temperature is deprecated for this model` (ValidationException at `CreateEvaluator`): the judge model rejects the evaluator's inference config. Change `config.llmAsAJudge.model` on the evaluator in `agentcore.json` to another model (e.g. `global.anthropic.claude-sonnet-4-5-20250929-v1:0`) and redeploy.

### Online eval config stuck in CREATING

- Run `agentcore status` to check the deployed state, or `agentcore eval online-eval get --id <online-eval-id>`
- Usually resolves within 30 seconds of deploy

### `remove evaluator` fails

- An online eval config in the project still references this evaluator
- Remove the online eval config first: `agentcore remove online-eval --name <name>`
- Then remove the evaluator: `agentcore remove evaluator --name <name>`, and `agentcore deploy`

### `add evaluator` / `add online-eval` fails on an existing project

- If `agentcore/agentcore.json` has `"version": 1`, it's a v0 project and `add` is blocked in compatibility mode. Commit first (`git add -A && git commit`): migrate refuses a dirty tree even to print the plan. Then run `agentcore migrate` to print the plan, show it to the developer, and only after they approve run `agentcore migrate --yes`.

## Cross-region inference (data residency)

Both built-in and LLM-as-a-Judge evaluators use **cross-region inference** by default. The data being evaluated stays in your primary region, but the inference call that runs the judge model may execute in another AWS region within the same geography (e.g., `us-east-1` → `us-east-2`/`us-west-2`; EU stays in EU).

There's no extra cost, and logs don't include the inference region. But if data-residency rules require pinning inference to a single region:

- **Built-in evaluators:** they're managed by AgentCore and use cross-region inference as-configured. If single-region inference is required, use a custom evaluator instead.
- **Custom LLM-as-a-Judge evaluators:** pin the model by choosing a region-specific model ID for `--model` instead of a cross-region inference profile ID. Check the docs for current single-region model IDs in your region.
- **Code-based evaluators:** not affected. The Lambda runs wherever you deployed it.

See [cross-region inference](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/cross-region-inference.html) for the current geography/region mapping rather than baking it in here — it expands across releases.

Evaluators, online evals, and config bundles are not available in China regions.

## Which eval command to use

Different tools for different workflows — developers confuse them.

| You want to... | Command | Where it runs |
|---|---|---|
| Score one session or trace from a recent run | `agentcore eval ondemand evaluate --session-ids <id>` (or `--trace-id`) | CLI, synchronous, against CloudWatch spans |
| Score the last N days and track drift | `agentcore eval ondemand evaluate --lookback-days 7`, or `agentcore eval batch-evaluation evaluate` for large windows | CLI (sync) / service (async job) |
| Run a curated benchmark / regression suite (CI/CD) | `agentcore eval ondemand simulate` or `agentcore eval batch-evaluation simulate` with a dataset | Invokes the deployed Runtime per example, then scores |
| Check production quality continuously | `agentcore add online-eval` | Platform, continuous sampling |
| Compare two configurations on live traffic | `agentcore eval ab-test ...` | Platform, via Gateway traffic split |

**Use `ondemand evaluate`** when you're iterating on an evaluator, investigating a specific regression, or gating on recent traffic. It's fast, cheap, and doesn't invoke the agent — it only scores existing traces.

**Use `simulate`** when you have a dataset of scenarios with expected responses / trajectories / assertions. It **invokes the agent** for each example, waits for telemetry ingestion once per run, then evaluates. Typical use: regression pack in CI before promoting a new version.

**Use online eval** for continuous production monitoring at a sampling rate — not the same as a benchmark.

## Output

- CLI commands to run evals or set up monitoring
- Quality gate script (for CI/CD path)
- Dataset and regression-run commands (for regression path)
- Evaluator config (for custom evaluator path)
- Interpretation of scores if reviewing existing results
