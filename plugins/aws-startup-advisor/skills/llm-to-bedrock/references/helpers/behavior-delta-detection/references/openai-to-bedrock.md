# OpenAI → Bedrock Behavior Deltas

> v1 — last verified: 2026-05-21

Per-delta reference for OpenAI → Bedrock parameter-surface differences. Loaded by `behavior-delta-detection` skill when `source_provider == "openai"`.

Each delta block contains: slug, `option_set_id` (for ux_choice deltas), source param/range, target param/range, `detect_grep` recipe, code template, `resolution_kind`.

In the `detect_grep` recipes below, `<REPO>` is the repository path supplied in your context (the analyzer that loads this skill receives it). Substitute it before running.

---

## Same-model (mantle) deltas

**Read this section INSTEAD of the parameter-surface sections below when the resolved target is a proprietary GPT model on `bedrock-mantle`** (`openai.gpt-5.6-sol` / `-terra` / `-luna`, `openai.gpt-5.5`, `openai.gpt-5.4`). The model is unchanged, so temperature ranges, penalty parameters, and stop-sequence limits are unchanged — do not raise those as deltas. The deltas here are about the API surface and the endpoint, not about model behavior.

## chat-completions-to-responses

- `resolution_kind`: `ux_choice`
- Source (OpenAI): `client.chat.completions.create(...)`, `messages=[...]`, reads `choices[0].message.content`
- Target (mantle GPT): `client.responses.create(...)`, `input=...`, reads `output_text`
- Chat Completions support is **unverified** for these models — every AWS sample uses Responses, and no GPT model card lists Chat Completions as supported. Treat a Chat Completions source as requiring a reshape, and probe the target account before committing to either surface.

### detect_grep

```bash
grep -rEn 'chat\.completions\.create' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
grep -rEn 'choices\[0\]\.(message|delta)' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
```

`user_visible` classification: `true` when the response shape is surfaced to users or persisted (chat transcript rendering, stored conversation history, streaming to a UI); `false` for internal one-shot calls whose text is consumed programmatically.

## reasoning-items-must-round-trip

- `resolution_kind`: `impl_path`
- These models reason before responding. In multi-turn and tool-calling flows the model's output items — which may include reasoning items — must be appended to the next request's `input`. Dropping them degrades multi-step and tool-use quality without raising an error, so this fails silently.
- Detection: any Responses-API call that builds the next turn's `input` from message text alone rather than appending `response.output`.

### detect_grep

```bash
grep -rEn 'responses\.create' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
grep -rEn 'function_call_output|tool_call' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
```

## endpoint-path-and-credential

- `resolution_kind`: `impl_path`
- Base URL must be `https://bedrock-mantle.{region}.api.aws/openai/v1` — the `openai/v1` segment is required and differs from the `v1` path other mantle models use. A hardcoded `/v1` returns 404.
- The API key must be a Bedrock API key or an auto-refreshing token provider, **not** an existing OpenAI key. A long-lived `OPENAI_API_KEY` read from the environment will fail authentication.
- IAM must grant `bedrock-mantle:*` actions; `bedrock:InvokeModel` does not authorize these models.
- Not user-visible — always `user_visible: false`, `resolution_kind: impl_path`. Apply without prompting.

## prompt-caching-availability

- `resolution_kind`: `impl_path`
- Prompt caching is listed as supported on GPT-5.6 only. Do not emit caching configuration for `openai.gpt-5.5` or `openai.gpt-5.4`.

---

## Cross-family parameter-surface deltas

Everything below applies when the target is **not** the same model — Claude, Nova, DeepSeek, or `gpt-oss`.

---

## temperature-range-mismatch

- `resolution_kind`: `ux_choice`
- `option_set_id`: `range_narrowed`
- Source (OpenAI): `temperature ∈ [0, 2]`
- Target (Bedrock/Claude): `temperature ∈ [0, 1]`
- **Bedrock REJECTS out-of-range** with `ValidationException: temperature must be ≤ 1`. Bedrock does NOT silently clamp. All clamp/rescale templates below MUST include the explicit transformation.

### detect_grep

Run all of these and merge hits. Each line should be evaluated for `user_visible`:

