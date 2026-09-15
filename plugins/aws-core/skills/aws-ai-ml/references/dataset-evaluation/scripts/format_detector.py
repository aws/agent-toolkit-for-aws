"""Format detection for S3 JSONL files.

This module provides functionality to detect and validate JSONL file formats
stored in S3. It samples the first 1MB of a file to determine the format type
across 11 supported formats: Nova SFT, Nova DPO, Nova RLVR, GPT-OSS SFT,
GPT-OSS DPO, Open Weights SFT, Open Weights SFT Conv, Open Weights DPO,
Verl, Verl Legacy, and SageMaker Eval.

Usage:
    result = detect_format("s3://my-bucket/data.jsonl")
    if result.is_valid:
        print(f"Format: {result.format_type}")
"""

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

import boto3

os.environ.setdefault("AWS_SDK_UA_APP_ID", "AWSSkill-SageMaker")

logger = logging.getLogger(__name__)

# Type aliases for schema validators
MessageValidator = Callable[[list, int], "list[ValidationError]"]
RecordValidator = Callable[[dict, int], "list[ValidationError]"]

__all__ = [
    "FormatType",
    "ConfidenceLevel",
    "ValidationError",
    "FormatDetectionResult",
    "detect_format",
]


class FormatType(Enum):
    """Supported JSONL format types."""

    NOVA_SFT = "nova_sft"
    NOVA_DPO = "nova_dpo"
    NOVA_RLVR = "nova_rlvr"
    GPT_OSS_SFT = "gpt_oss_sft"
    GPT_OSS_DPO = "gpt_oss_dpo"
    OPEN_WEIGHTS_SFT = "open_weights_sft"
    OPEN_WEIGHTS_SFT_CONV = "open_weights_sft_conv"
    OPEN_WEIGHTS_DPO = "open_weights_dpo"
    VERL = "verl"
    VERL_LEGACY = "verl_legacy"
    SAGEMAKER_EVAL = "sagemaker_eval"
    UNKNOWN = "unknown"


class ConfidenceLevel(Enum):
    """Confidence level for format detection results."""

    HIGH = "high"
    LOW = "low"
    NONE = "none"


@dataclass
class ValidationError:
    """Represents a validation error found during format detection."""

    line_number: int
    error_type: str
    message: str


@dataclass
class FormatDetectionResult:
    """Result of format detection operation."""

    format_type: FormatType
    is_valid: bool
    lines_sampled: int
    errors: list[ValidationError]
    confidence: ConfidenceLevel


def _sample_local_file(file_path: str, sample_size: int) -> list[str]:
    """Sample lines from local JSONL file.

    Args:
        file_path: Path to local file
        sample_size: Maximum bytes to read

    Returns:
        List of lines from file

    Raises:
        FileNotFoundError: If file doesn't exist
        IOError: If file can't be read
    """
    logger.debug("Sampling local file: %s", file_path)
    with open(file_path, "rb") as f:
        data = f.read(sample_size)

    if not data:
        return []

    text = data.decode("utf-8", errors="replace")

    last_newline_idx = text.rfind("\n")
    if last_newline_idx == -1:
        return []

    complete_text = text[: last_newline_idx + 1]
    lines = [line for line in complete_text.split("\n") if line]

    return lines


def _sample_s3_file(s3_uri: str, sample_size_bytes: int, s3_client=None) -> list[str]:
    """Sample the first N bytes of an S3 file and return complete lines.

    Reads the first sample_size_bytes from an S3 file using a Range request,
    then truncates to the last complete newline to avoid partial lines.

    Args:
        s3_uri: S3 URI in format "s3://bucket/key"
        sample_size_bytes: Number of bytes to sample (default 1MB)
        s3_client: Optional boto3 S3 client to reuse

    Returns:
        List of complete JSONL lines (strings without trailing newlines)

    Raises:
        ValueError: If S3 URI is invalid (missing "s3://", bucket, or key)
        botocore.exceptions.ClientError: If S3 access fails
    """
    logger.debug("Sampling S3 file: %s (%d bytes)", s3_uri, sample_size_bytes)
    # Parse S3 URI
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: must start with 's3://' (got: {s3_uri})")

    uri_without_prefix = s3_uri[5:]  # Remove "s3://"
    parts = uri_without_prefix.split("/", 1)

    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid S3 URI: must contain bucket and key (got: {s3_uri})")

    bucket, key = parts

    # Read first sample_size_bytes using Range header
    client = s3_client or boto3.client("s3")
    range_header = f"bytes=0-{sample_size_bytes - 1}"

    response = client.get_object(Bucket=bucket, Key=key, Range=range_header)
    data = response["Body"].read()

    # Handle empty file
    if not data:
        return []

    # Decode bytes to string
    text = data.decode("utf-8", errors="replace")

    # Find last complete newline to avoid truncated lines
    last_newline_idx = text.rfind("\n")
    if last_newline_idx == -1:
        # No newlines found - return empty list if file is all one line
        # (we can't be sure it's complete)
        return []

    # Keep only complete lines (up to and including last newline)
    complete_text = text[: last_newline_idx + 1]

    # Split on newlines and filter empty strings
    lines = [line for line in complete_text.split("\n") if line]

    return lines


