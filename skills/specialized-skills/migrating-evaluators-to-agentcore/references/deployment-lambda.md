# Deployment Path: Code-Based Lambda via CLI

> **Handler code and evaluator names are GENERATED — do not hand-write them.**
> `scripts/generate_handlers.py` produces the handler files (adapter wrappers for
> every DeepEval and RAGAS metric, custom and deterministic skeletons) plus
> `handlers/evaluators.json`; `scripts/names.py` produces valid names. The code
> samples below explain the patterns for review/debugging and for completing
> `TODO(EVAL-MIGRATION)` sections.
>
> **RAGAS packaging is also generated.** `migration.sh (framework="ragas")`
> resolves every dependency from PyPI against exact pins and runs
> `scripts/package_ragas_lambda.py` (PyPI pins,
> boto3/botocore exclusion via UV_OVERRIDE, datasets/langchain_community stub
> injection, Lambda-faithful self-test with a 250MB size gate). The self-test
> runs the whole packaging path locally, with no AWS calls, so a bundle problem
> surfaces before deployment.
>
> Failure modes, environment repair, and CLI fallbacks live in
> [deployment-lambda-troubleshooting.md](deployment-lambda-troubleshooting.md).

## Contents

- [When to Use](#when-to-use)
- [Priority: SDK Adapters First, Custom Handlers When Needed](#priority-sdk-adapters-first-custom-handlers-when-needed)
- [Fallback: Custom Handler (Rarely Needed)](#fallback-custom-handler-rarely-needed)
- [Prerequisites (Check in 1 Step Max)](#prerequisites-check-in-1-step-max)
- [Deployment Flow (migration.sh)](#deployment-flow-migrationsh)
- [Lambda Handler Gotchas](#lambda-handler-gotchas)
- [Evaluator ID Discovery](#evaluator-id-discovery)
- [Custom Handlers](#custom-handlers)
- [Handler Requirements](#handler-requirements)
- [Service Span Transformation (Critical for Handler Authors)](#service-span-transformation-critical-for-handler-authors)
- [Adapter Availability in Lambda (which adapters are published)](#adapter-availability-in-lambda-which-adapters-are-published)
- [Lambda Dependency Checklist](#lambda-dependency-checklist)
- [Post-Deploy Bundling Verification (catches CDK packaging failures)](#post-deploy-bundling-verification-catches-cdk-packaging-failures)
- [Handler Return Format (Required for all custom handlers)](#handler-return-format-required-for-all-custom-handlers)

## When to Use

Every supported DeepEval and RAGAS metric deploys as a Lambda (`classify.py` routes each
to `lambda_adapter`), because each one runs execution logic that an LLM cannot replicate:

| Metric Type | Examples | Why Lambda Required |
|---|---|---|
| Deterministic string/regex/schema | ExactMatch, PatternMatch, JsonCorrectness | `re.fullmatch()`, `model_validate_json()` — LLMs cannot reliably replicate |
| Multi-step pipelines (any framework) | DeepEval FaithfulnessMetric, AnswerRelevancyMetric, ContextualRelevancyMetric, BiasMetric, ToxicityMetric, RAGAS faithfulness/answer_relevancy | Multi-step claim extraction, NLI, embedding — cannot be approximated by single prompt |
| Tool-list arithmetic and averaged judges | DeepEval ToolCorrectnessMetric, RAGAS AnswerAccuracy/ContextRelevance/ResponseGroundedness | Partial credit over tool lists, or two judge prompts averaged — one prompt reproduces neither |

## Priority: SDK Adapters First, Custom Handlers When Needed

When an SDK adapter exists (`DeepEvalAdapter`, `RagasAdapter`):

- **Use the adapter** — it wraps the actual metric logic and avoids prompt drift.
- Deploy as Lambda handler using the adapter.

When NO adapter is available for a metric:

- **Author a custom Lambda handler** that implements the multi-step logic.
- The handler should be self-contained and replicate the original metric's pipeline.

### DeepEval adapter pattern (SDK wheel)

`bedrock-agentcore` ships the `third_party` adapters from **1.23.0** onward, so the
handler imports `DeepEvalAdapter` directly. The one requirement is an exact pin at or
past that release: the scaffold writes a floor (`bedrock-agentcore>=x.y`) which can
resolve to an older release where the adapter does not exist, and the Lambda then
fails at import — long after deploy reports success. `migration.sh` rewrites the floor
to the exact pin, and `verify_deps.py` re-checks it.
`migration.sh` also pins `strands-agents` to the RAGAS path's version and writes an
`overrides.txt` that drops `strands-agents-tools`, which `strands-agents-evals` pulls in
but no evaluator imports.

```python
# DeepEval: adapter from the pinned SDK wheel (the generated handler, condensed)
from bedrock_agentcore.evaluation.custom_code_based_evaluators import custom_code_based_evaluator
from bedrock_agentcore.evaluation.custom_code_based_evaluators.third_party.deepeval.adapter import DeepEvalAdapter
from deepeval.metrics import FaithfulnessMetric
from deepeval.models import AmazonBedrockModel

model = AmazonBedrockModel(model="us.anthropic.claude-sonnet-4-5-20250929-v1:0", region="us-east-1")

def _test_case(eval_input):
    ...  # map_spans(), then split the Context / Reference Answer / Metric Inputs sections

def _metric():
    return FaithfulnessMetric(model=model, async_mode=False)

@custom_code_based_evaluator()
def handler(eval_input, context=None):
    return DeepEvalAdapter(metric=_metric(), custom_mapper=_test_case)(eval_input, context)
```

Two parts of the generated handler matter here:

- **`custom_mapper=_test_case`.** The adapter's default mapping reads none of the
  sections the migrated client embeds in the first user message: it passes the whole
  message as `input` and leaves `retrieval_context` and `expected_output` empty. Context
  metrics (Faithfulness, Contextual*, Hallucination, a GEval over `CONTEXT`) then fail
  with `MISSING_REQUIRED_FIELD`, and every other metric judges an input the source never
  saw. `_test_case()` splits the query from the `Context` (a JSON chunk list becomes the
  `retrieval_context` list and `context`), `Reference Answer` (`expected_output`) and
  `Metric Inputs` sections. Metric Inputs may carry `tools_called`, `expected_tools`,
  `context`, `retrieval_context` and `expected_output`, and win over the rest; spans with
  no embedded sections map exactly as the default does.
- **A new metric per invocation.** A metric keeps state between `measure()` calls, and
  GEval caches the evaluation steps it generates, so one module-level instance would
  score every case with the first case's steps for as long as the Lambda stays warm.

`DAGMetric` (`dag=`) and `JsonCorrectnessMetric` (`expected_schema=`) take a Python
object that mapping.json cannot carry. Their handlers come with a
`TODO(EVAL-MIGRATION)` block: copy the object from the source script VERBATIM into
`_source_dag()` / `_source_expected_schema()` and delete the marker. Neither
`generate_migration_sh()` nor migration.sh deploys a handler that still has one.

A metric listed with `variants` (the source builds it with different arguments per
case) gets a `_VARIANTS` table of each variant's literal arguments, and builds the
metric with the variant the case names in its Metric Inputs,
`{"variants": {"<score_key>": "<name>"}}`. A case that names none, or an unknown one,
returns `MISSING_REQUIRED_FIELD`. The request only selects a variant: the pattern or
schema itself is fixed in the handler at generation. For a source object,
`_source_expected_schema(variant)` / `_source_dag(variant)` returns the one for each.

### RAGAS adapter pattern (PyPI pins + overrides)

RAGAS needs the same SDK pin, PLUS a dependency tree it never uses at runtime that
would exceed Lambda's 250MB limit. Solution: `package_ragas_lambda.py` writes exact
PyPI pins into pyproject and an `overrides.txt` that excludes `datasets`,
`langchain-community`, `networkx`, `scikit-network` and `diskcache` with an always-false
environment marker — uv replaces the requirement and never installs it. The handler
stubs the two ragas imports at module level:

```python
# RAGAS: adapter from the pinned SDK wheel, resolved from PyPI (the generated handler, condensed)
from bedrock_agentcore.evaluation.custom_code_based_evaluators import custom_code_based_evaluator
from bedrock_agentcore.evaluation.custom_code_based_evaluators.third_party.ragas import RagasAdapter
from ragas.metrics import Faithfulness
from langchain_aws import ChatBedrockConverse
from ragas.llms import LangchainLLMWrapper

eval_llm = LangchainLLMWrapper(ChatBedrockConverse(
    model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0", region_name="us-east-1",
))

def _fields(eval_input):
    ...  # map_spans(), then split the Context / Reference Answer / Metric Inputs sections

adapter = RagasAdapter(metric=Faithfulness(), custom_mapper=_fields, llm=eval_llm)

@custom_code_based_evaluator()
def handler(eval_input, context=None):
    return adapter(eval_input, context)
```

The adapter scores whatever sample fields `custom_mapper=_fields` returns:

- **Single-turn metrics.** Without a Metric Inputs section, `_fields()` returns exactly
  the fields the adapter's default mapping builds: the query, the response, the
  reference (`evaluationReferenceInputs`, then the embedded `Reference Answer`, then the
  assertions) and the retrieved contexts (tool results, then the embedded `Context`,
  where a JSON chunk list keeps its chunks). It then adds the Metric Inputs fields that
  no span carries (`rubrics`, `reference_contexts`, image lists, context IDs), which win.
- **Multi-turn metrics** (ToolCallAccuracy, ToolCallF1, AgentGoalAccuracy*,
  TopicAdherenceScore). `_fields()` builds the conversation from every message in the
  session: each user message, with the embedded sections stripped, becomes a human
  turn and each assistant message an AI turn with its tool calls. It reads the
  embedded reference by shape (a tool-call list, a topic list, or plain text). Metric
  Inputs may carry the whole conversation (`user_input`), the agent's `tools_called`
  (put on the last AI turn when no turn has any), `reference`, `reference_topics` and
  `reference_tool_calls`.

**Key difference:** both import the adapter from the same pinned SDK wheel. DeepEval
needs nothing else. RAGAS additionally needs `overrides.txt`, to keep its unused heavy
transitives out of the bundle.

## Fallback: Custom Handler (Rarely Needed)

`DeepEvalAdapter` covers every supported DeepEval metric, so a custom handler is
needed only for a metric no adapter supports (for example a hand-rolled
deterministic function — see `lambda_custom` in the routing table).

Do NOT write a custom handler to work around a metric `classify.py` marked
`path="unsupported"`. DeepEval's conversational metrics are unsupported in this
skill version by design; hand-rolling Turn extraction reintroduces exactly the
divergence the refusal exists to prevent.

## Prerequisites (Check in 1 Step Max)

```bash
node --version  # Need 20+
which agentcore || npm install -g @aws/agentcore@0.28.1
uname -m        # Check host architecture for platform mismatch detection
```

If Node.js missing:

1. `apt-get update && apt-get install -y nodejs npm`, then re-check `node --version`:
   the distro package is often v12, and the CDK steps (9-10) need 20+.
2. If it reports below v20, or apt-get fails: `mise install node@20.19.2` or
   `nvm install 20.19.2`
3. If all fail: STOP and inform user that Node.js is required for Lambda deployment.
   Do NOT fall back to LLM-as-a-Judge for Lambda-mandatory metrics.

## Deployment Flow (migration.sh)

**Generate the script with `scripts/deployer.generate_migration_sh()` — read the
signature carefully** (common errors: `TypeError: unexpected
keyword argument 'names'` / `missing 3 required positional arguments`):

```python
import sys, json
sys.path.insert(0, '<this skill\'s directory>')  # same path as $SKILL
from scripts.deployer import generate_migration_sh

names = json.load(open('names.json'))
entries = json.load(open('handlers/evaluators.json'))  # written by generate_handlers.py
evaluator_names = [(e['name'], e['level'], e['handler_file']) for e in entries]

result = generate_migration_sh(
    evaluator_names,          # list of (name, level, handler_filename) tuples
    'handlers',               # handler_dir
    'deploy',                 # output_dir
    project_name=names['project_name'],
    framework=names['framework'],
)
```

Deployed evaluators get `--timeout 300` (multi-step RAGAS metrics make 2+ LLM
calls per sample; the CLI's 120s default is insufficient).

1. Node 20+ activation
2. TypeScript pinning: `npm install typescript@5.9.3`
3. `agentcore create --project-name {PascalTask}{UUID4} --output-dir $DIR --skip-install --json`
   **`--skip-install` is REQUIRED** — without it, npm install hangs.
   **Project name follows `{PascalTask}{UUID4}` format** (e.g., `RagPipelineA1B2`)
   — PascalCase + 4 uppercase hex chars, pattern: `^[A-Za-z][A-Za-z0-9]{0,35}$`.
   Evaluator names follow `{PascalTask}{UUID4}_{framework}_{metric}`.
4. AWS target config (`aws-targets.json`)
5. `agentcore add evaluator` for each evaluator
6. Install handler code
7. **MANDATORY: Patch ALL pyproject.toml immediately** (scaffold defaults are too old).
   `generate_migration_sh` emits this for you; the snippet below is the manual
   fallback and applies to **DeepEval only** — RAGAS pyprojects are rewritten
   wholesale by `scripts/package_ragas_lambda.py`, so do not per-dep patch them.

   ```bash
   for TOML in $(find $DIR -name "pyproject.toml" -path "*/app/*/pyproject.toml"); do
     # A floor can resolve below 1.23.0; rewrite it, allowing any operator and spacing.
     sed -E -i "s|bedrock-agentcore[[:space:]]*[><=!~][^\"']*|bedrock-agentcore==1.23.0|" "$TOML"
     # Quoted requirement, not the bare name: app dirs are named after their metric, so
     # `grep -q deepeval` matches the project's own name and skips the real dependency.
     for DEP in requests==2.34.2 deepeval==4.2.3 aiobotocore==3.9.1 strands-agents-evals==1.2.0; do
       NAME=${DEP%%==*}
       grep -qE "\"$NAME[\"=<>!~ ]" "$TOML" ||
         sed -i "s/dependencies = \[/dependencies = [\n  \"$DEP\",/" "$TOML"
     done
   done
   ```

   `scripts/verify_deps.py --framework deepeval` applies the same quoted-requirement
   check and repairs anything missed, so run it rather than trusting the loop.
8. **MANDATORY: Patch CDK platform if host is x86_64** (`uname -m` = x86_64):

   ```bash
   PYTHON_JS=$(find $DIR -path "*/agentcore-cdk/dist/lib/packaging/python.js")
   if [ -n "$PYTHON_JS" ]; then
     sed -i "s/aarch64-manylinux/x86_64-manylinux/g" "$PYTHON_JS"
   fi
   ```

9. CDK dependencies: do NOT run a bare `npm install` in `agentcore/cdk` — the scaffold
   declares `~` ranges and ships no lockfile. Re-run `bash deploy/migration.sh` instead
   (completed steps are skipped): its step 11 rewrites `agentcore/cdk/package.json` to
   the exact versions in `deployer.CDK_NPM_PINS`, drops the scaffold's unused
   `jest`/`ts-jest`/`prettier`, installs with `npm ci` from the skill's lockfile
   (`assets/cdk-package-lock.json`, which pins every transitive dependency and its sha512),
   and disables the CLI's managed-dependency sync for the deploy so the CLI does not
   re-float them.
10. Refuses to continue while any handler still has a `TODO(EVAL-MIGRATION)` block.
11. `timeout 600 agentcore deploy --target default --yes --verbose`
    CDK deploy normally takes 2-4 minutes. NEVER use timeout < 300s.
    If it exceeds 600s, something is stuck (CF waiting on a conflicting stack).
12. After the deploy, sets 30-day retention on each `/aws/lambda/{project}-eval-{evaluator}`
    log group. The stack creates these groups itself (the scaffold's `cdk.json` sets
    `@aws-cdk/aws-lambda:useCdkManagedLogGroup`), with two-year retention and no CMK.
    Export `EVAL_MIGRATION_LOGS_KMS_KEY_ARN` first to associate a CMK with each group;
    nothing has invoked the Lambdas yet, so the key covers every log they write. Without
    it the groups keep the AWS-owned key and the script says so. Do NOT create these
    groups before the deploy: CloudFormation cannot create a log group that already
    exists, so the stack rolls back.

## Lambda Handler Gotchas

| Issue | Symptom | Fix |
|---|---|---|
| DEEPEVAL_HOME read-only | `OSError: Read-only file system: '/.deepeval'` | Set BOTH `DEEPEVAL_HOME` AND `DEEPEVAL_CACHE_FOLDER` to `/tmp/.deepeval` BEFORE imports |
| SDK version too old | `ImportError: cannot import name 'DeepEvalAdapter'` | Pin `bedrock-agentcore==1.23.0` in pyproject.toml — the adapters ship from 1.23.0 |
| `third_party` missing | `ModuleNotFoundError: No module named '...third_party'` | Pin `bedrock-agentcore==1.23.0`; a leftover `>=` floor can resolve below it |
| pydantic_core mismatch | `ImportError: ... pydantic_core` | Use `--platform manylinux2014_x86_64` when bundling |
| No OpenAI key in Lambda | DeepEval tries GPT by default | Configure `AmazonBedrockModel` from deepeval for Bedrock access |
| TypeScript version | CDK synth fails | Pin `typescript@5.9.3` |
| CF stack conflicts | `ROLLBACK_COMPLETE` or shared stack errors | `aws cloudformation delete-stack --stack-name <stack> --region <region>`, wait for it to finish, delete the `/aws/lambda/<project>-eval-*` log groups it left behind (the CDK keeps them), then re-run `bash deploy/migration.sh` |

## Evaluator ID Discovery

After CLI deployment, evaluator IDs follow format: `{project}_{evaluator-name}-{randomSuffix}`
(the CLI prepends the project; evaluator names themselves are `{framework}_{metric}`).

**The ONE safe resolution story (generated scripts implement this):**

- **Lambda evaluators (CLI-deployed):** resolve at runtime by the PROJECT-SCOPED
  fragment `{project}_{evaluator-name}` — the project's UUID suffix makes it
  collision-proof. `scripts/adot.py::resolve_evaluator_id` prefers exact-prefix
  matches. NEVER resolve by the bare evaluator name (`ragas_faithfulness`) —
  it matches stale evaluators from other runs and concurrent deployments.
- **LLM-as-a-Judge evaluators (SDK-created):** their IDs are NOT project-prefixed.
  Paste the exact ID returned by `create_evaluator_and_wait()` into the
  generated script's `EVALUATORS` dict — the script refuses to run without it.
- **Builtin.***: fixed IDs, no resolution needed.

## Custom Handlers

**DeepEvalAdapter is the primary path** for every supported DeepEval metric
(`LLMTestCase`). Custom handlers are only needed for metrics no adapter supports,
such as hand-rolled deterministic functions.

## Handler Requirements

- Handlers must be fully self-contained (this skill's scripts are not on the Lambda)
- ADOT spans require `scope` and `resource` fields
- Lambda `pyproject.toml` must include `requests==2.34.2` explicitly (exact pin,
  matching the dep loop above; a floor would let an unreviewed release onto the Lambda)
- Set env vars at the TOP of handler, before any framework imports
- Judge models take `model=` (NOT `model_name=`) and an explicit `region=` matching the
  deploy region; handlers and the IAM policy are generated per region
- DeepEval metrics need `async_mode=False` (the Lambda event loop conflicts otherwise)
- Lambda timeout 300s and boto3 `read_timeout=300`

## Service Span Transformation (Critical for Handler Authors)

When AgentCore invokes your Lambda, the service TRANSFORMS ADOT spans before delivery.
The handler does NOT receive the same format you sent to `_dp_client.evaluate()`.

**What changes:**

- Top-level `body` field does NOT exist — log record merged into `span_events[0].body`
- Only 1 span passed (not separate span + log record documents)
- Field names are snake_case: `trace_id`, `span_id`, `session_id`
- Span has normalized keys: `name`, `kind`, `source`, `attributes`, `events`, `span_events`, `status`

**Correct extraction pattern:**

```python
for span in eval_input.session_spans:
    body = None
    if isinstance(span, dict):
        for event in span.get("span_events", []):
            if isinstance(event, dict) and "body" in event:
                body = event["body"]
                break
    # body = {"input": {"messages": [...]}, "output": {"messages": [...]}}
```

**WRONG (will always be None in Lambda):**

```python
body = span.get("body")  # Service strips this field
```

`DeepEvalAdapter` handles this extraction internally.

## Adapter Availability in Lambda (which adapters are published)

`bedrock-agentcore==1.23.0` on PyPI ships both adapters this skill uses —
`deepeval` and `ragas`. 1.23.0 is the FIRST release carrying `ragas`; earlier
releases, including 1.22.0, do not.

The wheel contains other adapters as well. This skill does not generate handlers for
them and does not test them, so treat only `deepeval` and `ragas` as supported here;
finding another in the wheel is not evidence it works through this migration path.
Verify a wheel before trusting it:

```bash
python3 -c "import zipfile,sys;print([n for n in zipfile.ZipFile(sys.argv[1]).namelist() if 'third_party/' in n])" <wheel>
```

**DeepEvalAdapter — use an exact release pin. No git URL, no fork.**

```bash
sed -i 's|"bedrock-agentcore>=.*"|"bedrock-agentcore==1.23.0"|' "$TOML"
```

An exact pin (not `>=`) does two jobs: it keeps an unreviewed future version out of
the customer's Lambda, and it stops the floor resolving *downward* to a release
without `third_party`, which surfaces as `ImportError: No module named
'...third_party'` at invoke time rather than at deploy.

**RagasAdapter ships from 1.23.0.** `bedrock-agentcore==1.23.0` is pinned in pyproject
and resolves from PyPI like every other dependency.

Since nothing is built from source, **leave CDK's `--only-binary :all:`
constraint in place.** Every dependency the bundle needs is already a wheel on PyPI.
Relaxing the constraint would let uv build arbitrary sdists at bundle time for no
benefit — and the one metric that would need it, `RougeScore`, is refused at
classification time instead.

`GenericGenAISessionMapper` is a **strands-evals** symbol, not a
`bedrock-agentcore` one, and it ships in the published `strands-agents-evals`
release — it never required a fork.
## Lambda Dependency Checklist

The `sed` commands that patch pyprojects can fail silently, so the generated
`migration.sh` runs the verification tool ITSELF, immediately before its deploy
step, and stops on anything it cannot auto-fix — fix the reported issue and
re-run migration.sh. Run the tool by hand only on the manual fallback path above:

```bash
python3 $SKILL/scripts/verify_deps.py \
    --deploy-dir deploy/deploy_workspace/<ProjectName> \
    --framework deepeval   # or ragas (checks handlers present + overrides.txt)
```

Skipping verification on the manual path hits the error chain
`ModuleNotFoundError: deepeval` → fix → `ModuleNotFoundError: strands_evals` —
costing 10-30 steps.

**Why the `sed` patching fails silently:**

- The `deepeval==4.2.3` insertion matches on the project name `deepeval_*` instead of the dependencies section
- `strands-agents-evals` may already be present, preventing the second `sed`

**Manual check (fallback path only):** before a manual `agentcore deploy`,
directly verify each pyproject.toml contains ALL required deps:

```
deepeval==4.2.3
strands-agents-evals==1.2.0
bedrock-agentcore==1.23.0
```

All three are published PyPI releases — no git URLs anywhere. Pin exactly, not
`>=`: an SDK floor can resolve below 1.23.0, where the adapters do not exist,
and a deepeval floor resolves to LATEST, so the Lambda judges with different
metric code than the baseline ran and the divergence gate reads the version
skew as a mapping bug. The RAGAS path uses the same SDK pin, resolved from PyPI.
If any are missing, write the pyproject.toml directly — do NOT retry sed.

## Post-Deploy Bundling Verification (catches CDK packaging failures)

After `agentcore deploy` succeeds, the Lambda may STILL fail at runtime if CDK's
bundler failed to install dependencies (pyproject.toml lists them, but `uv pip`
inside CDK can silently skip packages due to platform/binary constraints).

**Immediately after deploy, run the smoke test:**

```bash
python3 $SKILL/scripts/smoke_test_lambda.py --project <ProjectName> --all
```

**If it reports `BUNDLING FAILED: No module named ...`:** Fix with
`update_function_code()` — download the Lambda zip,
`pip install "<missing_pkg>==<version>" -t /tmp/lambda_pkg/` using the exact version
pinned in `scripts/deployer.py` or `scripts/package_ragas_lambda.py`, merge and
re-upload. If the missing package is not one of those pins, do not hot-patch it: add
it to the evaluator's `pyproject.toml` with an exact `==` pin and re-run `migration.sh`.

**Do NOT spend steps debugging evaluator IDs, permissions, or the CLI if the Lambda
cannot import its dependencies.** Check CloudWatch logs
(`/aws/lambda/<FunctionName>`) FIRST on any invoke failure.

## Handler Return Format (Required for all custom handlers)

Lambda handlers MUST return an `EvaluatorOutput` carrying BOTH `value` AND `label`.
The field names are `value`, `label`, `explanation` — and `EvaluatorOutput` is a
Pydantic v2 model that sets no `extra` policy, so the default applies and **any other
keyword is accepted and silently discarded**. That makes every mistake here quiet rather than loud.

```python
from bedrock_agentcore.evaluation.custom_code_based_evaluators import EvaluatorOutput

# WRONG — a plain dict. The service reads no `value`, returns `value: null`, and the
# client falls back to label-based scoring, so every metric comes back 1.0.
return {"score": 0.85, "label": "Pass", "reason": "..."}

# WRONG — right type, wrong keywords. `score=` and `reason=` are discarded as unknown
# fields: value stays None (→ all 1.0) and explanation stays None.
return EvaluatorOutput(score=0.85, label="Pass", reason="...")

# CORRECT — value, label, explanation.
return EvaluatorOutput(
    value=score,
    label="Pass" if score >= threshold else "Fail",
    explanation="...",
)
```

Handlers from `generate_handlers.py` already do this. If you edit one by hand, keep all
three fields. The adapter-based handlers (`DeepEvalAdapter`/`RagasAdapter`) construct the
`EvaluatorOutput` internally — only the custom and deterministic skeletons build it directly.

### Pre-Deploy Handler Fixes (DO THESE before running migration.sh)

Inspect generated handlers and apply known fixes BEFORE deploying. Discovering
these bugs post-deploy wastes 10+ steps on redeploy cycles.

1. **AnswerCorrectness** (RAGAS): handled by `generate_handlers.py`, which passes
   `embeddings=` to the metric constructor. RAGAS builds the `AnswerSimilarity` sub-metric
   in `__post_init__`, so embeddings assigned afterwards — as `RagasAdapter` does — arrive
   too late and the sub-metric runs without them. Nothing to edit; if a hand-written handler
   shows this, construct the metric with `embeddings=eval_embeddings` rather than patching
   `metric.answer_similarity` after the fact.

2. **Multi-turn metrics need no manual fix** (ToolCallAccuracy, ToolCallF1,
   AgentGoalAccuracy*, TopicAdherenceScore). The RagasAdapter scores them with the
   metric's own `multi_turn_score()`, and the generated `_fields()` builds the
   conversation from every message in the session, so keep these evaluators at
   SESSION level.

3. **Custom handlers** (non-adapter): Must return `EvaluatorOutput(value=...)`, not a dict:

   ```python
   from bedrock_agentcore.evaluation.custom_code_based_evaluators import EvaluatorOutput
   return EvaluatorOutput(
       value=score, label="Pass" if score >= 0.5 else "Fail", explanation=reason
   )
   ```

   **The fields are `value=` and `explanation=`, NOT `score=` and `reason=`.** Because
   Pydantic discards unknown fields by default, a wrong keyword raises nothing.
   `score=` leaves `value: null`, so the client falls back to label-based scoring and every
   metric reads 1.0; `reason=` leaves `explanation: null`, so the service gets no rationale.

4. **`--level` needs no manual check.** `generate_migration_sh()` validates every
   `(name, level, handler_file)` tuple and raises before writing the script, so a
   swapped tuple or a bad level fails immediately rather than deploying a
   SESSION-scoped evaluator at `TRACE`. If you see that ValueError, fix the tuple
   order or the manifest's `level` field — do not patch migration.sh.

5. **Lambda dependencies need no manual step.** `migration.sh` runs
   `scripts/verify_deps.py` itself immediately before its deploy step, and auto-fixes
   what it can. Run it by hand only on the CLI-broken fallback path.
