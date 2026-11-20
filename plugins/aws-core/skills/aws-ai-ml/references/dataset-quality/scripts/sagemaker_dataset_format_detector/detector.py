"""
Dataset format detection for SageMaker model customization.

Supports the hub's DatasetFileFormat values:
    Nova_CPT, Bedrock_Converse, Nova_PPO,
    HF_Prompt_Completion, HF_Preference, Verl,
    OpenAI_Messages, SageMaker_Eval, Nova_RLVR

Bedrock_Converse covers both SFT and DPO variants of the Bedrock Converse API format.
Datasets that don't match any supported format are classified as "Custom".

Two detection modes:
    strict=True  — Formats with closed schemas (Nova_CPT, Nova_PPO,
                   Bedrock_Converse, OpenAI_Messages, SageMaker_Eval,
                   Nova_RLVR) enforce exact key allowlists. Formats with
                   open schemas (HF_Prompt_Completion, HF_Preference, Verl)
                   tolerate extra keys even in strict mode. Exactly one format must match
                   across all sample records.
    strict=False — All validators check minimum required fields + type
                   constraints only. Extra keys are ignored for all formats.
                   Priority-ordered first-match resolves ambiguity (most
                   specific format checked first).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Format name constants: the hub's DatasetFileFormat values
# ---------------------------------------------------------------------------
NOVA_CPT = "Nova_CPT"
BEDROCK_CONVERSE = "Bedrock_Converse"  # covers both SFT and DPO Converse variants
NOVA_PPO = "Nova_PPO"
HF_PROMPT_COMPLETION = "HF_Prompt_Completion"
HF_PREFERENCE = "HF_Preference"
VERL = "Verl"
OPENAI_MESSAGES = "OpenAI_Messages"  # OpenAI/GPT-OSS chat-completions shape
SAGEMAKER_EVAL = "SageMaker_Eval"  # SageMaker single-turn eval (query/response)
NOVA_RLVR = "Nova_RLVR"  # Nova RLVR (messages + reference_answer)
CUSTOM = "Custom"  # unsupported/unrecognized format

SUPPORTED_FORMATS = [
    NOVA_CPT,
    BEDROCK_CONVERSE,
    NOVA_PPO,
    HF_PROMPT_COMPLETION,
    HF_PREFERENCE,
    VERL,
    OPENAI_MESSAGES,
    SAGEMAKER_EVAL,
    NOVA_RLVR,
]


# ---------------------------------------------------------------------------
# Schema constraints
# ---------------------------------------------------------------------------

_NOVA_CPT_ALLOWED_KEYS = {"text"}
_NOVA_PPO_ALLOWED_KEYS = {"turns", "turns_to_mask", "reward_category", "meta_data"}
_BEDROCK_CONVERSE_ALLOWED_KEYS = {"messages", "schemaVersion", "system", "toolConfig"}
_NOVA_PPO_REWARD_CATEGORIES = {"default", "math", "coding", "if", "rag", "rai"}
_NOVA_CONTENT_ITEM_KEYS = {
    "text",
    "image",
    "video",
    "document",
    "toolUse",
    "toolResult",
    "reasoningContent",
}
_SAGEMAKER_EVAL_ALLOWED_KEYS = {"query", "response", "system", "category"}
_NOVA_RLVR_ALLOWED_KEYS = {"messages", "reference_answer"}
_OPENAI_ALLOWED_ROLES = {"user", "assistant", "system"}

# Negative constraints for Nova_CPT in relaxed mode. Nova_CPT's positive signal
# (text: str) is too weak on its own — nearly any record with a "text" field
# would match. Priority ordering handles the case where a higher-priority format
# also matches, but doesn't help when a record has e.g. {"text": "hi", "query": "Q"}
# where the intended format (SageMaker_Eval) fails due to missing "response".
# Without negative constraints, that record would silently classify as CPT.
# The presence of another format's vocabulary fields is a stronger signal that
# this is NOT pretraining data, even if the specific format can't fully match.
_NON_CPT_FIELDS = frozenset(
    {
        "prompt",
        "completion",
        "messages",
        "query",
        "chosen",
        "rejected",
        "label",
        "label_text",
        "labels",
        "intent",
        "category",
        "answer",
    }
)


# ---------------------------------------------------------------------------
# Content validators (core logic — no key restrictions)
#
# Each _check_* function validates that required fields are present with
# correct types and structural constraints. Extra keys are ignored.
# These are the building blocks for both strict and relaxed detection.
# ---------------------------------------------------------------------------


def _check_nova_cpt(record: dict) -> bool:
    """Nova CPT content: ``text`` present and is a string."""
    return isinstance(record.get("text"), str)


def _check_nova_ppo(record: dict) -> bool:
    """Nova PPO content: turns, turns_to_mask, reward_category with correct types."""
    for required in ("turns", "turns_to_mask", "reward_category"):
        if required not in record:
            return False
    turns = record["turns"]
    if not isinstance(turns, list) or len(turns) < 1:
        return False
    if not all(isinstance(t, str) for t in turns):
        return False
    for t in turns:
        if not (t.startswith("User:") or t.startswith("Bot:")):
            return False
    turns_to_mask = record["turns_to_mask"]
    if not isinstance(turns_to_mask, list):
        return False
    if not all(isinstance(t, int) for t in turns_to_mask):
        return False
    reward_category = record["reward_category"]
    if not isinstance(reward_category, str) or reward_category not in _NOVA_PPO_REWARD_CATEGORIES:
        return False
    return True


def _validate_nova_message(msg: dict) -> bool:
    """Validate a single Nova SFT/DPO message (role + content required)."""
    if not isinstance(msg, dict):
        return False
    if "role" not in msg or "content" not in msg:
        return False
    if msg["role"] not in ("user", "assistant"):
        return False
    content = msg["content"]
    if not isinstance(content, list) or len(content) < 1:
        return False
    for item in content:
        if not isinstance(item, dict):
            return False
        if not any(k in item for k in _NOVA_CONTENT_ITEM_KEYS):
            return False
    return True


def _validate_nova_candidates_message(msg: dict) -> bool:
    """Validate a Nova DPO candidates message (role + candidates)."""
    if not isinstance(msg, dict):
        return False
    if msg.get("role") != "assistant":
        return False
    candidates = msg.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 2:
        return False
    for candidate in candidates:
        if not isinstance(candidate, dict):
            return False
        if "content" not in candidate or "preferenceLabel" not in candidate:
            return False
        if candidate["preferenceLabel"] not in ("preferred", "non-preferred"):
            return False
        content = candidate["content"]
        if not isinstance(content, list) or len(content) < 1:
            return False
        for item in content:
            if not isinstance(item, dict) or "text" not in item:
                return False
    return True


def _check_bedrock_converse(record: dict) -> bool:
    """Bedrock Converse content: messages with role+list-content, SFT or DPO."""
    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) < 2:
        return False
    for msg in messages:
        if isinstance(msg, dict) and "candidates" in msg:
            if not _validate_nova_candidates_message(msg):
                return False
        else:
            if not _validate_nova_message(msg):
                return False
    return True


def _validate_openai_message(msg: dict) -> bool:
    """Validate a single OpenAI message (role + string content)."""
    if not isinstance(msg, dict):
        return False
    if "role" not in msg or "content" not in msg:
        return False
    if not isinstance(msg["role"], str) or msg["role"] not in _OPENAI_ALLOWED_ROLES:
        return False
    if not isinstance(msg["content"], str):
        return False
    return True


def _check_openai_messages(record: dict) -> bool:
    """OpenAI Messages content: messages list with role + string content, ≥1 assistant."""
    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) < 1:
        return False
    for msg in messages:
        if not _validate_openai_message(msg):
            return False
    if not any(m.get("role") == "assistant" for m in messages):
        return False
    return True


def _is_string_or_message_array(value: Any) -> bool:
    """Check if value is a plain string or a message array ``[{role, content}]``."""
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return all(
            isinstance(item, dict) and "role" in item and "content" in item for item in value
        )
    return False


def _check_hf_prompt_completion(record: dict) -> bool:
    """HF Prompt/Completion content: prompt + completion, no chosen/rejected."""
    if "prompt" not in record or "completion" not in record:
        return False
    if not _is_string_or_message_array(record["prompt"]):
        return False
    if not _is_string_or_message_array(record["completion"]):
        return False
    if "chosen" in record or "rejected" in record:
        return False
    return True


def _check_hf_preference(record: dict) -> bool:
    """HF Preference content: chosen + rejected present with correct types."""
    if "chosen" not in record or "rejected" not in record:
        return False
    if not _is_string_or_message_array(record["chosen"]):
        return False
    if not _is_string_or_message_array(record["rejected"]):
        return False
    return True


def _check_verl(record: dict) -> bool:
    """Verl content: prompt present, no completion/chosen/rejected."""
    if "prompt" not in record:
        return False
    if not _is_string_or_message_array(record["prompt"]):
        return False
    if "completion" in record:
        return False
    if "chosen" in record or "rejected" in record:
        return False
    return True


def _check_sagemaker_eval(record: dict) -> bool:
    """SageMaker Eval content: query + response as strings, optional system/category validated."""
    if "query" not in record or "response" not in record:
        return False
    if not isinstance(record["query"], str):
        return False
    if not isinstance(record["response"], str):
        return False
    if "system" in record and not isinstance(record["system"], str):
        return False
    if "category" in record and not isinstance(record["category"], str):
        return False
    return True


def _check_nova_rlvr(record: dict) -> bool:
    """Nova RLVR content: messages (OpenAI-style) + reference_answer (dict)."""
    if "reference_answer" not in record or not isinstance(record["reference_answer"], dict):
        return False
    messages = record.get("messages")
    if not isinstance(messages, list) or len(messages) < 1:
        return False
    for msg in messages:
        if not _validate_openai_message(msg):
            return False
    return True


# ---------------------------------------------------------------------------
# Strict validators — compose key restriction + content check
#
# These enforce exact key allowlists on top of content validation.
# Used when strict=True.
# ---------------------------------------------------------------------------


def _strict_nova_cpt(record: dict) -> bool:
    if set(record.keys()) != _NOVA_CPT_ALLOWED_KEYS:
        return False
    return _check_nova_cpt(record)


def _strict_nova_ppo(record: dict) -> bool:
    if not set(record.keys()).issubset(_NOVA_PPO_ALLOWED_KEYS):
        return False
    return _check_nova_ppo(record)


def _strict_bedrock_converse(record: dict) -> bool:
    if not set(record.keys()).issubset(_BEDROCK_CONVERSE_ALLOWED_KEYS):
        return False
    return _check_bedrock_converse(record)


def _strict_openai_messages(record: dict) -> bool:
    if set(record.keys()) != {"messages"}:
        return False
    return _check_openai_messages(record)


def _strict_sagemaker_eval(record: dict) -> bool:
    if not set(record.keys()).issubset(_SAGEMAKER_EVAL_ALLOWED_KEYS):
        return False
    return _check_sagemaker_eval(record)


def _strict_nova_rlvr(record: dict) -> bool:
    if not set(record.keys()).issubset(_NOVA_RLVR_ALLOWED_KEYS):
        return False
    return _check_nova_rlvr(record)


# ---------------------------------------------------------------------------
# Relaxed validators with negative constraints
#
# For formats where content checks alone are too broad, negative constraints
# prevent false matches by requiring absence of other formats' critical fields.
# ---------------------------------------------------------------------------


def _relaxed_nova_cpt(record: dict) -> bool:
    """Nova_CPT relaxed: text present, no other format's critical fields."""
    if not _check_nova_cpt(record):
        return False
    return not any(k in record for k in _NON_CPT_FIELDS)