def _classify_nova_format(record: dict) -> FormatType:
    """Classify Nova-specific format by checking last message structure.

    Args:
        record: Parsed JSON record with messages field

    Returns:
        FormatType.NOVA_DPO if last message has candidates field,
        FormatType.NOVA_SFT if last message has standard content field,
        FormatType.UNKNOWN otherwise
    """
    messages = record.get("messages", [])
    if not messages:
        return FormatType.UNKNOWN

    last_message = messages[-1]
    if "candidates" in last_message:
        return FormatType.NOVA_DPO
    elif "content" in last_message and last_message["content"]:
        return FormatType.NOVA_SFT
    else:
        return FormatType.UNKNOWN


def _classify_messages_format(record: dict) -> FormatType:
    """Distinguish Nova vs GPT-OSS/HF by inspecting content structure.

    Nova has nested content arrays (list of dicts with 'text' field),
    GPT-OSS/HF has flat content strings.

    Args:
        record: Parsed JSON record with messages field

    Returns:
        FormatType value for the detected format
    """
    messages = record.get("messages")

    # Critical type checking: messages must be a list
    if not isinstance(messages, list):
        return FormatType.UNKNOWN

    if not messages:
        return FormatType.UNKNOWN

    first_message = messages[0]

    # Check if content field exists
    if "content" not in first_message:
        return FormatType.UNKNOWN

    content = first_message["content"]

    # Nova: nested content arrays (list of dicts with 'text' field)
    if isinstance(content, list):
        return _classify_nova_format(record)
    # GPT-OSS/HF: flat content strings
    elif isinstance(content, str):
        return FormatType.GPT_OSS_SFT
    else:
        return FormatType.UNKNOWN


def _classify_schema(samples: list[dict]) -> FormatType:
    """Top-level classifier that checks for all 11 supported formats.

    Args:
        samples: List of parsed JSON records

    Returns:
        FormatType value for the detected format
    """
    if not samples:
        return FormatType.UNKNOWN

    first = samples[0]
    fields = set(first.keys())

    # SageMaker Evaluation: query + response
    if "query" in fields and "response" in fields:
        return FormatType.SAGEMAKER_EVAL

    # Verl/RLVR: prompt + (reward_model or extra_info), no completion
    if "prompt" in fields and ("reward_model" in fields or "extra_info" in fields):
        if "completion" not in fields:
            if isinstance(first["prompt"], list):
                return FormatType.VERL
            return FormatType.VERL_LEGACY

    # Messages-based formats: Nova RLVR, Nova, GPT-OSS
    if "messages" in fields:
        if "reference_answer" in fields:
            return FormatType.NOVA_RLVR
        return _classify_messages_format(first)

    # DPO: prompt/chosen/rejected
    if {"prompt", "chosen", "rejected"}.issubset(fields):
        if isinstance(first["prompt"], list):
            return FormatType.GPT_OSS_DPO
        return FormatType.OPEN_WEIGHTS_DPO

    # SFT: prompt/completion
    if {"prompt", "completion"}.issubset(fields):
        if isinstance(first["prompt"], list):
            return FormatType.OPEN_WEIGHTS_SFT_CONV
        return FormatType.OPEN_WEIGHTS_SFT

    return FormatType.UNKNOWN


