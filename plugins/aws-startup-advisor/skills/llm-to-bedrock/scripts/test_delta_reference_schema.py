# test_delta_reference_schema.py
"""Guard: every `resolution_kind` the delta references instruct the analyzer to
emit must be accepted by analysis.json.

The analyzer builds `behavior_deltas` by reading these references, then validates
its own output. A value that appears in a reference but not in the schema makes
T2-3 unable to produce a valid result — and the failure surfaces at runtime in a
subagent, not in CI. This test closes that gap.

It caught a real case twice over: an invented `mechanical` value, first in the
bullet declarations and then again in a prose sentence inside the same block that
a targeted edit had missed.
"""
import json
import re
from pathlib import Path

REFS = Path(__file__).resolve().parent.parent / "references/helpers/behavior-delta-detection/references"
SCHEMA = Path(__file__).resolve().parent / "schemas/analysis.json"

# Matches both the bullet form (`- `resolution_kind`: `impl_path``) and prose
# mentions (`... `resolution_kind: impl_path`. Apply ...`), with the value inside
# or outside the backticks.
PATTERN = re.compile(r"resolution_kind`?\s*:\s*`?([a-z_]+)`?")


def allowed_kinds() -> set[str]:
    schema = json.loads(SCHEMA.read_text())

    found: list[list[str]] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("enum") and "resolution_kind" not in found:
                pass
            for key, value in node.items():
                if key == "resolution_kind" and isinstance(value, dict) and "enum" in value:
                    found.append(value["enum"])
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    assert found, "analysis.json no longer declares a resolution_kind enum"
    return set(found[0])


def test_every_reference_resolution_kind_is_in_the_schema():
    allowed = allowed_kinds()
    offenders = []
    for ref in sorted(REFS.glob("*.md")):
        for lineno, line in enumerate(ref.read_text().splitlines(), 1):
            for value in PATTERN.findall(line):
                if value not in allowed:
                    offenders.append(f"{ref.name}:{lineno} -> {value!r}")
    assert not offenders, (
        "delta references instruct the analyzer to emit resolution_kind values that "
        f"analysis.json rejects (allowed: {sorted(allowed)}):\n  " + "\n  ".join(offenders))


def test_pattern_catches_both_declaration_forms():
    # Guards the guard: if PATTERN stops matching either form, the test above
    # silently passes on a broken reference.
    assert PATTERN.findall("- `resolution_kind`: `impl_path`") == ["impl_path"]
    assert PATTERN.findall("always `user_visible: false`, `resolution_kind: mechanical`.") == ["mechanical"]


# --- Same guard, applied to the evaluator's documented control states ----------
# The evaluator writes `{ blocked: { reason, detail } }` and then validates against
# eval.json. A reason documented in the prompt but absent from the schema means a
# real failure mode (404, IAM denial, missing deps) cannot be represented at all,
# so the phase enters the retry path with no valid outcome file.

AGENTS = Path(__file__).resolve().parent.parent.parent.parent / "agents"
EVAL_SCHEMA = Path(__file__).resolve().parent / "schemas/eval.json"
REASON_PATTERN = re.compile(r"reason:\s*'([a-z_]+)'")


def _eval_enums() -> tuple[set[str], set[str]]:
    schema = json.loads(EVAL_SCHEMA.read_text())
    blocked, partial = set(), set()
    for branch in schema.get("oneOf", []):
        props = branch.get("properties", {})
        if "blocked" in props:
            blocked = set(props["blocked"]["properties"]["reason"]["enum"])
        if "partial" in props:
            partial = set(props["partial"]["properties"]["reason"]["enum"])
    assert blocked, "eval.json no longer declares a blocked.reason enum"
    return blocked, partial


def test_evaluator_control_state_reasons_are_representable():
    blocked, partial = _eval_enums()
    allowed = blocked | partial
    prompt = (AGENTS / "llm2bedrock-prompt-evaluator.md").read_text()
    offenders = []
    for lineno, line in enumerate(prompt.splitlines(), 1):
        for value in REASON_PATTERN.findall(line):
            if value not in allowed:
                offenders.append(f"llm2bedrock-prompt-evaluator.md:{lineno} -> {value!r}")
    assert not offenders, (
        "the evaluator documents control-state reasons that eval.json rejects "
        f"(blocked: {sorted(blocked)}, partial: {sorted(partial)}):\n  " + "\n  ".join(offenders))


