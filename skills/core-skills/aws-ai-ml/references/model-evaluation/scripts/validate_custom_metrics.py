"""Validate custom metrics JSON against the Bedrock LLM-as-Judge format.

Usage:
    python validate_custom_metrics.py '<json_string>'
    python validate_custom_metrics.py path/to/custom_metrics.json
"""

import json
import sys
from typing import Optional, Union

from pydantic import BaseModel, field_validator, model_validator


class RatingValue(BaseModel):
    floatValue: Optional[float] = None
    stringValue: Optional[str] = None

    @model_validator(mode="after")
    def exactly_one_value(self):
        has_float = self.floatValue is not None
        has_string = self.stringValue is not None
        if has_float == has_string:  # both set or neither set
            raise ValueError("Exactly one of 'floatValue' or 'stringValue' must be set.")
        return self


class RatingScaleEntry(BaseModel):
    definition: str
    value: RatingValue

    @field_validator("definition")
    @classmethod
    def definition_length(cls, v):
        if len(v) > 100:
            raise ValueError(f"Definition exceeds 100 chars ({len(v)}).")
        return v


class CustomMetricDefinition(BaseModel):
    name: str
    instructions: str
    ratingScale: Optional[list[RatingScaleEntry]] = None

    @model_validator(mode="after")
    def check_instructions(self):
        if len(self.instructions) > 5000:
            raise ValueError(f"Instructions exceed 5000 char limit ({len(self.instructions)}).")
        if "{{prediction}}" not in self.instructions and "{{prompt}}" not in self.instructions:
            raise ValueError("Instructions must contain at least {{prompt}} or {{prediction}}.")
        return self

    @model_validator(mode="after")
    def consistent_scale_types(self):
        if not self.ratingScale:
            return self
        types = set()
        for entry in self.ratingScale:
            if entry.value.floatValue is not None:
                types.add("float")
            if entry.value.stringValue is not None:
                types.add("string")
        if len(types) > 1:
            raise ValueError("ratingScale mixes float and string values. Use one type.")
        return self


class CustomMetric(BaseModel):
    customMetricDefinition: CustomMetricDefinition


def validate(raw: str) -> tuple[bool, list[str]]:
    """Validate a JSON string of custom metrics. Returns (ok, errors)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]

    if not isinstance(data, list):
        return False, ["Must be a JSON array of metric definitions."]
    if len(data) == 0:
        return False, ["Array is empty — need at least one metric."]
    if len(data) > 10:
        return False, [f"Too many metrics ({len(data)}). Maximum is 10."]

    errors = []
    for i, item in enumerate(data):
        try:
            CustomMetric.model_validate(item)
        except Exception as e:
            errors.append(f"Metric [{i}]: {e}")

    return len(errors) == 0, errors


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_custom_metrics.py '<json>' | file.json")
        sys.exit(1)

    arg = sys.argv[1]
    try:
        with open(arg, encoding="utf-8") as f:
            raw = f.read()
    except (FileNotFoundError, IsADirectoryError):
        raw = arg

    ok, errors = validate(raw)
    if ok:
        count = len(json.loads(raw))
        print(f"✅ Valid — {count} custom metric{'s' if count != 1 else ''} defined.")
    else:
        print("❌ Validation failed:")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