def _relaxed_openai_messages(record: dict) -> bool:
    """OpenAI_Messages relaxed: valid content, no reference_answer.

    Without this constraint, a Nova_RLVR record where reference_answer has
    a non-dict type (failing _check_nova_rlvr) would fall through and match
    OpenAI_Messages. The presence of reference_answer — regardless of its
    type — signals RLVR intent, not plain chat-completions.
    """
    if not _check_openai_messages(record):
        return False
    return "reference_answer" not in record


# ---------------------------------------------------------------------------
# Validator registries
# ---------------------------------------------------------------------------

# Strict mode: unordered, exactly-one-match semantics.
# HF_Prompt_Completion, HF_Preference and Verl are open-schema formats, so they
# use the content checks directly (no _strict_* wrapper).
_VALIDATORS: dict[str, Callable[[dict], bool]] = {
    NOVA_CPT: _strict_nova_cpt,
    NOVA_PPO: _strict_nova_ppo,
    BEDROCK_CONVERSE: _strict_bedrock_converse,
    HF_PROMPT_COMPLETION: _check_hf_prompt_completion,
    HF_PREFERENCE: _check_hf_preference,
    VERL: _check_verl,
    OPENAI_MESSAGES: _strict_openai_messages,
    SAGEMAKER_EVAL: _strict_sagemaker_eval,
    NOVA_RLVR: _strict_nova_rlvr,
}

