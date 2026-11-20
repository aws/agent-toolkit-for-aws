#!/usr/bin/env python3
"""Deterministic metric classification: evaluator class → deployment path + score key.

Input: metrics.json, listing the metrics found in the customer's source:

    [
      {"class": "FaithfulnessMetric"},
      {"class": "GEval", "name": "Helpfulness", "init_kwargs": "threshold=0.7",
       "evaluation_params": ["INPUT", "ACTUAL_OUTPUT"],
       "criteria": "<copied VERBATIM from the source metric>"},
      {"class": "CorrectnessEvaluator"}
    ]

GEval also requires "name" and a rubric: "criteria" (str) or "evaluation_steps" (list[str]).
"evaluation_params" is optional. DAGMetric also requires "name". "init_kwargs" may hold only
literals (strings, numbers, booleans, None and lists/tuples/dicts of them), so rubric=
(List[Rubric]) cannot be passed; DAGMetric's dag= and JsonCorrectnessMetric's
expected_schema= are copied into the generated handler instead.

A DeepEval metric the source builds with different arguments per case (a PatternMatchMetric
per regex, a JsonCorrectnessMetric per schema) is listed once, with "variants" mapping a name
to each case's init_kwargs; each case names its variant in its Metric Inputs:

      {"class": "PatternMatchMetric", "init_kwargs": "threshold=1.0",
       "variants": {"date": "pattern=r'\\d{4}-\\d{2}-\\d{2}'", "email": "pattern=r'...'"}}

Output: mapping.json with one entry per metric:

    {
      "faithfulness": {
        "class": "FaithfulnessMetric",
        "score_key": "faithfulness",
        "path": "lambda_adapter",          # see PATHS below
        "adapter": "DeepEvalAdapter",
        "level": "TRACE",
        "evaluator_id": null,               # "Builtin.X" pre-filled for strands
        "init_kwargs": "",
        "notes": "..."
      }, ...
    }

PATHS:
- builtin            — no deployment; use the Builtin.* ID directly (Strands only)
- llm_judge          — custom LLM-as-a-Judge via SDK create_evaluator_and_wait() (Phoenix,
                       Strands OutputEvaluator)
- lambda_adapter     — code-based Lambda wrapping an SDK adapter (every DeepEval and RAGAS
                       metric)
- lambda_custom      — code-based Lambda with a custom handler (a skeleton is generated)
- unsupported        — out of scope for this skill version; report it to the user
- unknown            — not in the rules; decide manually and document why

scores_before.json and scores_after.json are compared by key, so with --scores-before each
derived key is replaced by its match in that file; unmatched keys on either side are errors.

Usage:
    python3 classify.py --framework deepeval --metrics metrics.json \\
        [--scores-before scores_before.json] --output mapping.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys

# =============================================================================
# Strands Evals → Builtin mapping (source of truth: references/strands-evals.md)
# =============================================================================

STRANDS_BUILTIN = {
    "CoherenceEvaluator": ("Builtin.Coherence", "TRACE"),
    "ConcisenessEvaluator": ("Builtin.Conciseness", "TRACE"),
    "CorrectnessEvaluator": ("Builtin.Correctness", "TRACE"),
    "FaithfulnessEvaluator": ("Builtin.Faithfulness", "TRACE"),
    "GoalSuccessRateEvaluator": ("Builtin.GoalSuccessRate", "SESSION"),
    "HarmfulnessEvaluator": ("Builtin.Harmfulness", "TRACE"),
    "HelpfulnessEvaluator": ("Builtin.Helpfulness", "TRACE"),
    "InstructionFollowingEvaluator": ("Builtin.InstructionFollowing", "TRACE"),
    "RefusalEvaluator": ("Builtin.Refusal", "TRACE"),
    "ResponseRelevanceEvaluator": ("Builtin.ResponseRelevance", "TRACE"),
    "StereotypingEvaluator": ("Builtin.Stereotyping", "TRACE"),
    "ToolParameterAccuracyEvaluator": ("Builtin.ToolParameterAccuracy", "TOOL_CALL"),
    "ToolSelectionAccuracyEvaluator": ("Builtin.ToolSelectionAccuracy", "TOOL_CALL"),
}

# =============================================================================
# DeepEval classification rules (source of truth: SKILL.md Step 2 table)
# =============================================================================

# Refused multi-turn metrics: conversation extraction from spans is unreliable for them.
DEEPEVAL_UNSUPPORTED_MULTI_TURN = {
    "ConversationalGEval",
    "ConversationCompletenessMetric",
    "KnowledgeRetentionMetric",
    "GoalAccuracyMetric",
    "RoleAdherenceMetric",
    "ToolUseMetric",
    "TurnContextualPrecisionMetric",
    "TurnContextualRecallMetric",
    "TurnFaithfulnessMetric",
    "TurnRelevancyMetric",
    "TopicAdherenceMetric",
}

# Multi-step single-turn pipelines → Lambda wrapping DeepEvalAdapter.
DEEPEVAL_MULTI_STEP = {
    "GEval",
    "FaithfulnessMetric",
    "AnswerRelevancyMetric",
    "ContextualRelevancyMetric",
    "ContextualPrecisionMetric",
    "ContextualRecallMetric",
    "BiasMetric",
    "ToxicityMetric",
    "HallucinationMetric",
    "SummarizationMetric",
    "PromptAlignmentMetric",
    "PIILeakageMetric",
    "MisuseMetric",
    "NonAdviceMetric",
    "RoleViolationMetric",
    # Its judgement nodes are LLM calls, so it is not deterministic.
    "DAGMetric",
    "ArgumentCorrectnessMetric",
    "TaskCompletionMetric",
}

# Deterministic metrics: the score comes from code, not from an LLM judge.
DEEPEVAL_DETERMINISTIC = {
    "ExactMatchMetric",
    "PatternMatchMetric",
    "JsonCorrectnessMetric",
    # Expected tools found among the tools called, divided by the expected tools.
    "ToolCorrectnessMetric",
}

# Bare spellings that appear in source and docs → the class deepeval exports. Classification
# rewrites them, so mapping.json only ever names a class generate_handlers.py can paste.
DEEPEVAL_CLASS_ALIASES = {
    "ExactMatch": "ExactMatchMetric",
    "PatternMatch": "PatternMatchMetric",
    "JsonCorrectness": "JsonCorrectnessMetric",
}

# Deterministic metrics that still take the judge model: JsonCorrectness writes its reason
# with it, and ToolCorrectness builds a default OpenAI model when given none, which fails
# without an OpenAI key. Their handlers get model= and async_mode=False.
DEEPEVAL_DETERMINISTIC_WITH_MODEL = {
    "JsonCorrectnessMetric",
    "ToolCorrectnessMetric",
}

# LLMTestCase fields a metric requires that the migrated client passes per case as Metric
# Inputs, because its ADOT documents carry no tool spans.
DEEPEVAL_METRIC_INPUTS = {
    "ArgumentCorrectnessMetric": ("tools_called",),
    "ToolCorrectnessMetric": ("expected_tools", "tools_called"),
}

# Constructor arguments that are Python objects, which mapping.json cannot carry:
# class -> (keyword, what to copy). The generated handler has a TODO(EVAL-MIGRATION) block
# for copying the object from the source script.
DEEPEVAL_SOURCE_OBJECT = {
    "DAGMetric": ("dag", "every node, criteria, child and score of the DeepAcyclicGraph"),
    "JsonCorrectnessMetric": ("expected_schema", "the model class and every class it uses"),
}

# Supported code-based DeepEval metrics, all routed through DeepEvalAdapter.
DEEPEVAL_ADAPTER_LAMBDA = DEEPEVAL_MULTI_STEP | DEEPEVAL_DETERMINISTIC

# Single-turn metric classes deepeval==4.2.3 exports: the only names pasted into generated
# handlers.
DEEPEVAL_METRIC_CLASSES = frozenset(
    {
        "AgentLoopDetectionMetric",
        "AnswerRelevancyMetric",
        "ArgumentCorrectnessMetric",
        "BiasMetric",
        "ContextualPrecisionMetric",
        "ContextualRecallMetric",
        "ContextualRelevancyMetric",
        "DAGMetric",
        "ExactMatchMetric",
        "FaithfulnessMetric",
        "HallucinationMetric",
        "ImageCoherenceMetric",
        "ImageEditingMetric",
        "ImageHelpfulnessMetric",
        "ImageReferenceMetric",
        "JsonCorrectnessMetric",
        "MCPUseMetric",
        "MisuseMetric",
        "NonAdviceMetric",
        "PIILeakageMetric",
        "PatternMatchMetric",
        "PlanAdherenceMetric",
        "PlanQualityMetric",
        "PromptAlignmentMetric",
        "RoleViolationMetric",
        "StepEfficiencyMetric",
        "SummarizationMetric",
        "TaskCompletionMetric",
        "TextToImageMetric",
        "ToolCorrectnessMetric",
        "ToolPermissionMetric",
        "ToxicityMetric",
        "GEval",
    }
)

# Metrics whose name and rubric fields are carried on the mapping entry, not in init_kwargs.
DEEPEVAL_GEVAL = {"GEval"}

# GEval rubric fields, copied verbatim from metrics.json onto the mapping entry.
GEVAL_RUBRIC_FIELDS = ("criteria", "evaluation_steps", "evaluation_params")

# Metrics whose constructor requires name=, with the suffix DeepEval appends to that name.
DEEPEVAL_NAMED = {"GEval": "geval", "DAGMetric": "dag"}

# Variant names are written into the generated handler and sent in each case's Metric Inputs.
VARIANT_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _camel_to_snake(name: str) -> str:
    """CamelCase → snake_case, handling consecutive capitals (PIILeakage → pii_leakage)."""
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower()


def _snake_name(name: str) -> str:
    """A metric's name= in snake_case: NonAdviceMetric → non_advice_metric."""
    words = _camel_to_snake(re.sub(r"[^0-9A-Za-z]+", "_", name))
    return re.sub(r"_+", "_", words).strip("_")


