"""
Provide your custom reward function code below. Learn about the available libraries and templates that you can use
at: https://docs.aws.amazon.com/sagemaker/latest/dg/customize-model.html.

- You must add your evaluation logic in the reward_function() function
- Do not remove the lambda_handler() function or modify its schema as it is required to create the reward function
"""

import json  # For JSON parsing - adjust imports based on your use case
import re  # For pattern matching and validation
from typing import Any, Dict, List, Optional  # For type hints

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
# SECTION 1: Helper function 1
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
            return float(matches[-1])  # Return last number instead of first
        except ValueError:
            return None

    return None


# =========================================================================================
# SECTION 2: Helper function 2
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
# SECTION 3: Sample reward function
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
    # SECTION 4: Parse input
    # ========================================================================
    # TODO: UPDATE logic to parse the input as per YOUR use case
    # Note the below lines of code are examples and will not work for your use case
    # You MUST update them to match YOUR use case
    # Extract the response and reference
    messages = sample.get("messages", sample.get("prompt", []))
    reference_answer = sample.get("reference_answer", {}).get("text", "") or sample.get(
        "reward_model", {}
    ).get("ground_truth", "")

    # Get the question and assistant's response
    question = ""
    response = ""
    for msg in messages:
        if msg.get("role") == "user":
            question = msg.get("content", "")
        elif msg.get("role") == "assistant":
            response = msg.get("content", "")

    # Extract numerical answers
    predicted = extract_number(response)
    expected = extract_number(reference_answer)

    # Compute metrics
    exact_match = 0.0
    answer_present = 0.0
    reasoning_quality = compute_reasoning_quality(response)

    if predicted is not None and expected is not None:
        exact_match = 1.0 if abs(predicted - expected) < 1e-6 else 0.0
        answer_present = 1.0

    # ========================================================================
    # SECTION 5: Compute reward scores
    # ========================================================================
    # TODO: UPDATE logic to compute aggregate score
    # Note the below lines of code are examples and will not work for your use case
    # You MUST update them to match YOUR use case
    # Aggregate reward computation
    aggregate_reward = 0.7 * exact_match + 0.3 * reasoning_quality

    # ========================================================================
    # SECTION 6: Form the metrics list
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
    # SECTION 7: Return output
    # ========================================================================
    # TODO: UPDATE the return statement to return YOUR outout
    # UPDATE the key before creating the evaluator
    # Note the below lines of code are examples and will not work for your use case
    # You MUST update them to match YOUR use case

    return {
        "id": str(sample.get("my_key", f"sample-{index:03d}")),  # Use formatted index as fallback
        "aggregate_reward_score": float(aggregate_reward),
        "metrics_list": metrics,
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    AWS Lambda Handler for reward function
    """
    try:
        # Extract batch from event
        batch = event.get("input", event) if isinstance(event, dict) else event
        if "batch" in event:
            batch = event.get("batch", [])
        elif "body" in event:
            body = json.loads(event.get("body", "{}"))
            batch = body.get("batch", [])

        if not batch:
            return {"error": "Missing or empty batch"}

        # Process each sample
        results = []
        for i, sample in enumerate(batch):
            try:
                result = reward_function(sample, i)
                results.append(result)
            except Exception as e:
                return {"error": str(e)}

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(results),
        }
    except Exception as e:
        return {"statusCode": 400, "body": json.dumps({"error": str(e)})}