# Relaxed mode: priority-ordered, first-match wins.
#
# Philosophy: relaxed mode is best-effort matching. The goal is to classify
# the dataset into a known format whenever possible, rather than rejecting it.
# Extra fields are tolerated because real-world datasets (SDG output, BYOD with
# metadata columns) often carry auxiliary fields alongside the core content.
# When a record's fields satisfy multiple format checks, priority ordering
# picks the most specific match — the format whose required fields are the
# strongest signal of intent. For deterministic, unambiguous detection where
# extra fields cause rejection, use strict=True.
#
# Priority rationale (most specific → most permissive):
#   1. Nova_RLVR — reference_answer is a unique marker (no other format uses it)
#   2. Bedrock_Converse — list-of-dict content structure is unambiguous
#   3. Nova_PPO — turns + turns_to_mask + reward_category is a unique triple
#   4. OpenAI_Messages — string-content messages (RLVR already ruled out above)
#   5. HF_Preference — chosen + rejected is a strong DPO signal
#   6. SageMaker_Eval — query + response are domain-specific field names
#   7. HF_Prompt_Completion — prompt + completion (common ML convention)
#   8. Nova_CPT — text only (negative constraints prevent over-matching)
#   9. Verl — prompt only (most permissive; anything with a prompt matches)
_RELAXED_VALIDATORS: list[tuple[str, Callable[[dict], bool]]] = [
    (NOVA_RLVR, _check_nova_rlvr),
    (BEDROCK_CONVERSE, _check_bedrock_converse),
    (NOVA_PPO, _check_nova_ppo),
    (OPENAI_MESSAGES, _relaxed_openai_messages),
    (HF_PREFERENCE, _check_hf_preference),
    (SAGEMAKER_EVAL, _check_sagemaker_eval),
    (HF_PROMPT_COMPLETION, _check_hf_prompt_completion),
    (NOVA_CPT, _relaxed_nova_cpt),
    (VERL, _check_verl),
]


