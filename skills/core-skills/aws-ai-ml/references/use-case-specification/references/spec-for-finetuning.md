# Spec for Fine-tuning

## Phase 1: Discovery (1–3 turns)

Review what is already known from the conversation so far, then identify what is still missing. You need these three things:

- **What** is the problem the user is trying to solve with model customization
- **Who** will use the finetuned model and in what context
- **Which** success criteria can be used to evaluate how well the custom model performs compared to the base model on a test set. Success criteria must be measurable by an LLM-as-a-Judge (e.g., response accuracy, tone adherence) — not things like latency or throughput.

**Guidelines**:

- Infer as much as possible from what the user has already said
- If the user gave examples, use them to fill gaps rather than asking again
- Only ask clarifying questions when you cannot infer the information needed for Phase 2
- If everything is already clear, say "You've given me a clear picture. I'll put together a use case specification now." and move to Phase 2.

⏸ Wait for user after each clarifying question.

## Phase 2: Produce Spec

1. Save all generated artifacts under the project directory structure defined by the directory-management reference, if available.
2. Synthesize the information into a Markdown document called `[relevant_title]_use_case_spec.md`:

   ```markdown
   # Use Case Specification
   
   ## Intent
   
   Fine-tune
   
   ## Business Problem
   
   [Concise problem statement + what the custom model will do]
   
   ## Primary Users
   
   [Who uses the model and in what context]
   
   ## Success Tenets
   
   1. **[Tenet Name]** — [Description of what success looks like, measurable by LLM-as-a-Judge]
   2. **[Tenet Name]** — [Description]
   3. **[Tenet Name]** — [Description]
   
   ```

3. Present the spec to the user:

> I have put together a use case specification and saved it in [filename].
>
> A use case specification is a design principle recommended by the [AWS Responsible AI Lens](https://docs.aws.amazon.com/wellarchitected/latest/responsible-ai-lens/design-principles.html).
>
> [use case in human-readable format]
>
> Does this match your intent?

⏸ Wait for user approval.