def derive_deepeval_key(cls: str, name_param: str | None) -> str:
    """Derive the score key DeepEval will use for a metric.

    - GEval: "{name}_[geval]" (name= lowercased, spaces → "_")
    - DAGMetric: "{name}_[dag]"
    - Others: class name minus "Metric", in snake_case (FaithfulnessMetric → faithfulness)
    """
    if cls in DEEPEVAL_NAMED:
        if not isinstance(name_param, str) or not name_param:
            raise ValueError(f"{cls} requires the 'name' field (its name= constructor arg)")
        return f"{name_param.lower().replace(' ', '_')}_[{DEEPEVAL_NAMED[cls]}]"
    base = cls[:-6] if cls.endswith("Metric") else cls
    return _camel_to_snake(base)


def _geval_fields(cls: str, spec: dict) -> dict:
    """Return GEval's name and rubric fields; raise ValueError if it has no rubric."""
    fields = {"name": spec["name"]}
    for key in GEVAL_RUBRIC_FIELDS:
        if spec.get(key):
            fields[key] = spec[key]
    if not (fields.get("criteria") or fields.get("evaluation_steps")):
        raise ValueError(
            f"{cls} '{spec['name']}' has neither 'criteria' nor 'evaluation_steps'. "
            "Copy one VERBATIM from the source metric into metrics.json — a GEval "
            "without a rubric evaluates nothing and its scores are meaningless."
        )
    return fields