# ---------------------------------------------------------------------------
# Public API — format detection
# ---------------------------------------------------------------------------


def detect_format(records: list[dict], strict: bool = False) -> str:
    """Detect dataset format from sample records.

    Args:
        records: Sample records (dicts) from the dataset.
        strict: If True, enforce exact key allowlists.
                If False (default), use relaxed detection with priority ordering.

    Returns:
        Format name string (one of SUPPORTED_FORMATS, or CUSTOM).
    """
    if not records:
        logger.warning("Empty dataset provided. Classified as '%s'.", CUSTOM)
        return CUSTOM

    if not all(isinstance(record, dict) for record in records):
        logger.info("Dataset contains a non-object record. Classified as '%s'.", CUSTOM)
        return CUSTOM

    if strict:
        matches: list[str] = []
        for name, validator in _VALIDATORS.items():
            if all(validator(record) for record in records):
                matches.append(name)

        if len(matches) == 1:
            return matches[0]
        if len(matches) == 0:
            logger.info(
                "Dataset does not match any supported format (strict mode). "
                "Classified as '%s'. Supported formats: %s",
                CUSTOM,
                SUPPORTED_FORMATS,
            )
            return CUSTOM
        logger.warning(
            "Dataset is ambiguous — matches multiple formats: %s (strict mode). "
            "Classified as '%s'. Please restructure your dataset to match "
            "exactly one supported format: %s",
            matches,
            CUSTOM,
            SUPPORTED_FORMATS,
        )
        return CUSTOM

    # Relaxed: best-effort matching. Walk the priority list (most specific
    # first) and return the first format where ALL sample records pass.
    # A record may satisfy multiple validators — priority picks the format
    # whose required fields are the strongest signal of intent. This is
    # intentional: the goal is to always classify into a known format when
    # possible, enabling downstream evaluation rather than rejecting.
    for name, check in _RELAXED_VALIDATORS:
        if all(check(record) for record in records):
            return name

    logger.info(
        "Dataset does not match any supported format (relaxed mode). "
        "Classified as '%s'. Supported formats: %s",
        CUSTOM,
        SUPPORTED_FORMATS,
    )
    return CUSTOM