def _validate_nova_messages(messages: list, line_num: int, is_dpo: bool) -> list[ValidationError]:
    """Validate Nova SFT/DPO message structure."""
    errors = []
    for msg_idx, msg in enumerate(messages):
        if "role" not in msg:
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="missing_field",
                    message=f"Message {msg_idx} missing required field 'role'",
                )
            )
        elif msg["role"] not in ["user", "assistant", "system"]:
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="invalid_structure",
                    message=f"Invalid role '{msg['role']}' in message {msg_idx}",
                )
            )
        if "content" not in msg and "candidates" not in msg:
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="missing_field",
                    message=f"Message {msg_idx} missing 'content' or 'candidates'",
                )
            )
        if "content" in msg and not isinstance(msg["content"], list):
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="invalid_structure",
                    message=f"Nova format content must be list, got {type(msg['content']).__name__}",
                )
            )
        if is_dpo and "candidates" in msg:
            for cand_idx, candidate in enumerate(msg["candidates"]):
                if "preferenceLabel" not in candidate:
                    errors.append(
                        ValidationError(
                            line_number=line_num,
                            error_type="missing_field",
                            message=f"DPO message {msg_idx} candidate {cand_idx} missing 'preferenceLabel'",
                        )
                    )
                elif candidate["preferenceLabel"] not in ["preferred", "non-preferred"]:
                    errors.append(
                        ValidationError(
                            line_number=line_num,
                            error_type="invalid_structure",
                            message=f"Invalid preferenceLabel '{candidate['preferenceLabel']}' in message {msg_idx} candidate {cand_idx}",
                        )
                    )
    return errors


def _validate_gpt_messages(messages: list, line_num: int) -> list[ValidationError]:
    """Validate GPT-OSS SFT message structure."""
    errors = []
    for msg_idx, msg in enumerate(messages):
        if "role" not in msg:
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="missing_field",
                    message=f"Message {msg_idx} missing required field 'role'",
                )
            )
        elif msg["role"] not in ["user", "assistant", "system"]:
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="invalid_structure",
                    message=f"Invalid role '{msg['role']}' in message {msg_idx}",
                )
            )
        if "content" not in msg:
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="missing_field",
                    message=f"Message {msg_idx} missing required field 'content'",
                )
            )
        elif not isinstance(msg["content"], str):
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="invalid_structure",
                    message=f"GPT-OSS format content must be string, got {type(msg['content']).__name__}",
                )
            )
    return errors


def _validate_rlvr_messages(messages: list, line_num: int) -> list[ValidationError]:
    """Validate Nova RLVR message structure."""
    errors = []
    for msg_idx, msg in enumerate(messages):
        if "role" not in msg:
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="missing_field",
                    message=f"Message {msg_idx} missing required field 'role'",
                )
            )
        elif msg["role"] not in ["user", "assistant", "system"]:
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="invalid_structure",
                    message=f"Invalid role '{msg['role']}' in message {msg_idx}",
                )
            )
        if "content" not in msg:
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="missing_field",
                    message=f"Message {msg_idx} missing required field 'content'",
                )
            )
        elif not isinstance(msg["content"], str):
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="invalid_structure",
                    message=f"Nova RLVR content must be string, got {type(msg['content']).__name__}",
                )
            )
    return errors


def _validate_verl_prompt(record: dict, line_num: int) -> list[ValidationError]:
    """Validate Verl prompt structure (list of role/content dicts)."""
    errors = []
    if "prompt" not in record:
        errors.append(
            ValidationError(
                line_number=line_num,
                error_type="missing_field",
                message="Missing required field 'prompt'",
            )
        )
    elif not isinstance(record["prompt"], list):
        errors.append(
            ValidationError(
                line_number=line_num,
                error_type="invalid_structure",
                message=f"Verl field 'prompt' must be list, got {type(record['prompt']).__name__}",
            )
        )
    else:
        for msg_idx, msg in enumerate(record["prompt"]):
            if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
                errors.append(
                    ValidationError(
                        line_number=line_num,
                        error_type="invalid_structure",
                        message=f"Prompt message {msg_idx} must have 'role' and 'content'",
                    )
                )
    if "reward_model" not in record and "extra_info" not in record:
        errors.append(
            ValidationError(
                line_number=line_num,
                error_type="missing_field",
                message="Missing required field 'reward_model' or 'extra_info'",
            )
        )
    return errors


def _validate_verl_legacy_prompt(record: dict, line_num: int) -> list[ValidationError]:
    """Validate Verl Legacy prompt structure (string) and extra_info."""
    errors = []
    if "prompt" not in record:
        errors.append(
            ValidationError(
                line_number=line_num,
                error_type="missing_field",
                message="Missing required field 'prompt'",
            )
        )
    elif not isinstance(record["prompt"], str):
        errors.append(
            ValidationError(
                line_number=line_num,
                error_type="invalid_structure",
                message=f"Verl Legacy field 'prompt' must be string, got {type(record['prompt']).__name__}",
            )
        )
    if "reward_model" not in record and "extra_info" not in record:
        errors.append(
            ValidationError(
                line_number=line_num,
                error_type="missing_field",
                message="Missing required field 'reward_model' or 'extra_info'",
            )
        )
    return errors