def _variants(variants: object) -> dict[str, str]:
    """Return a copy of metrics.json "variants": variant name → init_kwargs string."""
    if not isinstance(variants, dict) or not variants:
        raise ValueError(
            f"'variants' must map variant names to init_kwargs strings, got {variants!r}"
        )
    for name, kwargs in variants.items():
        named = isinstance(name, str) and VARIANT_NAME_PATTERN.fullmatch(name)
        if not named or not isinstance(kwargs, str):
            raise ValueError(
                f"variant {name!r}: names must match {VARIANT_NAME_PATTERN.pattern} and map to "
                f"an init_kwargs string, got {kwargs!r}"
            )
    return dict(variants)


def _alias_note(spelled: str, cls: str) -> str:
    return f"source spells this class {spelled!r}; mapped to {cls}"


def classify_deepeval(spec: dict) -> dict:
    spelled = spec["class"]
    cls = DEEPEVAL_CLASS_ALIASES.get(spelled, spelled)
    if cls in DEEPEVAL_UNSUPPORTED_MULTI_TURN:
        return {
            "class": cls,
            "score_key": _camel_to_snake(cls[:-6] if cls.endswith("Metric") else cls),
            "evaluator_id": None,
            "level": "SESSION",
            "init_kwargs": spec.get("init_kwargs", ""),
            "path": "unsupported",
            "adapter": None,
            "notes": (
                f"{cls} is a DeepEval multi-turn/conversational metric, which "
                "this skill version does NOT support. Do not attempt to migrate "
                "it and do not substitute an LLM-as-a-Judge approximation. "
                "Report it to the user as out of scope and migrate the remaining "
                "metrics. RAGAS multi-turn metrics are unaffected."
            ),
        }
    key = derive_deepeval_key(cls, spec.get("name"))
    entry = {
        "class": cls,
        "score_key": key,
        "evaluator_id": None,
        "level": "TRACE",
        "init_kwargs": spec.get("init_kwargs", ""),
        "notes": "",
    }
    if cls in DEEPEVAL_GEVAL:
        entry.update(_geval_fields(cls, spec))
    if cls in DEEPEVAL_NAMED:
        entry["name"] = spec["name"]
        # Scripts report a named metric under their own spelling of its name
        # (NonAdviceMetric → non_advice_metric), which the derived key does not align with.
        entry["key_aliases"] = [_snake_name(spec["name"])]
    if cls in DEEPEVAL_ADAPTER_LAMBDA:
        entry.update(path="lambda_adapter", adapter="DeepEvalAdapter")
        entry["needs_llm"] = cls not in DEEPEVAL_DETERMINISTIC
        # generate_handlers.py reads needs_model to wire AmazonBedrockModel into the handler.
        entry["needs_model"] = entry["needs_llm"] or cls in DEEPEVAL_DETERMINISTIC_WITH_MODEL
        # Always single-turn here; kept explicit so mapping.json entries keep a stable shape.
        entry["multi_turn"] = False
        notes = ["No LLM-as-a-Judge fallback allowed"]
        # The Metric Inputs fields each case must carry, named in the client's error messages.
        fields = list(DEEPEVAL_METRIC_INPUTS.get(cls, ()))
        if fields:
            maps = " ".join(f"--metric-inputs-map {f}=<trace field>" for f in fields)
            notes.append(
                f"requires {' and '.join(fields)} per case as Metric Inputs ({maps}, or "
                "metric_inputs from _run_agent())"
            )
        elif cls == "TaskCompletionMetric":
            notes.append(
                "also reads the tools the agent called when the source passes them: pass "
                "them as Metric Inputs (--metric-inputs-map tools_called=<trace field>, or "
                "metric_inputs={'tools_called': [...]} from _run_agent())"
            )
        if cls == "ToolCorrectnessMetric":
            notes.append(
                "score = expected tools found among the tools called / expected tools; with "
                "no expected tools, 1.0 if none were called, else 0.0"
            )
        if cls in DEEPEVAL_SOURCE_OBJECT:
            kwarg = DEEPEVAL_SOURCE_OBJECT[cls][0]
            notes.append(
                f"takes {kwarg}= as a Python object: complete the TODO(EVAL-MIGRATION) block "
                "in the generated handler by copying it from the source VERBATIM"
            )
        if "variants" in spec:
            entry["variants"] = _variants(spec["variants"])
            fields.append("variants")
            notes.append(
                "built with different arguments per case: each case names its variant in its "
                'Metric Inputs, as {"variants": {<this score key>: <variant>}}'
            )
        if fields:
            entry["needs_metric_inputs"] = True
            entry["metric_inputs_fields"] = fields
        if spelled != cls:
            notes.append(_alias_note(spelled, cls))
        entry["notes"] = "; ".join(notes)
    else:
        entry.update(path="unknown", adapter=None)
        entry["notes"] = (
            "Class not in classification rules. Read the metric's source: if it scores an "
            "LLMTestCase, set path=lambda_adapter and adapter=DeepEvalAdapter (and "
            "needs_model=true if it takes a model); if it needs deepeval's own tracing or a "
            "multimodal test case, report it as out of scope. Document your decision."
        )
    return entry


