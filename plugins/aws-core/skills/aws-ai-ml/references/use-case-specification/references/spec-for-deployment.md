# Spec for Deployment

## Phase 1: Discovery (1–3 turns)

Review what is already known from the conversation so far, then identify what is still missing. You need:

- **What** is the problem the user is trying to solve (the business problem)
- **Who** will use the model and in what context
- **Deployment preferences** — gather the user's preferences in natural language. Don't require specific values or formats. Just understand what they need.

**Core questions to ask (1–2 turns max):**

1. What should the model do? (task/use case)
2. Any size or cost preferences?

That's it for the default flow. The table below lists additional preferences you can capture **if the user volunteers them or asks to drill down** — but do not ask about these unprompted:

| Preference | What to ask about | Examples of user answers |
|---|---|---|
| **Task** | What should the model do? | "text generation", "chatbot", "translate documents", "classify images" |
| **Data type** | What kind of data? | "text", "images", "audio", "mixed text and images" |
| **Size preference** | How big/small? Cost sensitivity? | "small and fast", "as capable as possible", "under 10B params", "don't care" |
| **Deployment target** | Where will it run? | "SageMaker", "Bedrock", "wherever is easiest", "don't care" |
| **License preference** | Any restrictions? | "must be Apache 2.0", "open source only", "no restrictions" |
| **Context length** | How much input text? | "long documents", "short messages", "don't need much" |
| **Languages** | What languages? | "English only", "multilingual", "Japanese and English" |
| **Model type** | Open weights or proprietary? | "open source", "proprietary is fine", "no preference" |
| **Recency** | Want the latest? | "latest available", "newest", "don't care" |

**Guidelines**:

- Infer from context — "chatbot" implies task=text generation, data type=text
- Only ask the core questions above. Do NOT walk through the preferences table asking each one.
- If the user volunteers additional constraints (e.g., "must be Apache 2.0"), capture them.
- Record the user's words as-is. Do NOT map to specific keyword values — that happens later in model-selection.
- If the user says "I don't care" or "any" for a preference, omit it from the spec.

⏸ Wait for user after each clarifying question.

## Phase 2: Produce Spec

1. Save all generated artifacts under the project directory structure defined by the directory-management reference, if available.
2. Synthesize the information into a Markdown document called `[relevant_title]_use_case_spec.md`:

```markdown
# Use Case Specification

## Intent

Deploy base model

## Business Problem

[Concise problem statement + what the model will do]

## Primary Users

[Who uses the model and in what context]

## Deployment Constraints

- **Task**: [user's words — e.g., "text generation", "chatbot", "image classification"]
- **Data type**: [user's words — e.g., "text", "images", "multimodal"]
- **Size preference**: [user's words — e.g., "small and fast", "under 10B", "large"]
- **Deployment target**: [user's words — e.g., "SageMaker", "Bedrock", "either"]
- **License**: [user's words — e.g., "Apache 2.0", "open source", "any"]
- **Context window**: [user's words — e.g., "long documents", "short messages"]
- **Languages**: [user's words — e.g., "English", "multilingual"]
- **Model type**: [user's words — e.g., "open source", "proprietary OK"]
- **Recency**: [user's words — e.g., "latest available", "newest"]

```

Only include preferences that have a known value. Omit fields the user didn't specify or said "any" / "don't care" for.

1. Present the spec to the user:

> I have put together a use case specification and saved it in [filename].
>
> A use case specification is a design principle recommended by the [AWS Responsible AI Lens](https://docs.aws.amazon.com/wellarchitected/latest/responsible-ai-lens/design-principles.html).
>
> [use case in human-readable format]
>
> Does this match your intent?

⏸ Wait for user approval.