# Schema-driven format validation specs.
# Each entry defines required_fields (field->type mapping) and an optional
# message_validator or record_validator for complex per-record checks.
# - message_validator: called with (messages_list, line_num) -> list[ValidationError]
#   Used for formats whose top-level required field is "messages" (list).
# - record_validator: called with (record, line_num) -> list[ValidationError]
#   Used for formats needing whole-record access (verl, verl_legacy).
FORMAT_SCHEMAS: dict[FormatType, dict[str, Any]] = {
    FormatType.NOVA_SFT: {
        "required_fields": {"messages": list},
        "message_validator": lambda msgs, ln: _validate_nova_messages(
            msgs, ln, is_dpo=False
        ),  # nosemgrep: python.lang.maintainability.return.return-not-in-function -- lambda inside dict literal, not a bare return
    },
    FormatType.NOVA_DPO: {
        "required_fields": {"messages": list},
        "message_validator": lambda msgs, ln: _validate_nova_messages(
            msgs, ln, is_dpo=True
        ),  # nosemgrep: python.lang.maintainability.return.return-not-in-function -- lambda inside dict literal, not a bare return
    },
    FormatType.NOVA_RLVR: {
        "required_fields": {"messages": list, "reference_answer": dict},
        "message_validator": _validate_rlvr_messages,
    },
    FormatType.GPT_OSS_SFT: {
        "required_fields": {"messages": list},
        "message_validator": _validate_gpt_messages,
    },
    FormatType.GPT_OSS_DPO: {
        "required_fields": {"prompt": list, "chosen": list, "rejected": list},
        "field_error_prefix": "GPT-OSS DPO",
    },
    FormatType.OPEN_WEIGHTS_SFT: {
        "required_fields": {"prompt": str, "completion": str},
        "field_error_prefix": "Open Weights SFT",
    },
    FormatType.OPEN_WEIGHTS_SFT_CONV: {
        "required_fields": {"prompt": list, "completion": list},
        "field_error_prefix": "Open Weights SFT Conv",
    },
    FormatType.OPEN_WEIGHTS_DPO: {
        "required_fields": {"prompt": str, "chosen": str, "rejected": str},
        "field_error_prefix": "Open Weights DPO",
    },
    FormatType.SAGEMAKER_EVAL: {
        "required_fields": {"query": str, "response": str},
        "field_error_prefix": "SageMaker Eval",
    },
    FormatType.VERL: {
        "required_fields": {},
        "record_validator": _validate_verl_prompt,
    },
    FormatType.VERL_LEGACY: {
        "required_fields": {},
        "record_validator": _validate_verl_legacy_prompt,
    },
}


def _validate_samples(
    samples: list[dict], expected_format: FormatType, line_numbers: list[int]
) -> tuple[bool, list[ValidationError]]:
    """Validate that all samples conform to the expected format schema.

    Args:
        samples: List of parsed JSON records
        expected_format: Expected FormatType enum value
        line_numbers: 1-based line numbers corresponding to each sample

    Returns:
        Tuple of (is_valid, errors) where errors is a list of ValidationError objects
    """
    errors = []
    schema = FORMAT_SCHEMAS.get(expected_format)

    for record, line_num in zip(samples, line_numbers):
        # Check schema consistency
        detected_format = _classify_schema([record])
        if detected_format != expected_format:
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="schema_mismatch",
                    message=f"Expected {expected_format.value} but found {detected_format.value}",
                )
            )
            continue

        if schema is None:
            continue

        # Record-level validator (verl, verl_legacy) handles everything
        if "record_validator" in schema:
            validator: RecordValidator = schema["record_validator"]
            errors.extend(validator(record, line_num))
            continue

        # Check required fields exist with correct types
        required = schema["required_fields"]
        prefix: str = schema.get("field_error_prefix", "") or ""
        skip_messages = False
        for field, expected_type in required.items():
            if field not in record:
                errors.append(
                    ValidationError(
                        line_number=line_num,
                        error_type="missing_field",
                        message=f"Missing required field '{field}'",
                    )
                )
                if field == "messages":
                    skip_messages = True
            elif not isinstance(record[field], expected_type):
                actual = type(record[field]).__name__
                if field == "messages":
                    errors.append(
                        ValidationError(
                            line_number=line_num,
                            error_type="invalid_structure",
                            message=f"Field 'messages' must be a list",
                        )
                    )
                    skip_messages = True
                elif prefix:
                    errors.append(
                        ValidationError(
                            line_number=line_num,
                            error_type="invalid_structure",
                            message=f"{prefix} field '{field}' must be {expected_type.__name__}, got {actual}",
                        )
                    )
                else:
                    errors.append(
                        ValidationError(
                            line_number=line_num,
                            error_type="invalid_structure",
                            message=f"Field '{field}' must be {expected_type.__name__}, got {actual}",
                        )
                    )

        if skip_messages:
            continue

        # Message-level validator
        if "message_validator" in schema:
            msg_validator: MessageValidator = schema["message_validator"]
            errors.extend(msg_validator(record["messages"], line_num))

    logger.debug("Validation found %d error(s)", len(errors))
    return (len(errors) == 0, errors)


