# GenAI must-ask floor

For any SCUTO line whose `serviceCode` touches Bedrock
(`AmazonBedrock`, `AmazonBedrockService`, `AmazonBedrockFoundationModels`,
`AmazonBedrockAgentCore`, Bedrock embeddings or guardrails, Bedrock
third-party model marketplaces), the cost of that line
is dominated by parameters that vary 10× to 60× between answers. These
parameters MUST be asked. The usage step MUST NOT fill them with a number
of its own: it uses the user's answers, and the defaults at the end of this
file only where the user can't describe a size.

Ask every parameter below that applies to the architecture:

- **Model choice, per role.** The model used for each distinct role
  (supervisor, specialist, embedding, image, voice). Up to 60× price
  difference between models at the same role. If the user names only one
  model, confirm it covers every role. Step 4 of the skill asks this
  before the lines are picked, so use its answers rather than asking
  again. A role whose model the user couldn't choose has no lines and
  isn't priced.
- **The shape of a call, never its token counts.** Users rarely know
  tokens, so ask what goes in and out of a call, per model, in their
  terms, and derive the tokens with `scripts/derive_genai_tokens.py`:
  - how many invocations (requests, turns, jobs) and model calls a month;
  - what every call repeats, such as the system prompt or template
    (the prefix);
  - what each invocation adds, such as the user's message (the fresh
    input);
  - for an agent, what each tool call adds to the context, the call and
    its result (the step);
  - how long a reply is (the output).

  Turn sizes said in words into tokens with this scale: a sentence is
  about 30 tokens, a paragraph 150, a page 600, a few pages 2,000 and a
  long document 10,000. Use a size the user gives in tokens as given.
- **Tool calls per query or turn.** When the architecture is agentic
  (Bedrock Agents, AgentCore, tool-using workflow). Each tool call is a
  separate model invocation; a query with 4 turns and 3 tool calls is
  16 invocations.
- **Turns per conversation.** When the architecture is conversational
  (chatbot, assistant, support agent). Multiplier on every per-turn
  cost.
- **When the cache starts cold.** When prompt caching is on (Step 4 of
  the skill asks), how many sessions a month start with an empty cache.
  For a fixed template called all day, it is the templates × 12 refreshes
  an hour × the hours it runs, because the cache lasts 5 minutes. The
  script writes the prefix to the cache once per cold start and each
  step's addition once, and reads the rest; on an agent that caches,
  these are usually the largest Bedrock lines.
- **Guardrail text per call.** When guardrails are applied: how many
  calls check text a month, whether several items go in one call, and
  roughly how many characters one call checks. A text unit is up to 1,000
  characters of one call, rounded up, and bills once for each policy the
  guardrail runs, so nine 200-character messages in one call are 2 units,
  not 9. Count units per call, never per item, unless each item is its own
  call.
- **Processing-mode mix.** When the architecture routes between modes
  such as quick/balanced/deep, ask the share of traffic per mode and the
  model used in each mode. The weighted average decides the effective
  rate.

If the user can't give the model or the number of invocations or calls,
that line receives `source: UNKNOWN` and is excluded from the total. A
size the user can't describe takes its default, tagged `ASSUMED`
with the 0.5×-3× band: a prefix of 2,000 tokens, fresh input of 500, a
step of 2,000 and an output of 500. Every run then sizes the same unknown
the same way. If the script warns that the invocations and the stated
calls disagree, ask which holds before pricing. Suggest the user measure
with a small pilot — a representative sample (10-100 queries) through the target model,
capturing input/output token counts from Bedrock's response `usage` field
or CloudWatch Logs, so they can come back with a measured average.