def classify_strands(spec: dict) -> dict:
    cls = spec["class"]
    if cls in STRANDS_BUILTIN:
        builtin_id, level = STRANDS_BUILTIN[cls]
        key = _camel_to_snake(cls[:-9] if cls.endswith("Evaluator") else cls)
        return {
            "class": cls,
            "score_key": key,
            "path": "builtin",
            "adapter": None,
            "evaluator_id": builtin_id,
            "level": level,
            "init_kwargs": spec.get("init_kwargs", ""),
            # AgentCore's built-in evaluators judge with an LLM service-side.
            "needs_llm": True,
            "notes": "No deployment needed.",
        }
    if cls == "OutputEvaluator":
        return {
            "class": cls,
            "score_key": spec.get("name", "output_evaluator"),
            "path": "llm_judge",
            "adapter": None,
            "evaluator_id": None,
            "level": "TRACE",
            "init_kwargs": spec.get("init_kwargs", ""),
            "needs_llm": True,
            "notes": (
                "Extract the rubric= text and deploy as LLM-as-a-Judge "
                "(see references/strands-evals.md)."
            ),
        }
    return {
        "class": cls,
        "score_key": _camel_to_snake(cls),
        "path": "unknown",
        "adapter": None,
        "evaluator_id": None,
        "level": "TRACE",
        "init_kwargs": spec.get("init_kwargs", ""),
        "notes": "Unrecognized Strands evaluator — check references/strands-evals.md.",
    }


def classify_phoenix(spec: dict) -> dict:
    cls = spec["class"]
    key = _camel_to_snake(cls[:-9] if cls.endswith("Evaluator") else cls)
    notes = "Extract the classifier prompt VERBATIM via {NAME}_CLASSIFICATION_EVALUATOR_CONFIG."
    if "tool" in key:
        notes += (
            " Tool-related evaluator: prefer TRACE level with tool data embedded "
            "in context (TOOL_CALL often returns empty)."
        )
    return {
        "class": cls,
        "score_key": key,
        "path": "llm_judge",
        "adapter": None,
        "evaluator_id": None,
        "level": "TRACE",
        "init_kwargs": spec.get("init_kwargs", ""),
        # Every Phoenix evaluator is a single classification prompt.
        "needs_llm": True,
        "notes": notes,
    }


