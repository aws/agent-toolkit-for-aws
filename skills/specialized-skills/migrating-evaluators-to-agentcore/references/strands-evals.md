# Strands Evals → AgentCore Migration Reference

> This mapping is encoded in `scripts/classify.py` (STRANDS_BUILTIN) — run the
> classifier instead of applying the table by hand. The table below is the
> human-readable reference; if they ever disagree, classify.py is the source
> of truth and this file has drifted.

## Contents

- [Builtin Mapping Table (NO deployment needed)](#builtin-mapping-table-no-deployment-needed)
- [OutputEvaluator → Custom LLM-as-a-Judge](#outputevaluator--custom-llm-as-a-judge)
- [Code Template: Strands Evals All-in-One](#code-template-strands-evals-all-in-one)
- [Tracing Replacement: Langfuse → AgentCore (Strands agents)](#tracing-replacement-langfuse--agentcore-strands-agents)
- [Score Extraction by Level](#score-extraction-by-level)
- [Known Scoring Differences](#known-scoring-differences)

## Builtin Mapping Table (NO deployment needed)

| Strands Evals Evaluator | AgentCore Builtin ID | Level |
|---|---|---|
| `CoherenceEvaluator` | `Builtin.Coherence` | TRACE |
| `ConcisenessEvaluator` | `Builtin.Conciseness` | TRACE |
| `CorrectnessEvaluator` | `Builtin.Correctness` | TRACE |
| `FaithfulnessEvaluator` | `Builtin.Faithfulness` | TRACE |
| `GoalSuccessRateEvaluator` | `Builtin.GoalSuccessRate` | SESSION |
| `HarmfulnessEvaluator` | `Builtin.Harmfulness` | TRACE |
| `HelpfulnessEvaluator` | `Builtin.Helpfulness` | TRACE |
| `InstructionFollowingEvaluator` | `Builtin.InstructionFollowing` | TRACE |
| `RefusalEvaluator` | `Builtin.Refusal` | TRACE |
| `ResponseRelevanceEvaluator` | `Builtin.ResponseRelevance` | TRACE |
| `StereotypingEvaluator` | `Builtin.Stereotyping` | TRACE |
| `ToolParameterAccuracyEvaluator` | `Builtin.ToolParameterAccuracy` | TOOL_CALL |
| `ToolSelectionAccuracyEvaluator` | `Builtin.ToolSelectionAccuracy` | TOOL_CALL |

## OutputEvaluator → Custom LLM-as-a-Judge

`OutputEvaluator(rubric=...)` does NOT map to any builtin. Deploy as custom evaluator:

```python
from bedrock_agentcore.evaluation import EvaluationClient
from deployer import judge_model_id  # region-prefixed profile, not a us.* literal

client = EvaluationClient(region_name=region)  # region = the deploy region
evaluator = client.create_evaluator_and_wait(
    evaluatorName="custom_context_relevance",
    level="TRACE",
    evaluatorConfig={
        "llmAsAJudge": {
            "instructions": rubric_text + "\n\n## Conversation record\n{context}\n\n## Assistant Output\n{assistant_turn}",
            "ratingScale": {
                "numerical": [
                    {"value": 0, "label": "Not Relevant", "definition": "The response does not address the query"},
                    {"value": 1, "label": "Partially Relevant", "definition": "The response partially addresses the query"},
                    {"value": 2, "label": "Fully Relevant", "definition": "The response fully addresses the query"},
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

**Detection rule:** If source uses `OutputEvaluator` (not a named evaluator), extract
the rubric text and deploy as LLM-as-a-Judge. Only placeholders allowed:
`{context}`, `{assistant_turn}`, `{tool_turn}`.

## Code Template: Strands Evals All-in-One

**Illustrative only — do not copy this as your client script.** Generate the client with
`scripts/generate_client_script.py`, as SKILL.md Step 3 requires: it emits the `mean_scores`
shape the Step 6 check and the verifier both read, raises on evaluator errors instead of
recording a silent 0.0, and handles trace-pinning. What is worth reading here is the
Strands-specific middle: the in-memory span exporter, the `session.id` trace attributes, and
`convert_strands_to_adot`. Everything around it the generator does better.

```python
"""
Migrated evaluation: {EvaluatorName} → {Builtin.ID} (AgentCore)
Standalone AgentCore evaluation script. Run the original script separately for baseline.
Saves scores_after.json + summary.json to output directory.
"""
import json, os, uuid, shutil
from pathlib import Path
from strands import Agent
from strands_evals.telemetry import StrandsEvalsTelemetry
from bedrock_agentcore.evaluation import EvaluationClient, convert_strands_to_adot

REGION = "us-east-1"
EVALUATOR_ID = "Builtin.{Name}"
# The metric key the ORIGINAL script reports, used verbatim in both score files.
METRIC_KEY = "{metric_key}"
# Output directory — task instruction specifies where to save artifacts
ARTIFACTS_DIR = Path(os.environ.get("ARTIFACTS_DIR", "/logs/artifacts"))
WORKSPACE_DIR = ARTIFACTS_DIR / "workspace"
SCRIPT_PATH = Path(__file__)
ORIGINAL_SCRIPT = "{original_name}.py"

test_cases = [...]  # Same inputs as original


def main():
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    telemetry = StrandsEvalsTelemetry().setup_in_memory_exporter()
    memory_exporter = telemetry.in_memory_exporter
    client = EvaluationClient(region_name=REGION)

    after_scores, queries = [], []

    for case in test_cases:
        session_id = str(uuid.uuid4())
        memory_exporter.clear()
        queries.append(case["input"])

        agent = Agent(
            trace_attributes={"session.id": session_id, "gen_ai.conversation.id": session_id},
            tools=[...],
            callback_handler=None,
        )
        agent_response = agent(case["input"])
        raw_spans = list(memory_exporter.get_finished_spans())

        # --- AgentCore evaluator ---
        adot_docs = convert_strands_to_adot(raw_spans)
        eval_response = client._dp_client.evaluate(
            evaluatorId=EVALUATOR_ID,
            evaluationInput={"sessionSpans": adot_docs},
        )
        results = eval_response.get("evaluationResults", [])
        values = [r.get("value") for r in results if r.get("value") is not None]
        if not values:
            # Never record a fabricated 0.0: it is indistinguishable from a real zero and
            # silently corrupts the divergence comparison.
            raise RuntimeError(f"evaluator returned no value for {case['input']!r}: {results}")
        after_scores.append(sum(values) / len(values))

    # Save artifacts
    mean_after = sum(after_scores) / len(after_scores)

    # mean_scores, keyed by the SAME metric key scores_before.json uses: the Step 6 check and
    # the verifier both index mean_scores, and a key present in one file but not the other is
    # scored as two failed metrics.
    (ARTIFACTS_DIR / "scores_after.json").write_text(json.dumps({
        "evaluators": [EVALUATOR_ID],
        "mean_scores": {METRIC_KEY: mean_after},
        "scores": [{"input": q, METRIC_KEY: s} for q, s in zip(queries, after_scores)],
    }, indent=2))

    # Load scores_before (produced by running original script) to compute divergence
    scores_before_path = ARTIFACTS_DIR / "scores_before.json"
    if scores_before_path.exists():
        before_data = json.loads(scores_before_path.read_text())
        mean_before = before_data["mean_scores"][METRIC_KEY]
        divergence = abs(mean_before - mean_after)
    else:
        mean_before = None
        divergence = None

    (ARTIFACTS_DIR / "summary.json").write_text(json.dumps({
        "source_evaluator": "{EvaluatorClass}",
        "target_evaluator": EVALUATOR_ID,
        "mapping_type": "builtin",
        "deploy_success": True, "invoke_success": True,
        "score_divergence": round(divergence, 3) if divergence is not None else None,
    }, indent=2))

    shutil.copy(SCRIPT_PATH.parent / ORIGINAL_SCRIPT, WORKSPACE_DIR)
    shutil.copy(SCRIPT_PATH, WORKSPACE_DIR)

    print(f"\nAgentCore mean: {mean_after:.3f}")
    if divergence is not None:
        print(f"Divergence from original: {divergence:.3f} {'✓ PASS' if divergence <= 0.1 else '✗ FAIL'}")
    else:
        print("scores_before.json not found — run original script first for comparison")


if __name__ == "__main__":
    main()
```

## Tracing Replacement: Langfuse → AgentCore (Strands agents)

```python
# REMOVE:
from langfuse import Langfuse, observe
langfuse = Langfuse(...)
@observe()
def run_agent(query): ...
langfuse.flush()

# REPLACE WITH:
from strands_evals.telemetry import StrandsEvalsTelemetry
from bedrock_agentcore.evaluation import convert_strands_to_adot
telemetry = StrandsEvalsTelemetry().setup_in_memory_exporter()
# ... run agent (no decorator needed) ...
adot_spans = convert_strands_to_adot(list(telemetry.in_memory_exporter.get_finished_spans()))
```

## Score Extraction by Level

- **TRACE-level** (Coherence, Conciseness, etc.): 1 result per session, `result["value"]` is 0.0-1.0
- **TOOL_CALL-level** (ToolParameterAccuracy, ToolSelectionAccuracy): 1 result per tool call span, average all values
- **SESSION-level** (GoalSuccessRate): 1 result per session, `result["value"]` is 0.0-1.0

## Known Scoring Differences

1. **Context structure:** AgentCore separates history (`{context}`) from target turn (`{assistant_turn}`). Local evaluators inline everything as flattened text.
2. **History format:** AgentCore uses JSON (`model_dump`). Local uses human-readable text.

Most impactful on: borderline refusals, multi-step tool chains. Rarely matters for clear-cut evaluations.