# --- Guard: the evaluator must not hand-assemble Responses image payloads -------
# Both mistakes below pass the §9.5a smoke test (it hardcodes a known-good jpeg)
# and fail only on golden cases, so a static check is the cheapest place to catch
# a regression in prompt text that no unit test can reach.

def test_evaluator_does_not_document_a_bare_responses_content_list():
    prompt = (AGENTS / "llm2bedrock-prompt-evaluator.md").read_text()
    offenders = []
    for lineno, line in enumerate(prompt.splitlines(), 1):
        if "input_image" not in line and "input_text" not in line:
            continue
        # Any line showing a Responses content block must either be inside a
        # role/content wrapper or be delegating to the helper.
        if '"role"' in line or "'role'" in line:
            continue
        if "responses_message" in line:
            continue
        # The §9.5a snippet wraps across lines; allow the inner block lines there.
        offenders.append((lineno, line.strip()[:90]))
    # Lines inside the multi-line §9.5a wrapper are legitimate; assert every
    # offender sits within 3 lines of a role wrapper.
    lines = prompt.splitlines()
    real = []
    for lineno, text in offenders:
        window = "\n".join(lines[max(0, lineno - 4):lineno])
        # Any message-item role is a valid wrapper: `user` for prompts, `developer`
        # for a system prompt on the Responses API.
        if not re.search(r'"role":\s*"(user|developer|system|assistant)"', window):
            real.append(f"line {lineno}: {text}")
    assert not real, (
        "Responses image content documented without a user-message wrapper "
        "(input takes [{'role':'user','content':[...]}], not a bare block list):\n  "
        + "\n  ".join(real))


def test_evaluator_never_templates_an_extension_into_a_mime_type():
    # `image/<ext>` yields the invalid `image/jpg` for a .jpg case.
    prompt = (AGENTS / "llm2bedrock-prompt-evaluator.md").read_text()
    bad = [f"line {n}: {l.strip()[:90]}"
           for n, l in enumerate(prompt.splitlines(), 1)
           if "image/<ext>" in l or "'format': <ext>" in l or '"format": <ext>' in l]
    assert not bad, (
        "extension templated directly into a wire format; use image_input helpers "
        "(.jpg -> jpeg / image/jpeg):\n  " + "\n  ".join(bad))


# --- Guard: golden-case field names, derived from the canonical record ----------
# The evaluator reads golden cases by key. A key that does not exist in the record
# the log-ingestor writes raises KeyError before any API call, which no unit test
# reaches because the loop lives in prompt text.

def _canonical_case_fields() -> set[str]:
    """Field names from the canonical prompts.jsonl record in the log-ingestor prompt."""
    text = (AGENTS / "llm2bedrock-log-ingestor.md").read_text()
    marker = "Write each entry as one JSON object per line"
    start = text.index(marker)
    block = text[text.index("```json", start) + len("```json"):]
    block = block[:block.index("```")]
    record = json.loads(block)
    assert "user_prompt" in record, "canonical record shape changed — revisit this guard"
    return set(record)


def test_evaluator_reads_only_canonical_golden_case_fields():
    fields = _canonical_case_fields()
    prompt = (AGENTS / "llm2bedrock-prompt-evaluator.md").read_text()
    # Subscripts on the per-case variables used in the §8 / §10 loops.
    subscript = re.compile(r"\b(?:case|prompt|entry)\[[\"']([a-z_]+)[\"']\]")
    getter = re.compile(r"\b(?:case|prompt|entry)\.get\([\"']([a-z_]+)[\"']")
    offenders = []
    for lineno, line in enumerate(prompt.splitlines(), 1):
        for key in subscript.findall(line) + getter.findall(line):
            if key not in fields:
                offenders.append(f"llm2bedrock-prompt-evaluator.md:{lineno} -> {key!r}")
    assert not offenders, (
        "evaluator reads golden-case fields absent from the canonical record "
        f"(fields: {sorted(fields)}):\n  " + "\n  ".join(offenders))


def test_documented_responses_image_blocks_set_detail():
    # Mirrors the helper-level test, for the image blocks written inline in prompts.
    prompt = (AGENTS / "llm2bedrock-prompt-evaluator.md").read_text()
    bad = [f"line {n}: {l.strip()[:90]}"
           for n, l in enumerate(prompt.splitlines(), 1)
           if '"type": "input_image"' in l and '"detail"' not in l]
    assert not bad, (
        "inline input_image block without the SDK-required `detail` field:\n  " + "\n  ".join(bad))
