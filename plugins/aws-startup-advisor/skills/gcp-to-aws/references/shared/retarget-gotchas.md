# Retarget Gotchas: Framework-Specific Migration Pitfalls

> Loaded by `design-ai.md` Step 0.6 when `agentic_profile.is_agentic == true` AND `ai_constraints.agentic.migration_approach == "retarget"`.
> Also useful context for `generate-ai.md` when generating retarget migration plans.

These are real issues startups hit when keeping their existing framework and swapping the model layer to Bedrock. A simple "swap `ChatOpenAI` for `ChatBedrock`" understates the work. This file documents what actually breaks and how to fix it.

---

## LangChain / LangGraph

### Tool calling schema differences

**Problem:** OpenAI and Claude handle tool calls differently. OpenAI returns `tool_calls` as a list with `function.arguments` as a JSON string. Claude via Bedrock returns tool use blocks with `input` as a parsed object. LangChain's `ChatBedrock` abstracts most of this, but edge cases leak through.

**What breaks:**

- Custom output parsers that assume OpenAI's `tool_calls` format
- Code that accesses `response.additional_kwargs["tool_calls"]` directly instead of using LangChain's `ToolMessage` abstraction
- Parallel tool calls: OpenAI supports multiple tool calls in one response; Claude does too, but some Bedrock models (Nova, Llama) may not

**Fix:** Use LangChain's standardized tool calling interface (`bind_tools()`, `ToolMessage`). Don't access raw response format. Test parallel tool calls explicitly with your target Bedrock model.

### `with_structured_output` behavior

**Problem:** `ChatOpenAI.with_structured_output(schema)` uses OpenAI's native JSON mode or function calling. `ChatBedrock.with_structured_output(schema)` uses Claude's tool use to enforce structure. The output is the same, but error handling differs — Claude may refuse to fill required fields if the prompt doesn't provide enough context, returning a partial object instead of raising an error.

**Fix:** Validate structured output after every call. Add explicit instructions in the prompt for each required field. Test with edge-case inputs where the model might not have enough context to fill all fields.

### Streaming differences

**Problem:** `ChatBedrock` streaming works but the chunk format differs from `ChatOpenAI`. Code that processes `AIMessageChunk` objects and checks for `tool_call_chunks` may need adjustment.

**Fix:** Use LangChain's `astream_events` API (v2) which normalizes events across providers. Avoid directly inspecting chunk internals.

### Async behavior

**Problem:** `ChatBedrock` wraps synchronous boto3 calls in threads for async. It's not truly async like `ChatOpenAI`'s native async client. Under high concurrency, this can cause thread pool exhaustion.

**Fix:** For high-concurrency LangGraph deployments, increase the thread pool size or use `ChatBedrockConverse` (the newer Converse API-based client) which has better async support. Monitor thread usage in production.

### LangGraph checkpointer compatibility

**Problem:** LangGraph checkpoints serialize the full state including message objects. If you switch models mid-thread (e.g., testing Bedrock on an existing thread), the deserialized messages may have provider-specific metadata that the new model doesn't understand.

**Fix:** Start fresh threads when switching providers. Don't resume an OpenAI-started thread with a Bedrock model. Use the feature flag approach (separate threads per provider) rather than mid-thread switching.

---

## CrewAI

### Model configuration format

**Problem:** CrewAI uses LiteLLM under the hood for model routing. The model string format for Bedrock is `bedrock/model-id` (e.g., `bedrock/us.anthropic.claude-sonnet-5`). Getting the format wrong produces cryptic LiteLLM errors.

**Fix:** Use the exact format: `bedrock/{full_model_id}`. Set `AWS_REGION_NAME` environment variable. Verify with a simple LiteLLM test call before running the full crew.

### Tool schema formatting

**Problem:** CrewAI formats tool descriptions into the prompt differently per model. Claude expects specific XML-like formatting for best tool use results. If CrewAI's internal prompt formatting doesn't match what Claude expects, tool selection accuracy drops.

**Fix:** Update to latest CrewAI version (tool formatting improvements ship frequently). Test tool selection accuracy with your specific tools — if accuracy drops, add more explicit tool descriptions with examples. Consider using `@tool` decorator with detailed `description` parameter.

### Process type and model capability

**Problem:** CrewAI's `Process.hierarchical` requires the manager model to reliably delegate tasks. Some Bedrock models (especially smaller ones like Nova Lite, Llama variants) are less reliable at hierarchical delegation than GPT-4o or Claude Sonnet.

**Fix:** For hierarchical processes, use Claude Sonnet 5 as the manager model (best tool-use reliability on Bedrock). Specialist agents can use cheaper models. Don't use Nova Micro or Llama Scout as the manager in hierarchical crews.

### Memory and context window

**Problem:** CrewAI accumulates conversation history across tasks. With GPT-4o (128K context), this rarely overflows. If you switch to a model with smaller context (Nova Pro 300K is fine, but Nova Micro 128K or Haiku 200K might be tight for long crews), tasks later in the sequence may lose context.

**Fix:** Check your crew's typical context accumulation. If tasks are long, use a model with >= 200K context for the crew, or enable CrewAI's memory summarization to keep context compact.

---

## AutoGen