```bash
grep -rEn 'Slider\([^)]*[Tt]emperature' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
grep -rEn 'NumberInput\([^)]*[Tt]emperature' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
grep -rEn '[Tt]emperature.*max[[:space:]]*=[[:space:]]*[12](\.[0-9]+)?' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
grep -rEn 'temperature[[:space:]]*=[[:space:]]*1\.[2-9]|temperature[[:space:]]*=[[:space:]]*[2]\.[0-9]+' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
```

`user_visible` classification:

- `true` if hit is inside a `Slider(...)`, `NumberInput(...)`, form field config, env var read by user, or CLI flag definition.
- `false` if hit is a hardcoded constant in backend code with no UI/config exposure.

### Code templates

#### `range_narrowed_1` — Cap UI to target range

Modify the user-visible control to use target's range. Backend passes value through unchanged.

```python
# Before
Slider(id="Temperature", initial=1, min=0, max=2, step=0.1)

# After
Slider(id="Temperature", initial=1, min=0, max=1, step=0.1)
```

```typescript
// Before
<Slider name="temperature" min={0} max={2} step={0.1} defaultValue={1} />

// After
<Slider name="temperature" min={0} max={1} step={0.1} defaultValue={1} />
```

#### `range_narrowed_2` — Linear rescale

UI keeps source range; backend rescales before API call.

```python
# UI unchanged: Slider(id="Temperature", initial=1, min=0, max=2, step=0.1)

# At call site:
SOURCE_MAX = 2.0
TARGET_MAX = 1.0
def to_bedrock_temperature(ui_value: float) -> float:
    # Rescale [0, SOURCE_MAX] to [0, TARGET_MAX] preserving relative intent.
    return ui_value * (TARGET_MAX / SOURCE_MAX)

temperature = to_bedrock_temperature(cl.user_session.get("temperature"))
chat_llm = ChatBedrockConverse(model_id=model_id, temperature=temperature, ...)
```

```typescript
// UI unchanged: max={2}
const SOURCE_MAX = 2.0;
const TARGET_MAX = 1.0;
const toBedrockTemperature = (uiValue: number) => uiValue * (TARGET_MAX / SOURCE_MAX);

const temperature = toBedrockTemperature(userSession.get("temperature"));
```

#### `range_narrowed_3` — Keep UI + add description note

UI keeps source range; add a description; backend clamps.

```python
# Before
Slider(id="Temperature", initial=1, min=0, max=2, step=0.1)

# After
Slider(
    id="Temperature",
    initial=1,
    min=0,
    max=2,
    step=0.1,
    description="Note: values above 1.0 are clamped to 1.0 (Bedrock/Claude limit)",
)

# At call site:
temperature = min(cl.user_session.get("temperature"), 1.0)
```

#### `range_narrowed_4` — Keep UI + fail loud

UI keeps source range; backend raises a clear error if out-of-range.

```python
# UI unchanged.

# At call site:
temperature = cl.user_session.get("temperature")
if temperature > 1.0:
    raise ValueError(
        f"Bedrock/Claude only supports temperature 0-1; got {temperature}. "
        "Lower the slider value or migrate to a different option."
    )
```

---

## presence-penalty-removed

- `resolution_kind`: `ux_choice`
- `option_set_id`: `parameter_removed`
- Source (OpenAI): `presence_penalty ∈ [-2.0, 2.0]`
- Target (Bedrock Converse): not supported. There is no equivalent.

### detect_grep

```bash
grep -rEn 'presence_penalty' <REPO> --include="*.py" --include="*.js" --include="*.ts" --include="*.json" | grep -v node_modules | grep -v __pycache__
grep -rEn '[Pp]resence.*[Pp]enalty' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
```

### Code templates

#### `parameter_removed_1` — Drop control + remove from API

```python
# Before:
Slider(id="PresencePenalty", initial=0, min=-2, max=2, step=0.1)
# ... later:
client.chat.completions.create(model=..., messages=..., presence_penalty=cl.user_session.get("presence_penalty"))

# After: remove the Slider entirely. Remove the parameter from the API call.
client.converse(modelId=..., messages=...)  # no presence_penalty
```

#### `parameter_removed_2` — Hide control + ignore in API

```python
# Before:
Slider(id="PresencePenalty", initial=0, min=-2, max=2, step=0.1)

# After: keep it in the form but disable, and remove the param from the API call.
Slider(
    id="PresencePenalty",
    initial=0,
    min=-2,
    max=2,
    step=0.1,
    disabled=True,
    description="Disabled — Bedrock has no presence_penalty equivalent",
)
# API call as in option 1: parameter omitted.
```