# =============================================================================
# RAGAS classification rules
# =============================================================================

# Every supported RAGAS metric deploys as a Lambda wrapping RagasAdapter, which runs the
# metric's own scoring code. That includes the NVIDIA metrics (AnswerAccuracy,
# ContextRelevance, ResponseGroundedness): each averages two judge prompts, which one
# LLM-as-a-Judge prompt cannot reproduce.

# Deterministic metrics — no LLM, no embeddings (rapidfuzz/sacrebleu etc.).
RAGAS_DETERMINISTIC = {
    "ExactMatch",
    "StringPresence",
    "BleuScore",
    "ChrfScore",
    "NonLLMStringSimilarity",
    "ToolCallAccuracy",
    "ToolCallF1",
    "NonLLMContextRecall",
    "NonLLMContextPrecisionWithReference",
    "IDBasedContextPrecision",
    "IDBasedContextRecall",
}

# Metrics that need embeddings=; all but RAGAS_EMBEDDINGS_ONLY also need llm=.
RAGAS_NEEDS_EMBEDDINGS = {
    "SemanticSimilarity",
    "AnswerSimilarity",
    "AnswerCorrectness",
    "AnswerRelevancy",
    "ResponseRelevancy",
}
RAGAS_EMBEDDINGS_ONLY = {"SemanticSimilarity", "AnswerSimilarity"}

# Multi-turn metrics: scored at SESSION level over the whole conversation.
RAGAS_MULTI_TURN = {
    "ToolCallAccuracy",
    "ToolCallF1",
    "TopicAdherenceScore",
    "AgentGoalAccuracyWithReference",
    "AgentGoalAccuracyWithoutReference",
}

# Refused metrics → reason, which is copied verbatim into the mapping notes.
RAGAS_UNSUPPORTED = {
    "DataCompyScore": (
        "pandas+datacompy cannot fit in a Lambda bundle alongside ragas, and the "
        "bespoke datacompy-only handler that works around it has no end-to-end "
        "coverage — shipping it is how the 250MB limit gets found in production"
    ),
    "RougeScore": (
        "its rouge-score dependency publishes an sdist and no wheel, so the CDK's "
        "`uv pip install --only-binary :all:` bundling cannot install it, and "
        "building that wheel locally would run the sdist's setup.py on the build host"
    ),
}

# Score keys where ragas's metric.name differs from the snake_case class name.
RAGAS_KEY_OVERRIDES = {
    "StringPresence": "string_present",
    "SummarizationScore": "summary_score",  # common renames: see RAGAS_KEY_ALIASES
    "AnswerAccuracy": "nv_accuracy",
    "ContextRelevance": "nv_context_relevance",
    "ResponseGroundedness": "nv_response_groundedness",
    "ChrfScore": "chrf_score",
    "ResponseRelevancy": "answer_relevancy",  # alias of AnswerRelevancy
    "LLMContextRecall": "context_recall",
    "LLMSQLEquivalence": "llm_sql_equivalence",
}

# Extra key candidates for --scores-before alignment: ragas 0.4.4 columns, common renames.
RAGAS_KEY_ALIASES = {
    "RubricsScore": ["domain_specific_rubrics"],
    "MultiModalFaithfulness": ["faithful_rate"],
    "MultiModalRelevance": ["relevance_rate"],
    "LLMSQLEquivalence": ["llm_sql_equivalence_with_reference"],
    "AgentGoalAccuracyWithReference": ["agent_goal_accuracy"],
    "AgentGoalAccuracyWithoutReference": ["agent_goal_accuracy"],
    "TopicAdherenceScore": ["topic_adherence"],
    "SemanticSimilarity": ["answer_similarity", "semantic_similarity"],
    # Scripts often rename the "summary_score" column; token matching cannot pair the two.
    "SummarizationScore": ["summarization_score"],
    # NVIDIA metrics: scripts usually use these names, not ragas's nv_* columns.
    "AnswerAccuracy": ["answer_accuracy"],
    "ContextRelevance": ["context_relevance"],
    "ResponseGroundedness": ["response_groundedness"],
}

