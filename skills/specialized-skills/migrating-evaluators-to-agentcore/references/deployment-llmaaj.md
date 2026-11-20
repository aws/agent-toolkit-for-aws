# Deployment Path: Custom LLM-as-a-Judge via SDK

## Contents

- [When to Use](#when-to-use)
- [When NOT to Use](#when-not-to-use)
- [Deployment via SDK](#deployment-via-sdk)
- [Schema Notes](#schema-notes)
- [Prompt Design by Metric Type](#prompt-design-by-metric-type)
- [Score Extraction](#score-extraction)
- [Test Case Count and Divergence Sensitivity](#test-case-count-and-divergence-sensitivity)
- [Gotchas](#gotchas)

## When to Use

Deploy as LLM-as-a-Judge when the metric IS IMPLEMENTED as a single-prompt evaluation.
Do NOT use this path to approximate multi-step metrics with a single prompt unless
the metric's actual implementation is a single LLM call.

| Metric Type | Examples | Why LLM-as-a-Judge Is Correct |
|---|---|---|
| Phoenix classifiers (all) | Conciseness, Correctness, Faithfulness, Refusal | Implemented as single-prompt binary classifiers |
| Strands OutputEvaluator | OutputEvaluator(rubric="...") | Single LLM call with custom rubric |
| Custom evaluators without SDK adapter | Any metric where no `*Adapter` exists AND the logic is single-prompt | When you must — but verify the metric's actual implementation first |

## When NOT to Use

No DeepEval or RAGAS metric uses this path: each runs its own code through its SDK
adapter in Lambda, and `generate_handlers.py` refuses one routed to `llm_judge`.

- **Deterministic metrics** (ExactMatch, PatternMatch, JsonCorrectness) — LLMs
  cannot reliably replicate `re.fullmatch()` or `model_validate_json()`. Use Lambda.
- **DeepEval ToolCorrectnessMetric** — arithmetic over the expected and called tools,
  with partial credit a fixed rating scale cannot express (2 of 3 tools is 0.667).
  Use Lambda.
- **RAGAS NVIDIA metrics** (AnswerAccuracy, ContextRelevance, ResponseGroundedness) —
  each averages two judge prompts, with retries and fixed answers for edge cases, which
  one prompt cannot replicate. Use `RagasAdapter` Lambda.
- **DAGMetric** — a graph of LLM judgement nodes, each its own call, which one prompt
  cannot replicate. Use Lambda.
- **Multi-step NLI pipelines** (FaithfulnessMetric, AnswerRelevancyMetric, ContextualRelevancyMetric,
  BiasMetric, ToxicityMetric, Hallucination, Summarization) — multi-step pipelines
  (claim extraction → NLI → aggregation). Use `DeepEvalAdapter` Lambda deployment.
- **GEval** — uses internal multi-step Chain-of-Thought that a
  single prompt cannot replicate. Deploy as Lambda with `DeepEvalAdapter` for ≈0
  divergence. Do NOT fall back to LLM-as-a-Judge.
- **DeepEval multi-turn conversational** (ConversationalGEval, GoalAccuracy,
  RoleAdherence, ToolUse, ConversationCompleteness, KnowledgeRetention,
  TopicAdherence, Turn*) — NOT SUPPORTED in this version. `classify.py` marks them
  `path="unsupported"`; report them as out of scope rather than approximating them
  with an LLM-as-a-Judge. RAGAS multi-turn metrics are unaffected.
- **RAGAS multi-step/embedding metrics** (Faithfulness, AnswerRelevancy, Context*,
  FactualCorrectness, SemanticSimilarity, etc.) — use `RagasAdapter` Lambda.

**Rule of thumb:** If you're not certain whether a metric is single-prompt or multi-step,
read its source code. If it makes multiple LLM calls or has claim/statement extraction
logic, it MUST go through Lambda with an SDK adapter.

## Deployment via SDK

Use `scripts/names.py` to generate evaluator names, then deploy:

```python
import sys
from bedrock_agentcore.evaluation import EvaluationClient
sys.path.insert(0, "<this skill's directory>")  # same path as $SKILL
from scripts.deployer import judge_model_id  # region-prefixed profile, not a us.* literal

client = EvaluationClient(region_name=region)  # region = the deploy region

evaluator = client.create_evaluator_and_wait(
    evaluatorName=evaluator_name,  # from names.json
    level="TRACE",
    evaluatorConfig={
        "llmAsAJudge": {
            "instructions": "...(prompt with {context} and {assistant_turn})...",
            "ratingScale": {
                "categorical": [
                    {"label": "correct", "definition": "The output meets the criteria"},
                    {"label": "incorrect", "definition": "The output does not meet criteria"},
                ]
            },
            "modelConfig": {
                "bedrockEvaluatorModelConfig": {
                    "modelId": judge_model_id(region),
                }
            },
        }
    },
)
EVALUATOR_ID = evaluator["evaluatorId"]
```

## Schema Notes

- `instructions` (NOT `customInstructions`) — the prompt text with placeholders
- `modelConfig.bedrockEvaluatorModelConfig.modelId` (NOT top-level `model`)
- `ratingScale.categorical`: list of `{"label": str, "definition": str}`
- `ratingScale.numerical`: list of `{"value": float, "label": str, "definition": str}`,
  `value` ≥ 0
- `level=` (NOT `evaluationLevel=`) — the SDK kwarg is `level`
- Only `{context}`, `{assistant_turn}`, `{tool_turn}` placeholders allowed
- Escape curly braces in JSON examples: `{{` and `}}`

## Prompt Design by Metric Type

### Phoenix classifiers — Extract EXACT prompt

```python
from phoenix.evals.metrics.{name} import {NAME}_CLASSIFICATION_EVALUATOR_CONFIG
config = {NAME}_CLASSIFICATION_EVALUATOR_CONFIG
print(config.name)      # label name
print(config.choices)   # score mapping: {'concise': 1.0, 'verbose': 0.0}
for m in config.messages:
    print(m.role, m.content)  # the actual prompt template
```

Do NOT paraphrase. Use verbatim.

**Placeholder adaptation must not drop evidence.** Phoenix templates often carry more
placeholders than AgentCore allows — `{{input}}`, `{{tool_call}}`, `{{tool_result}}`,
`{{output}}` versus only `{context}`, `{assistant_turn}`, `{tool_turn}`. Every original
placeholder must land somewhere: embed the extras into `{context}` with labels the
prompt text can reference, e.g.

```
[User Query] ...
[Tool Call] ...
[Tool Result] ...
```

and keep the prompt's references to them intact. A judge whose tool fields were
dropped cannot see tool behavior, so it scores "correct" whenever the output text
looks plausible — the signature is a migrated judge saturating at 1.0 while the
original consistently docks tool-misuse cases. That divergence is this adaptation
error, not judge nondeterminism.

### Prompt extraction rule (ALL frameworks)

- **Phoenix:** Extract from `{NAME}_CLASSIFICATION_EVALUATOR_CONFIG.messages`
- **Strands OutputEvaluator:** Extract the `rubric` parameter

The agent's job is to FIND and COPY the prompt, never to rewrite or "improve" it.

### Fidelity rule: what may and may not change

Once the source prompt is recovered, the deployed evaluator asks the judge exactly what the
original asked. Three parts of the config, three different rules.

**`instructions` — byte-identical to the source, with two exceptions, and nothing else.**
The exceptions are forced by the API, not chosen: substituting the placeholder tokens for the
three AgentCore allows, and packing any further source fields into `{context}` under labels
the prompt body still references. Every field the original judged with must still reach the
judge. Beyond that, no additions, no reworded sentences, no clarifications, no defaults, no
examples. If the prompt was recovered and all fields arrive, `instructions` is finished and
divergence is not a reason to revisit it.

**`ratingScale` labels and their order — from the source's own mapping.** Take the labels
from the source (Phoenix `config.choices`, the `rubric`'s scale) and order them so the
positional scoring reproduces the source's scores, best first. Never reorder labels to move
scores, and never add or drop a label the source does not have.

**`definition` — required by the API, absent from every source.** `CategoricalScaleDefinition`
requires both `label` and `definition`, while Phoenix supplies only a label-to-score mapping,
so this text has to be written. It is the one place new wording reaches the judge, so keep it
inert: say what the label *means*, in terms of the label itself. It must not say how to
decide, must not supply a default or tie-break, must not name a condition or threshold, and
must not reference the input, the context or the response. "The response is concise" is fine.
"Respond concise unless the response exceeds two sentences" is a decision rule, and changes
what is being measured.

### One evaluator per metric — never deploy a second version

The evaluator name comes from `names.json` and is used exactly as written. Do not append
`_v2`, `_fixed`, `_strict` or any other suffix, and do not create a second evaluator for the
same metric. To correct a deployed evaluator — wrong label order, a field that did not reach
`{context}`, the wrong `level` — call `UpdateEvaluator` with the existing `evaluatorId` and a
corrected `evaluatorConfig`. Creating a second name is never necessary, and it breaks score
resolution: the client looks the evaluator up by the `{project}_{evaluator_name}` fragment,
and a suffixed name contains that fragment too, so both versions prefix-match and which one
wins depends on `list_evaluators` ordering. The scores then come from an arbitrary one of the
two. A corrected evaluator keeps its name; only its config changes.

## Score Extraction

A categorical ratingScale returns `{"label": "well_coordinated", "value": null}`.
Labels are author-chosen, so do NOT hand-write a label table: `extract_score`
(inlined from `scripts/adot.py`) derives the mapping from the evaluator's own
deployed ratingScale via `fetch_label_scores`, and falls back to a table of
well-known labels when `GetEvaluator` is not permitted.

**Order categorical labels best-first.** The i-th of N labels scores
`(N-1-i)/(N-1)`, so `["well_coordinated", "poorly_coordinated"]` gives 1.0/0.0.
A two-label scale listed worst-first is detected and raises rather than
silently inverting every score.

An unresolvable label raises. Never map an unknown label to 0.0 — a fabricated
score silently corrupts the divergence comparison it feeds.

## Test Case Count and Divergence Sensitivity

**Use the customer's test cases as-is — never add, replace or reword one, and never drop a
case to improve a score.** Comparing both evaluators on the customer's own data is the whole
point; changing the data changes the measurement rather than the migration. A runtime subset is
the one exception, under the conditions in SKILL.md's Core Invariants: same subset on both
sides, count recorded in `summary.json`.

The case count is therefore an observation, not a requirement. It tells you how much a single
judge disagreement is worth, since a binary evaluator's mean moves in steps of `1/n`:

| Cases | One case flipping | Against the 0.1 budget |
|---|---|---|
| 4 | 0.25 | fails on its own |
| 5 | 0.20 | fails on its own |
| 10 | 0.10 | exactly at the budget |
| 12 | 0.083 | within budget |

Below about 11 binary cases, any single flip exceeds the budget, so expect an occasional
failure that no amount of fixing will remove — and say so in `summary.json` with the per-case
scores rather than touching the fixture. A multi-point scale moves in smaller steps and
tolerates more. If a customer's fixture is too small to measure reliably, report that as a
finding; it is not yours to enlarge.

## Gotchas

| Agent might think... | But actually... | Instead... |
|---|---|---|
| "I can map `OutputEvaluator` to a builtin" | Generic LLM-as-a-Judge with custom rubric | Deploy as custom LLM-as-a-Judge via SDK |
| "I can use `{input}` placeholder in custom instructions" | Only `{context}`, `{assistant_turn}`, `{tool_turn}` allowed | Use allowed placeholders; embed other data in instructions text |
| "I'll paraphrase the Phoenix prompt to be clearer" | Prompt wording changes alter judge behavior unpredictably | Extract and use the EXACT prompt text verbatim |
| "Divergence is still >0.1, so I'll add a line telling the judge how to decide" | That tunes the judge until it agrees, which fits the instrument to the measurement. The divergence was real and is now hidden | Leave a recovered prompt alone. Confirm every source field reaches `{context}`; if it does, report inherent |
| "I'll deploy a `_v2` with the corrected config" | A suffixed name still contains the `{project}_{evaluator_name}` fragment, so both versions prefix-match and score resolution picks an arbitrary one | `UpdateEvaluator` on the existing `evaluatorId`. The name from `names.json` never changes |
| "The source has no definition text, so I'll describe when to pick each label" | A definition that names conditions is a decision rule, and the source never gave the judge one | Define the label in terms of itself ("the response is concise"), not when to apply it |
| "GEval is a single-LLM-call metric, LLM-as-a-Judge works" | GEval uses internal multi-step CoT | Deploy as Lambda — NO fallback to LLM-as-a-Judge |