def detect_format(
    file_path: str, sample_size_bytes: int = 1_048_576, s3_client=None
) -> FormatDetectionResult:
    """Detect the format of a JSONL file in S3 or on local disk.

    Samples the first sample_size_bytes of the file and analyzes the structure
    to determine if it matches one of the 11 supported formats.

    Args:
        file_path: S3 URI (s3://bucket/key) or local file path
        sample_size_bytes: Number of bytes to sample (default 1MB = 1,048,576 bytes)
        s3_client: Optional boto3 S3 client to reuse (ignored for local files)

    Returns:
        FormatDetectionResult with format type, validation status, and any errors
    """
    if file_path.startswith("s3://"):
        lines = _sample_s3_file(file_path, sample_size_bytes, s3_client=s3_client)
    else:
        lines = _sample_local_file(file_path, sample_size_bytes)

    # Parse JSON lines and collect parse errors
    parsed_records = []
    line_numbers = []
    errors = []

    for line_num, line in enumerate(lines, start=1):
        try:
            parsed_records.append(json.loads(line))
            line_numbers.append(line_num)
        except json.JSONDecodeError as e:
            errors.append(
                ValidationError(
                    line_number=line_num,
                    error_type="parse_error",
                    message=f"Invalid JSON: {str(e)}",
                )
            )

    # If no successfully parsed records, return UNKNOWN with parse errors
    if not parsed_records:
        confidence = ConfidenceLevel.NONE if errors else ConfidenceLevel.HIGH
        return FormatDetectionResult(
            format_type=FormatType.UNKNOWN,
            is_valid=len(errors) == 0,
            lines_sampled=len(lines),
            errors=errors,
            confidence=confidence,
        )

    # Classify schema using first successfully parsed record
    format_type = _classify_schema(parsed_records)

    # Validate all parsed records against detected format
    is_valid, validation_errors = _validate_samples(parsed_records, format_type, line_numbers)
    errors.extend(validation_errors)

    # Calculate confidence level
    if len(errors) == 0:
        confidence = ConfidenceLevel.HIGH
    elif any(err.error_type == "parse_error" for err in errors):
        confidence = ConfidenceLevel.NONE
    else:
        confidence = ConfidenceLevel.LOW

    logger.debug(
        "Detected format: %s (valid=%s, confidence=%s)",
        format_type.value,
        is_valid,
        confidence.value,
    )

    return FormatDetectionResult(
        format_type=format_type,
        is_valid=len(errors) == 0,
        lines_sampled=len(lines),
        errors=errors,
        confidence=confidence,
    )


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Detect and validate JSONL file formats")
    parser.add_argument("file_path", help="S3 URI (s3://bucket/key) or local file path")
    parser.add_argument(
        "--sample-size", type=int, default=1_048_576, help="Bytes to sample (default: 1MB)"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON instead of human-readable"
    )
    args = parser.parse_args()

    try:
        result = detect_format(args.file_path, args.sample_size)

        if args.json:
            output = {
                "format_type": result.format_type.value,
                "is_valid": result.is_valid,  # nosemgrep: python.lang.maintainability.is-function-without-parentheses -- dataclass field, not a method
                "confidence": result.confidence.value,
                "lines_sampled": result.lines_sampled,
                "errors": [
                    {"line_number": e.line_number, "error_type": e.error_type, "message": e.message}
                    for e in result.errors
                ],
            }
            print(json.dumps(output, indent=2))
        else:
            print(f"Format: {result.format_type.value}")
            print(
                f"Valid: {'✓' if result.is_valid else '✗'}"
            )  # nosemgrep: python.lang.maintainability.is-function-without-parentheses -- dataclass field, not a method
            print(f"Confidence: {result.confidence.name}")
            print(f"Lines sampled: {result.lines_sampled}")
            if result.errors:
                print("Errors:")
                for err in result.errors:
                    print(f"  Line {err.line_number}: {err.message}")

        sys.exit(
            0 if result.is_valid else 1
        )  # nosemgrep: python.lang.maintainability.is-function-without-parentheses -- dataclass field, not a method
    except (FileNotFoundError, IOError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