# ragas 0.4.4 fetches only public image URLs: it refuses local paths and non-public
# hosts (GHSA-95ww-475f-pr4f), so a baseline scored on such images will diverge.
_MULTIMODAL_IMAGES = "public image URLs list (local paths and non-public hosts are refused)"
# Metric → (Metric Inputs fields, description): sample fields the migrated client's ADOT
# documents cannot carry, which it sends per case in the Metric Inputs section instead.
RAGAS_NEEDS_METRIC_INPUTS = {
    "InstanceRubrics": (("rubrics",), "per-instance rubric dict"),
    "MultiModalFaithfulness": (("retrieved_contexts",), _MULTIMODAL_IMAGES),
    "MultiModalRelevance": (("retrieved_contexts",), _MULTIMODAL_IMAGES),
    "SummarizationScore": (("reference_contexts",), "source context chunks list"),
    "LLMSQLEquivalence": (("reference_contexts",), "database schema DDL list"),
    "NonLLMContextRecall": (("reference_contexts",), "ground-truth context chunks list"),
    "NonLLMContextPrecisionWithReference": (
        ("reference_contexts",),
        "ground-truth context chunks list",
    ),
    "IDBasedContextPrecision": (
        ("retrieved_context_ids", "reference_context_ids"),
        "retrieved and ground-truth context ID lists",
    ),
    "IDBasedContextRecall": (
        ("retrieved_context_ids", "reference_context_ids"),
        "retrieved and ground-truth context ID lists",
    ),
    # The documents carry no tool calls, so ToolCallAccuracy would score the empty list.
    "ToolCallAccuracy": (("tools_called",), "the agent's tool calls as {name, args} dicts"),
    "ToolCallF1": (("tools_called",), "the agent's tool calls as {name, args} dicts"),
}

# Spellings seen in docs → the class ragas==0.4.4 exports (same role as DEEPEVAL_CLASS_ALIASES).
RAGAS_CLASS_ALIASES = {"CHRFScore": "ChrfScore"}

# ragas==0.4.4 metric classes, base classes excluded; same role as DEEPEVAL_METRIC_CLASSES.
# classify_ragas routes any other class to "unknown".
RAGAS_METRIC_CLASSES = frozenset(
    {
        "AgentGoalAccuracyWithReference",
        "AgentGoalAccuracyWithoutReference",
        "AnswerAccuracy",
        "AnswerCorrectness",
        "AnswerRelevancy",
        "AnswerSimilarity",
        "AspectCritic",
        "BleuScore",
        "ChrfScore",
        "ContextEntityRecall",
        "ContextPrecision",
        "ContextRecall",
        "ContextRelevance",
        "ContextUtilization",
        "DataCompyScore",
        "ExactMatch",
        "FactualCorrectness",
        "Faithfulness",
        "FaithfulnesswithHHEM",
        "IDBasedContextPrecision",
        "IDBasedContextRecall",
        "InstanceRubrics",
        "LLMContextPrecisionWithReference",
        "LLMContextPrecisionWithoutReference",
        "LLMContextRecall",
        "LLMSQLEquivalence",
        "MultiModalFaithfulness",
        "MultiModalRelevance",
        "NoiseSensitivity",
        "NonLLMContextPrecisionWithReference",
        "NonLLMContextRecall",
        "NonLLMStringSimilarity",
        "ResponseGroundedness",
        "ResponseRelevancy",
        "RougeScore",
        "RubricsScore",
        "SemanticSimilarity",
        "SimpleCriteriaScore",
        "StringPresence",
        "SummarizationScore",
        "ToolCallAccuracy",
        "ToolCallF1",
        "TopicAdherenceScore",
    }
)