#### `parameter_removed_3` — Inert decoration

UI control rendered as before, accepts input, but the value is discarded.

```python
# UI unchanged.

# At call site: read the value but do not pass it to Bedrock.
_ = cl.user_session.get("presence_penalty")  # discarded
client.converse(modelId=..., messages=...)
```

---

## frequency-penalty-removed

Identical structure to `presence-penalty-removed`. Same option set, same templates with `frequency_penalty` substituted.

### detect_grep

```bash
grep -rEn 'frequency_penalty' <REPO> --include="*.py" --include="*.js" --include="*.ts" --include="*.json" | grep -v node_modules | grep -v __pycache__
grep -rEn '[Ff]requency.*[Pp]enalty' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
```

---

## top-p-default-mismatch

- `resolution_kind`: `impl_path`
- Source (OpenAI): `top_p` default `1.0`, range `[0, 1]`
- Target (Bedrock/Claude): `top_p` default `0.999`, range `[0, 1]`

The range is identical. The default differs by 0.001 — too small to be worth a user question. **Default action**: pass the user's `top_p` value through unchanged. If the source code did not set `top_p` explicitly, do not set it on the Bedrock side either (Bedrock's own default kicks in).

Document the choice in the rewriter's returned notes field:

```
top_p: passed through unchanged (OpenAI default 1.0, Claude default 0.999, range identical)
```

---

## response-format-json-mode-removed

- `resolution_kind`: `impl_path`
- Source (OpenAI): `response_format={"type": "json_object"}` or `{"type": "json_schema", "json_schema": {...}}`
- Target (Bedrock/Claude): no `response_format` parameter. Two viable patterns:

### Default selection logic

Read the source code at the call site. If the call already provides a JSON schema (e.g., `response_format={"type": "json_schema", "json_schema": {"name": ..., "schema": {...}}}`), prefer **tool_use**. Otherwise (plain `"json_object"`) use **prefill**.

#### Pattern A — tool_use (preferred when schema is defined)

```python
# Before
response = client.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    response_format={"type": "json_schema", "json_schema": {"name": "Result", "schema": {"type": "object", "properties": {"answer": {"type": "string"}}}}},
)
result = json.loads(response.choices[0].message.content)

# After: model is forced to call the tool, which acts as the JSON schema.
tool_config = {
    "tools": [{"toolSpec": {"name": "Result", "inputSchema": {"json": {"type": "object", "properties": {"answer": {"type": "string"}}}}}}],
    "toolChoice": {"tool": {"name": "Result"}},
}
response = bedrock.converse(modelId="us.anthropic.claude-sonnet-4-6", messages=messages_bedrock, toolConfig=tool_config)
tool_use_block = next(b for b in response["output"]["message"]["content"] if "toolUse" in b)
result = tool_use_block["toolUse"]["input"]
```

#### Pattern B — prefill (when no schema is given)

```python
# Before
response = client.chat.completions.create(
    model="gpt-4o",
    messages=messages,
    response_format={"type": "json_object"},
)

# After: prefill the assistant turn with `{` to constrain the start of output.
messages_bedrock = messages_bedrock + [{"role": "assistant", "content": [{"text": "{"}]}]
response = bedrock.converse(modelId=..., messages=messages_bedrock, ...)
output = "{" + response["output"]["message"]["content"][0]["text"]
result = json.loads(output)
```

### detect_grep

```bash
grep -rEn 'response_format' <REPO> --include="*.py" --include="*.js" --include="*.ts" | grep -v node_modules | grep -v __pycache__
```

Document the choice in the rewriter's returned notes field, e.g.:

```
response_format: switched to tool_use (schema present at app.py:42); see bedrock-known-fixes for details
```

---

## Adding a new delta

When adding a delta to this reference:

1. Pick `resolution_kind` and (if `ux_choice`) `option_set_id` from the skill's defined sets.
2. Provide a `detect_grep` recipe narrow enough to avoid false positives. Test it on at least one real code sample.
3. For `ux_choice`, provide a code template per option in at least Python (and TS/JS if applicable).
4. Update the "last verified" date in this file's header.
