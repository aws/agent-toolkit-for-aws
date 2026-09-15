"""
Provide your custom reward function code below. Learn about the available libraries and templates that you can use
at: https://docs.aws.amazon.com/sagemaker/latest/dg/customize-model.html.

- You must add your evaluation logic in the reward_function() function
- Do not remove the lambda_handler() function or modify its schema as it is required to create the reward function
"""

import json  # For JSON parsing - adjust imports based on your use case
import re  # For pattern matching and validation
from typing import Any, Dict, List, Optional, Union  # For type hints

# Add any other imports your use case requires

# ========================================================================================
#  NOTE: INITIAL SUGGESTION ONLY - MUST BE CUSTOMIZED
#
#     YOU MUST:
#     1. Review and update each section per YOUR use case
#     2. Customize the logic for YOUR SPECIFIC requirements
#     3. Replace example values (field names, thresholds, etc.) with your actual values
#     4. Test thoroughly before using
#
#     DO NOT use this code as-is. It will not work until you uncomment and customize it.
# =========================================================================================


# =========================================================================================
# SECTION 1: Helper function — content normalization
# =========================================================================================
# Nova messages use content as a string, a list of {"type":"text","text":"..."} chunks,
# or a dict with a "text" key. This helper normalizes all forms to a plain string.
def content_to_text(content: Any) -> str:
    """
    Normalize Nova message content to a plain string.

    Args:
        content: String, list of text chunks, or dict with "text" key

    Returns:
        Plain text string
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: List[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            else:
                parts.append(str(item))
        return "".join(parts)
    if isinstance(content, dict) and "text" in content:
        return content["text"]
    return str(content)


# =========================================================================================
# SECTION 2: Helper function — ground truth extraction
# =========================================================================================
# Nova reference_answer can be a dict with flexible keys (answer, label, sentiment, etc.),
# a JSON string, or a plain string.
def coerce_ground_truth(ground_truth: Union[str, Dict[str, Any], Any]) -> Optional[str]:
    """
    Extract the ground-truth answer as a string from reference_answer.

    Args:
        ground_truth: Dict, JSON string, or plain string

    Returns:
        Ground truth string, or None if not found
    """
    if ground_truth is None:
        return None

    if isinstance(ground_truth, str):
        s = ground_truth.strip()
        if not s:
            return None
        if s.startswith("{") or s.startswith("["):
            try:
                ground_truth = json.loads(s)
            except Exception:
                return s
        else:
            return s

    if isinstance(ground_truth, dict):
        for key in ("ground_truth", "answer", "label", "sentiment", "polarity", "target"):
            if key in ground_truth and ground_truth[key] is not None:
                return str(ground_truth[key])
        if len(ground_truth) == 1:
            only_val = next(iter(ground_truth.values()))
            if only_val is not None:
                return str(only_val)
        return None

    return str(ground_truth)


# =========================================================================================
# SECTION 3: Helper function — number extraction
# =========================================================================================
# TODO: UPDATE or REMOVE the helper function as per YOUR use case
# Note the below lines of code are examples and will not work for your use case
# You MUST update them to match YOUR use case
def extract_number(text: str) -> Optional[float]:
    """
    Extract numerical answer from text.
    Looks for numbers after answer keywords, or returns the last number found.

    Args:
        text: Text containing a numerical answer

    Returns:
        Extracted number as float, or None if no number found
    """
    if not text:
        return None

    # Try to find numbers after common answer keywords
    answer_patterns = [
        r"(?:equals|is|answer is|result is|=)\s*(-?\d+\.?\d*)",
        r"(?:answer|result|solution):\s*(-?\d+\.?\d*)",
    ]

    for pattern in answer_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

    # Fallback: find all numbers and return the last one (likely the answer)
    pattern = r"-?\d+\.?\d*"
    matches = re.findall(pattern, text)

    if matches:
        try:
            return float(matches[-1])
        except ValueError:
            return None

    return None


# =========================================================================================
# SECTION 4: Helper function — reasoning quality
# =========================================================================================
# TODO: UPDATE or REMOVE the helper function as per YOUR use case
# Note the below lines of code are examples and will not work for your use case
# You MUST update them to match YOUR use case
def compute_reasoning_quality(response: str) -> float:
    """
    Compute reasoning quality score based on response characteristics.
    This is a simple heuristic - customize based on your needs.

    Args:
        response: The model's response text

    Returns:
        Quality score between 0.0 and 1.0
    """
    if not response:
        return 0.0

    score = 0.0

    # Check for reasoning indicators (customize these for your use case)
    reasoning_indicators = [
        "because",
        "therefore",
        "thus",
        "since",
        "so",
        "first",
        "second",
        "then",
        "finally",
        "step",
        "calculate",
        "compute",
        "equals",
    ]

    response_lower = response.lower()

    # Award points for reasoning indicators (max 0.55)
    indicator_count = sum(1 for indicator in reasoning_indicators if indicator in response_lower)
    score += min(indicator_count * 0.11, 0.55)

    # Award points for response length (indicates detailed reasoning, max 0.25)
    if len(response) > 30:
        score += 0.05
    if len(response) > 60:
        score += 0.1
    if len(response) > 120:
        score += 0.1

    # Award points for structured response (max 0.2)
    if "\n" in response or "." in response:
        score += 0.2

    return min(score, 1.0)


# =========================================================================================
# SECTION 5: Helper function — answer extraction
# =========================================================================================
# TODO: UPDATE or REMOVE the helper function as per YOUR use case
# Note the below lines of code are examples and will not work for your use case
# You MUST update them to match YOUR use case
def extract_answer(response: str) -> Optional[str]:
    """
    Extract the answer from a Nova model response.
    Looks for <|begin_of_solution|>...<|end_of_solution|> blocks and \\boxed{} patterns.

    Args:
        response: The model's response text

    Returns:
        Extracted answer string, or None if not found
    """
    if not response:
        return None

    # Try solution block first
    solution_match = re.search(
        r"<\|begin_of_solution\|>(.*?)<\|end_of_solution\|>",
        response,
        re.DOTALL,
    )
    if solution_match:
        boxed = re.findall(r"\\boxed\{([^}]+)\}", solution_match.group(1))
        if boxed:
            return boxed[-1].strip()

    # Fallback: boxed anywhere
    boxed = re.findall(r"\\boxed\{([^}]+)\}", response)
    if boxed:
        return boxed[-1].strip()

    return None


# =========================================================================================
# SECTION 6: Sample reward function
# =========================================================================================
# TODO: UPDATE or REMOVE the reward function as per YOUR use case
# Note the below lines of code are examples and will not work for your use case
# You MUST update them to match YOUR use case
def reward_function(sample: Dict[str, Any], index: int) -> Dict[str, Any]:
    """
    Args:
        sample: Dictionary containing messages and reference_answer
        index: Sample index in batch

    Returns:
        Dictionary with reward scores and metrics
    """
    # ========================================================================
    # SECTION 7: Parse input
    # ========================================================================
    # TODO: UPDATE logic to parse the input as per YOUR use case
    # Note the below lines of code are examples and will not work for your use case
    # You MUST update them to match YOUR use case
    messages = sample.get("messages", [])
    ground_truth = sample.get("reference_answer", {})

    # Get the assistant's response (last message with role assistant or nova_assistant)
    response = ""
    for msg in messages:
        role = msg.get("role", "")
        if role in ("assistant", "nova_assistant"):
            response = content_to_text(msg.get("content", ""))

    # Extract numerical answers
    predicted = extract_number(response)
    expected_str = coerce_ground_truth(ground_truth)
    expected = extract_number(expected_str) if expected_str else None

    # Compute metrics
    exact_match = 0.0
    answer_present = 0.0
    reasoning_quality = compute_reasoning_quality(response)

    if predicted is not None and expected is not None:
        exact_match = 1.0 if abs(predicted - expected) < 1e-6 else 0.0
        answer_present = 1.0

    # ========================================================================
    # SECTION 8: Compute reward scores
    # ========================================================================
    # TODO: UPDATE logic to compute aggregate score
    # Note the below lines of code are examples and will not work for your use case
    # You MUST update them to match YOUR use case
    aggregate_reward = 0.7 * exact_match + 0.3 * reasoning_quality

    # ========================================================================
    # SECTION 9: Form the metrics list
    # ========================================================================
    # TODO: UPDATE logic to compute metrics list
    # Note the below lines of code are examples and will not work for your use case
    # You MUST update them to match YOUR use case
    metrics = [
        {"name": "exact_match", "value": float(exact_match), "type": "Reward"},
        {"name": "answer_present", "value": float(answer_present), "type": "Metric"},
        {"name": "reasoning_quality", "value": float(reasoning_quality), "type": "Metric"},
    ]

    # ========================================================================
    # SECTION 10: Return output
    # ========================================================================
    # TODO: UPDATE the return statement to return YOUR output
    # UPDATE the key before creating the evaluator
    # Note the below lines of code are examples and will not work for your use case
    # You MUST update them to match YOUR use case

    return {
        "id": str(sample.get("id", f"sample-{index:03d}")),
        "aggregate_reward_score": float(aggregate_reward),
        "metrics_list": metrics,
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda Handler for reward function.
    SageMaker Nova RLVR invokes this with a bare list of samples and expects
    a bare list of {id, aggregate_reward_score, ...} dicts in return.
    """
    # Event is a bare list of samples
    batch = event if isinstance(event, list) else []

    results = []
    for i, sample in enumerate(batch):
        try:
            result = reward_function(sample, i)
            results.append(result)
        except Exception as e:
            results.append(
                {
                    "id": str(
                        sample.get("id", f"sample-{i:03d}")
                        if isinstance(sample, dict)
                        else f"sample-{i:03d}"
                    ),
                    "aggregate_reward_score": 0.0,
                    "metrics_list": [],
                }
            )

    return results