def classify_ragas(spec: dict) -> dict:
    spelled = spec["class"]
    cls = RAGAS_CLASS_ALIASES.get(spelled, spelled)
    # AspectCritic / SimpleCriteriaScore keys come from their name= param.
    if cls in ("AspectCritic", "SimpleCriteriaScore") and spec.get("name"):
        key = spec["name"].lower().replace(" ", "_")
    else:
        key = RAGAS_KEY_OVERRIDES.get(cls, _camel_to_snake(cls))
    entry = {
        "class": cls,
        "score_key": key,
        "evaluator_id": None,
        "level": "TRACE",
        "init_kwargs": spec.get("init_kwargs", ""),
        "notes": "",
    }
    if cls in RAGAS_KEY_ALIASES:
        entry["key_aliases"] = RAGAS_KEY_ALIASES[cls]
    if cls in RAGAS_UNSUPPORTED:
        entry.update(path="unsupported", adapter=None)
        entry["notes"] = (
            f"{cls} is NOT supported by this skill version: {RAGAS_UNSUPPORTED[cls]}. "
            "Do not attempt to migrate it and do not substitute an approximation. "
            "Report it to the user as out of scope and migrate the remaining metrics."
        )
        return entry
    if cls not in RAGAS_METRIC_CLASSES:
        entry.update(path="unknown", adapter=None)
        entry["notes"] = (
            f"{spelled} is not a metric class ragas==0.4.4 exports, so no handler can be "
            "generated for it. Check the spelling against the source's import; if it is a "
            "custom metric, set path=lambda_custom. Document your decision."
        )
        return entry
    entry.update(path="lambda_adapter", adapter="RagasAdapter")
    entry["needs_llm"] = cls not in RAGAS_DETERMINISTIC and cls not in RAGAS_EMBEDDINGS_ONLY
    entry["needs_embeddings"] = cls in RAGAS_NEEDS_EMBEDDINGS
    entry["multi_turn"] = cls in RAGAS_MULTI_TURN
    notes = []
    if cls in RAGAS_NEEDS_METRIC_INPUTS:
        fields, desc = RAGAS_NEEDS_METRIC_INPUTS[cls]
        entry["needs_metric_inputs"] = True
        entry["metric_inputs_fields"] = list(fields)
        maps = " ".join(f"--metric-inputs-map {f}=<trace field>" for f in fields)
        notes.append(
            f"requires {' and '.join(fields)} ({desc}) per case as Metric Inputs, which the "
            f"generated handler reads ({maps}, or metric_inputs from _run_agent())"
        )
    if entry["needs_llm"]:
        notes.append(
            "needs llm=LangchainLLMWrapper(ChatBedrockConverse(...)) or the "
            "adapter returns METRIC_ERROR"
        )
    if entry["needs_embeddings"]:
        notes.append("needs embeddings=LangchainEmbeddingsWrapper(BedrockEmbeddings(...))")
    if entry["multi_turn"]:
        entry["level"] = "SESSION"  # multi-turn needs all turns in one invocation
        notes.append(
            "multi-turn: SESSION level required; the handler builds the conversation from "
            "the session's messages (or a user_input conversation in Metric Inputs) and reads "
            "the embedded reference by shape (tool-call list/topic list/plain text)"
        )
    if spelled != cls:
        notes.append(_alias_note(spelled, cls))
    entry["notes"] = "; ".join(notes)
    return entry


CLASSIFIERS = {
    "deepeval": classify_deepeval,
    "strands": classify_strands,
    "phoenix": classify_phoenix,
    "ragas": classify_ragas,
}


# =============================================================================
# scores_before.json cross-validation (ground truth for keys)
# =============================================================================


def extract_score_keys(data: dict) -> set[str]:
    """Extract metric key names from a scores JSON, whatever shape it uses."""
    if not isinstance(data, dict):
        return set()
    if "mean_scores" in data and isinstance(data["mean_scores"], dict):
        return {k for k, v in data["mean_scores"].items() if isinstance(v, (int, float))}
    keys: set[str] = set()
    if "scores" in data and isinstance(data["scores"], list):
        for entry in data["scores"]:
            if not isinstance(entry, dict):
                continue
            if "scores" in entry and isinstance(entry["scores"], dict):
                keys |= {k for k, v in entry["scores"].items() if isinstance(v, (int, float))}
            elif "metric" in entry and "score" in entry:
                keys.add(entry["metric"])
            else:
                keys |= {
                    k
                    for k, v in entry.items()
                    if isinstance(v, (int, float)) and k not in ("input", "name", "actual_output")
                }
        if keys:
            return keys
    skip = {"evaluators", "scores", "overall_mean", "mean_scores", "overall_score"}
    return {k for k, v in data.items() if k not in skip and isinstance(v, (int, float))}


def _token_aligned(a: str, b: str) -> bool:
    """Whether one metric key contains the other on snake_case token boundaries.

    Plain substring matching would wrongly pair "bias" with "unbiased_score". Case is
    ignored, so a baseline that kept the source's "NonAdviceMetric" still aligns.
    """
    a, b = a.lower(), b.lower()
    if a == b:
        return True
    at, bt = a.split("_"), b.split("_")
    short, long = (at, bt) if len(at) <= len(bt) else (bt, at)
    return any(long[i : i + len(short)] == short for i in range(len(long) - len(short) + 1))


