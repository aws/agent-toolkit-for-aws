# Gemini → Bedrock Behavior Deltas

> v1 — last verified: 2026-05-21

Per-delta reference for Google Gemini → Bedrock parameter-surface differences. Loaded by `behavior-delta-detection` skill when `source_provider == "gemini"`.

Each delta block contains: slug, `option_set_id` (for ux_choice deltas), source param/range, target param/range, `detect_grep` recipe, code template, `resolution_kind`.

In the `detect_grep` recipes below, `<REPO>` is the repository path supplied in your context (the analyzer that loads this skill receives it). Substitute it before running.

---

## temperature-range-mismatch

- `resolution_kind`: `ux_choice`
- `option_set_id`: `range_narrowed`
- Source (Gemini): `temperature ∈ [0, 2]`
- Target (Bedrock/Claude): `temperature ∈ [0, 1]`
- **Bedrock REJECTS out-of-range** with `ValidationException`. Bedrock does NOT silently clamp. All clamp/rescale templates MUST include the explicit transformation.

### detect_grep

```bash
grep -rEn 'Slider\([^)]*[Tt]emperature' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
grep -rEn 'NumberInput\([^)]*[Tt]emperature' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
grep -rEn '[Tt]emperature.*max[[:space:]]*=[[:space:]]*[12](\.[0-9]+)?' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
grep -rEn 'temperature[[:space:]]*=[[:space:]]*1\.[2-9]|temperature[[:space:]]*=[[:space:]]*[2]\.[0-9]+' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
grep -rEn 'GenerationConfig\([^)]*temperature' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
```

`user_visible` classification: same rules as in the OpenAI reference.

### Code templates

Identical to OpenAI's `temperature-range-mismatch` templates — the source range and target range are the same. Substitute Gemini SDK call sites for OpenAI ones (e.g., `model.generate_content(prompt, generation_config=GenerationConfig(temperature=...))` → `bedrock.converse(...)`).

See `openai-to-bedrock.md` § `temperature-range-mismatch` § Code templates for the full set: `range_narrowed_1` (Cap UI), `range_narrowed_2` (Linear rescale), `range_narrowed_3` (Keep + note), `range_narrowed_4` (Fail loud).

---

## top-p-range-match

- `resolution_kind`: `impl_path`
- Source (Gemini): `top_p ∈ [0, 1]`
- Target (Bedrock/Claude): `top_p ∈ [0, 1]`

De-facto no-op. Listed here so the analyzer/rewriter don't assume there's a delta to ask about. **Default action**: pass through unchanged. Document in the rewriter's returned notes field:

```
top_p: passed through (Gemini and Claude both accept [0, 1])
```

---

## candidate-count-removed

- `resolution_kind`: `ux_choice`
- `option_set_id`: `parameter_removed`
- Source (Gemini): `candidate_count ∈ [1, 8]` — Gemini can return multiple candidates per request.
- Target (Bedrock Converse): single response only. There is no equivalent.

### detect_grep

```bash
grep -rEn 'candidate_count' <REPO> --include="*.py" --include="*.js" --include="*.ts" --include="*.json" | grep -v node_modules | grep -v __pycache__
grep -rEn '[Cc]andidate.*[Cc]ount' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
grep -rEn '"Number of (responses|candidates|completions)"' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
```

Hits inside a UI Slider/NumberInput labeled "Number of responses" / "Candidate count" → `user_visible: true`. Hits as a hardcoded constant in non-UI backend code → `user_visible: false`.

### Code templates

Use the `parameter_removed` set from the skill (see `SKILL.md` § Option set: parameter_removed). Substitute the Gemini SDK call site:

```python
# Before
response = model.generate_content(prompt, generation_config=GenerationConfig(candidate_count=3, temperature=0.7))
choices = [c.content.parts[0].text for c in response.candidates]

# After (option parameter_removed_1: drop control + remove from API)
# UI: remove the candidate-count slider/input.
# Backend: single response from converse.
response = bedrock.converse(modelId=..., messages=messages_bedrock, inferenceConfig={"temperature": 0.7})
choice = response["output"]["message"]["content"][0]["text"]

# If the calling code expected a list of choices, change the consumer to handle a single result.
```

If the source code consumes multiple candidates (e.g., `response.candidates[2]`), flag it in the rewriter's returned notes field as a potential downstream consumer that needs attention — not just a UI change.

---

## safety-settings-incompatible

- `resolution_kind`: `impl_path`
- Source (Gemini): `safety_settings: list[SafetySetting]` — fine-grained controls per harm category (HARM_CATEGORY_HARASSMENT, HARM_CATEGORY_HATE_SPEECH, HARM_CATEGORY_SEXUALLY_EXPLICIT, HARM_CATEGORY_DANGEROUS_CONTENT) with thresholds (BLOCK_NONE through BLOCK_LOW_AND_ABOVE).
- Target (Bedrock): no direct equivalent. Bedrock Guardrails is the architectural counterpart, but it's a separate AWS resource configured outside the API call.

### Default action (v1)

Drop the `safety_settings` parameter from the request. Add a note recommending the customer adopt **Bedrock Guardrails** as a follow-up. Do NOT attempt to auto-translate Gemini categories to Guardrails — the threshold model is different and a wrong translation could weaken safety.

Document in the rewriter's returned notes field:

```
safety_settings: dropped (no automatic mapping to Bedrock). Recommend setting up Bedrock Guardrails for content moderation: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html
```

### detect_grep

```bash
grep -rEn 'safety_settings|SafetySetting|HARM_CATEGORY' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
```

(v2 may add a `parameter_replaced` option set with auto-mapping to Guardrails. Not in scope for v1.)

---

## Adding a new delta

Same conventions as `openai-to-bedrock.md`. Update the "last verified" date in this file's header.