### Response format assumptions

**Problem:** AutoGen's `ConversableAgent` parses model responses expecting OpenAI's format. When using Bedrock via LiteLLM, the response translation is usually correct, but edge cases exist — especially around `function_call` (legacy) vs `tool_calls` (current) format.

**Fix:** Use AutoGen >= 0.4 which has better multi-provider support. Configure the model client explicitly rather than relying on auto-detection. Test the full conversation flow, not just single turns.

### GroupChat speaker selection

**Problem:** AutoGen's `GroupChat` uses the model to select the next speaker. This is a meta-task that requires the model to understand the conversation flow and pick the right agent. Claude handles this well; smaller Bedrock models may select speakers inconsistently.

**Fix:** Use Claude Sonnet 5 for the GroupChat manager. If using a cheaper model, consider switching to `round_robin` or custom `speaker_selection_method` instead of model-based selection.

### Code execution sandbox

**Problem:** AutoGen's `UserProxyAgent` with `code_execution_config` executes code locally. This is unrelated to the model swap, but startups often discover during migration that their code execution setup is fragile. The model swap can change code generation patterns (Claude generates slightly different Python than GPT-4o), breaking assumptions in the execution environment.

**Fix:** Test code generation + execution end-to-end. Claude tends to be more verbose in code comments and may use different library idioms. Ensure your execution sandbox has all required packages.

---

## OpenAI SDK (Direct — not Agents SDK)

### Converse API vs Chat Completions API

**Problem:** The Bedrock Converse API is similar to OpenAI's Chat Completions but not identical. Key differences:

- No `n` parameter (multiple completions per request)
- No `logprobs`
- No `response_format: { type: "json_schema", schema: {...} }` (use tool use for structured output instead)
- Different token counting (Bedrock uses model-specific tokenizers)
- No `seed` parameter for reproducibility

**Fix:** Audit your OpenAI API calls for parameters that don't have Converse API equivalents. Replace `response_format` with tool use for structured output. Remove `n > 1` calls (make multiple sequential calls instead). Accept that exact reproducibility (`seed`) is not available.

### Function calling format

**Problem:** OpenAI uses `functions` (legacy) or `tools` with `type: "function"`. Bedrock Converse uses `toolConfig` with `tools` array. The schema format is similar but not identical — Bedrock requires `inputSchema` with a JSON Schema object, while OpenAI uses `parameters`.

**Fix:** If using the provider adapter pattern (generated by this plugin), the adapter handles format translation. If migrating directly, map: `tools[].function.parameters` → `tools[].toolSpec.inputSchema.json`.

### Streaming event format

**Problem:** OpenAI streams `ChatCompletionChunk` objects with `delta` fields. Bedrock Converse streams `contentBlockDelta`, `contentBlockStart`, `contentBlockStop`, `messageStop` events. The event structure is fundamentally different.

**Fix:** Use the provider adapter's `generate_stream()` method which normalizes both to a simple string iterator. If migrating directly, rewrite your stream processing loop to handle Bedrock's event types.

---

## Common Across All Frameworks

### Prompt sensitivity

**Problem:** Prompts optimized for GPT-4o may not perform identically on Claude Sonnet 5. Claude tends to be more literal and instruction-following; GPT-4o is more "creative" with ambiguous instructions. System prompts that rely on GPT-4o's implicit behaviors may need adjustment.

**Fix:** Test your top 20 most-used prompts on the target Bedrock model. Adjust prompts that produce degraded output. Claude generally responds better to explicit, structured instructions with clear formatting requirements.

### Rate limiting and throttling

**Problem:** OpenAI rate limits are per-API-key with clear headers. Bedrock throttling is per-account per-model per-region with different error codes (`ThrottlingException`). Retry logic built for OpenAI's `429` responses may not handle Bedrock's throttling correctly.

**Fix:** Update retry logic to handle `ThrottlingException` and `ServiceUnavailableException`. Use exponential backoff. For high-throughput workloads, request quota increases via AWS Support or use provisioned throughput.

### Token counting

**Problem:** OpenAI's `tiktoken` library gives exact token counts for GPT models. Bedrock models use different tokenizers (Claude uses its own, Llama uses SentencePiece, etc.). Code that pre-calculates token budgets using `tiktoken` will be wrong for Bedrock models.

**Fix:** Remove `tiktoken` dependency for Bedrock models. Use Bedrock's response metadata (`usage.inputTokens`, `usage.outputTokens`) for post-hoc counting. For pre-calculation, use conservative estimates (4 chars per token as rough heuristic) or the model-specific tokenizer if available.

### Error handling

**Problem:** OpenAI errors are well-documented HTTP errors (400, 401, 429, 500). Bedrock errors are AWS SDK exceptions (`ValidationException`, `ThrottlingException`, `ModelNotReadyException`, `AccessDeniedException`). Error handling code built for OpenAI's error taxonomy won't catch Bedrock failures.

**Fix:** Map error handlers: OpenAI `401` → Bedrock `AccessDeniedException`, OpenAI `429` → Bedrock `ThrottlingException`, OpenAI `400` → Bedrock `ValidationException`. Add handlers for Bedrock-specific errors like `ModelNotReadyException` (model access not yet enabled).