def align_with_scores_before(mapping: dict, scores_before_path: str) -> dict:
    """Replace derived keys with the actual keys from scores_before.json.

    Matches exactly, then by alias, then by a unique token-boundary match. Any key left
    unmatched on either side raises SystemExit.
    """
    with open(scores_before_path) as f:
        actual_keys = extract_score_keys(json.load(f))
    if not actual_keys:
        print(
            f"[classify] WARNING: no metric keys extractable from {scores_before_path}; "
            "skipping alignment",
            file=sys.stderr,
        )
        return mapping

    derived = list(mapping.keys())
    remap: dict[str, str] = {}
    unmatched_actual = set(actual_keys)

    for dkey in derived:
        if dkey in actual_keys:
            remap[dkey] = dkey
            unmatched_actual.discard(dkey)

    # Known aliases (e.g. RubricsScore's column is 'domain_specific_rubrics')
    for dkey in derived:
        if dkey in remap:
            continue
        for alias in mapping[dkey].get("key_aliases", []):
            candidates = [a for a in unmatched_actual if _token_aligned(alias, a)]
            if len(candidates) == 1:
                remap[dkey] = candidates[0]
                unmatched_actual.discard(candidates[0])
                print(f"[classify] key aligned via alias: {dkey!r} → {candidates[0]!r}")
                break

    for dkey in derived:
        if dkey in remap:
            continue
        candidates = [a for a in unmatched_actual if _token_aligned(dkey, a)]
        if len(candidates) == 1:
            remap[dkey] = candidates[0]
            unmatched_actual.discard(candidates[0])
            print(f"[classify] key aligned to scores_before.json: {dkey!r} → {candidates[0]!r}")

    unmatched_derived = [d for d in derived if d not in remap]
    if unmatched_actual or unmatched_derived:
        raise SystemExit(
            "[classify] ERROR: metric keys cannot be aligned with scores_before.json.\n"
            f"  keys in scores_before.json with no match: {sorted(unmatched_actual)}\n"
            f"  derived keys with no match:               {sorted(unmatched_derived)}\n"
            "  Fix metrics.json (wrong class or missing 'name' param?) — before/after "
            "are compared by key, so any mismatch WILL fail the check."
        )

    return {remap[dkey]: {**entry, "score_key": remap[dkey]} for dkey, entry in mapping.items()}


# =============================================================================
# CLI
# =============================================================================


def classify_all(framework: str, specs: list[dict]) -> dict:
    framework = framework.lower()
    if framework not in CLASSIFIERS:
        raise SystemExit(
            f"[classify] ERROR: unsupported framework {framework!r}. "
            f"Supported: {sorted(CLASSIFIERS)}"
        )
    classifier = CLASSIFIERS[framework]
    mapping: dict[str, dict] = {}
    for spec in specs:
        if "class" not in spec:
            raise SystemExit(f"[classify] ERROR: spec missing 'class': {spec}")
        try:
            entry = classifier(spec)
        except ValueError as exc:
            raise SystemExit(f"[classify] ERROR: {spec.get('class')}: {exc}") from exc
        # Applied by the generated client (METRIC_TRANSFORMS), e.g. "score/5" for a 0-5 rubric.
        transform = spec.get("score_transform")
        if transform is not None:
            if not isinstance(transform, str) or not transform.strip():
                raise SystemExit(
                    f"[classify] ERROR: score_transform for {spec['class']!r} must be a "
                    f'non-empty expression string over "score" (e.g. "score/5"), '
                    f"got {transform!r}"
                )
            entry["score_transform"] = transform.strip()
        if "variants" in spec and "variants" not in entry and entry["path"] != "unsupported":
            raise SystemExit(
                f"[classify] ERROR: {spec['class']}: 'variants' is supported only for DeepEval "
                "metrics that deploy as a DeepEvalAdapter Lambda"
            )
        key = entry["score_key"]
        if key in mapping:
            raise SystemExit(
                f"[classify] ERROR: duplicate score key {key!r} — "
                "two metrics would collide in the scores JSON. If the source builds this "
                'metric with different arguments per case, list it once with "variants".'
            )
        mapping[key] = entry
    return mapping


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--framework",
        required=True,
        choices=sorted(CLASSIFIERS),
        help="source evaluation framework",
    )
    parser.add_argument(
        "--metrics",
        required=True,
        help="path to metrics.json (list of {class, name?, init_kwargs?})",
    )
    parser.add_argument(
        "--scores-before",
        default=None,
        help="path to scores_before.json — keys are aligned against it (recommended)",
    )
    parser.add_argument("--output", default="mapping.json", help="output path")
    args = parser.parse_args()

    with open(args.metrics) as f:
        specs = json.load(f)
    if not isinstance(specs, list):
        raise SystemExit("[classify] ERROR: metrics.json must be a JSON list")

    mapping = classify_all(args.framework, specs)
    if args.scores_before:
        mapping = align_with_scores_before(mapping, args.scores_before)

    with open(args.output, "w") as f:
        json.dump(mapping, f, indent=2)

    print(f"[classify] {len(mapping)} metrics classified → {args.output}")
    for key, entry in mapping.items():
        print(
            f"[classify]   {key}: path={entry['path']}"
            + (f" adapter={entry['adapter']}" if entry.get("adapter") else "")
            + (f" id={entry['evaluator_id']}" if entry.get("evaluator_id") else "")
        )
    unknowns = [k for k, e in mapping.items() if e["path"] == "unknown"]
    if unknowns:
        print(
            f"[classify] WARNING: {len(unknowns)} metric(s) need manual classification: "
            f"{unknowns} — read the metric source before deciding.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
