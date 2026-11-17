# Spec Authoring Workflow

Create specifications for synthetic dataset generation using a field-driven approach.

## Workflow

1. **Understand use case** - Ask what the dataset is for and how it will be used. If model-selection and finetuning-technique skills have already run in this conversation, consider the selected fine-tuning technique and base model when designing the output schema.

2. **Gather requirements through conversation** - Have a back-and-forth discussion to understand:
   - Use case context (business problem, target audience, how data will be used)
   - Quality standards (what good data looks like for this use case)
   - Core data fields (P0 requirements - what the dataset MUST have)
   - Auxiliary fields (supporting fields that enhance realism/variation)
   - Generation constraints (rules that govern every record)
   - Data verification needs
   - **Verification mode** — do NOT ask here; this is a dedicated decision point in Step 5. In this step, only gather enough context to form a `deterministic` vs `llm-augmented` recommendation. See Step 5 for the full rules and Step 6 for the exact spec-file wording.
   - Whether conditional fields are needed (fields that depend on other field values)
   - **Output format** — determine the correct format based on the fine-tuning technique and model family. See [supported-output-formats.md](supported-output-formats.md) for the format selection guide and exact schemas. The output schema MUST match one of the 9 supported formats so the generated data passes the platform's format detector. **Exception: tabular use cases** produce `Custom` format (CSV rows) — this is valid and expected. See [sample-spec-tabular-augmentation.md](sample-spec-tabular-augmentation.md) for tabular templates.

   **Approach**:
   - Ask ONE question at a time - don't overwhelm the user with multiple questions in a single turn
   - Start by asking for an explanation of what they're trying to do
   - Use that explanation to infer answers to some questions
   - Follow up only on what you still need to know, one question at a time

3. **Determine CDG vs NCDG** — Before designing fields, determine whether the user has contextual data for the generator to reference. First check conversation history. **If you cannot find clear information from the conversation, Do NOT skip this step or assume NCDG without asking.** Ask the user explicitly:

   > "Do you have any reference documents that the generator should use as context when creating your data? For example:
   > - Source documents to summarize or extract from (PDFs, Word documents, text files, HTML)
   > - Existing examples or seed data (CSV, JSONL)
   > - Style guides, glossaries, or domain references
   > - Any files the generated data should be *grounded in*
   >
   > Supported formats: csv, db, doc, docx, html, json, jsonl, md, parquet, pdf, sql, sqlite, txt (max 1000 files, 10MB each).
   >
   > If yes, this becomes a **Contextual Data Generation (CDG)** job — the generator will reference your files to produce higher-quality, grounded output. If no, we'll generate entirely from scratch (NCDG)."

   **Rules:**
   - This step is mandatory — never skip it or assume NCDG without explicit user confirmation.
   - If the user says yes, collect the file paths/locations and declare them in the spec's Input Data section, per [spec-format-guide.md](spec-format-guide.md). Ask what role each file plays (seed examples, reference material, or source documents to generate from).
   - A file **you** attach rather than the user gets the same treatment — e.g. a sidecar you write during an iterative loop. Declare it in the Input Data section too; this does not depend on the answer above.
   - If the user says no **and you have not attached a file yourself**, omit the Input Data section from the spec entirely — no placeholder needed.
   - If the user is unsure, explain: contextual docs significantly improve quality when the generated data needs to be grounded in real domain knowledge, existing patterns, or specific terminology.

   ⏸ Wait for user.

4. **Dimension Analysis** - Based on the use case and requirements, propose key dimensions to vary and value coverage strategy:

   **Identify Key Dimensions**: Suggest relevant dimensions based on use case:
   - **Demographic**: age, location, language, cultural background, accessibility needs
   - **Behavioral**: experience level, usage patterns, interaction style
   - **Contextual**: time, setting, scenario complexity, urgency
   - **Content-based**: tone, length, formality, technical depth

   **Value Coverage Strategy**: For each dimension, recommend distribution:
   - **Common cases** (60-80%): Mainstream, frequently occurring values
   - **Edge cases** (15-30%): Underrepresented but important (minorities, accessibility, non-standard formats)
   - **Adversarial cases** (5-10%): Stress testing, boundary conditions, potential failure modes

   **Real-World Diversity**: Ensure coverage includes:
   - Cultural and linguistic diversity
   - Socioeconomic variation
   - Accessibility considerations (disabilities, assistive tech)
   - Geographic representation
   - Non-standard but valid cases

   Present your dimension analysis and get user feedback before finalizing field definitions.

5. **Select Verification Mode** — Before summarizing the spec, explicitly present the verification mode choice to the user as a dedicated decision point. Do NOT bury this in the spec summary or skip it.

   For example:

   > Before I write the spec, I need you to choose a **verification mode**. This controls how each generated record is checked for quality, and has a significant impact on generation time:
   >
   > **Deterministic** — Pure Python checks only (format, field presence, value ranges, word counts).
   > - ✅ Faster generation
   > - ✅ No extra LLM cost
   > - ❌ Cannot verify subjective quality (e.g., "is the tone actually empathetic?")
   >
   > **LLM-Augmented** — Adds an LLM call per record for semantic quality checks.
   > - ✅ Can better verify subjective quality (tone, accuracy, preference alignment)
   > - ❌ **Can increase end-to-end generation time by 2-3x** (synthetic dataset generation can already be a long-running process — this may multiply the wait)
   > - ❌ Additional Bedrock LLM cost per record
   >
   > **My recommendation:** [deterministic/llm-augmented] because [reason].
   >
   > Which mode would you like?

   **Rules:**
   - This step is mandatory — never skip it or auto-select without explicit user confirmation.
   - Always state the 2-3x latency impact clearly. Users must understand this before choosing.
   - Wait for the user to explicitly choose before proceeding.
   - If the user asks follow-up questions about the modes, answer them, then re-ask for their choice.

   ⏸ Wait for user.

6. **Summarize and explain the spec** - Before writing, present the proposed spec structure:
   - Explain each section (Use Case Context, Quality Standards, Input Data, Output Schema, Data Generation, Data Verification)
   - Describe what each section means and why we're structuring it this way
   - List the specific fields with their properties, grouped by generation step
   - Explain field types:
     - **Categorical**: Sample from a finite set of values with a distribution
     - **LLM-generated**: Generated by an LLM call, conditioned on other fields
     - **Programmatic**: Generated by deterministic code — Faker, templates, field copies, custom logic
   - When an Output Schema is defined, always include an output format compliance check in the Data Verification structural checks
   - Explain the chosen verification mode (`deterministic` vs `llm-augmented`) and why it's appropriate for this use case
   - **The spec file's Verification Mode section must be unambiguous to the downstream code-gen model.** The label alone is NOT sufficient — synthetic dataset generation determines and writes verification code purely from the spec file, and ambiguous language can cause it to generate the wrong type of verifier. Use the following exact directives based on the user's choice:
     - **When writing the spec with `deterministic` mode**, include this exact line in the Verification Mode section: "Do not use LLM to verify samples. All verification must be pure Python only. Do not make any LLM calls in the verification function."
     - **When writing the spec with `llm-augmented` mode**, include this exact line in the Verification Mode section: "Verification MUST include an LLM call to semantically validate each generated record. The verify_sample function must call the LLM to check subjective quality criteria. Do not skip the LLM verification step."
   - Additionally, in the Checks subsection, reinforce the mode:
     - For `deterministic`: prefix the checks with "All checks below are pure Python — no LLM calls permitted."
     - For `llm-augmented`: prefix the semantic checks with "The following checks REQUIRE an LLM call — do not implement these as pure Python heuristics."
   - Semantic checks must be consolidated into a single LLM call per record to avoid latency (only applicable in `llm-augmented` mode)
   - **Verification threshold (Best-of-K):** When multiple LLM checks are needed, default to the Best-of-K pattern to reduce samples discarded due to noisy LLM validations. Instead of requiring all N checks to pass, require only K:
     - N≤2 → K=N (all must pass)
     - N=3–4 → K=N-1
     - N≥5 → K=N-2
     Write the threshold explicitly in the spec, e.g.: "Use a single LLM call to verify the following, and accept the sample if at least 2 checks pass:" followed by the check list. If the customer explicitly requires strict validation (all N must pass), use "accept the sample if ALL checks pass" instead — but do not default to this.

7. **Get approval** - Confirm user is happy with the proposed spec structure

8. **Confirm file location** - Ask where to save the spec (default: `<descriptive_name>_data_spec.md`)

9. **Write spec** - Generate complete spec file that exactly matches the template structure

## Critical Requirements

- **Read the execution environment reference first** - Before starting any conversation, read [execution-environment.md](execution-environment.md). The generated code for your spec can only use a fixed set of Python modules — a spec that requires operations outside those cannot be implemented.
- **Read the format guide and template first** - Before starting any conversation, read [spec-format-guide.md](spec-format-guide.md) and [spec-template.md](spec-template.md). The format guide is the authoritative reference for field syntax, spec sections, and writing conventions.
- **Output schema must match a supported format** - Read [supported-output-formats.md](supported-output-formats.md). The generated data must pass the platform's format detector. Use the format selection guide to pick the right format based on fine-tuning technique and model family. Write the Output Schema section using the exact JSON structure from the supported formats reference.
- **Spec MUST match template exactly** - See [spec-template.md](spec-template.md)
- **Always get approval before writing** - User must confirm the spec structure
- **Explain, don't just list** - Help user understand what each section means and why
- **Keep communication succinct** - Minimize turns while gathering complete information
- **Be flexible** - Adapt questions based on user's responses and context

## Best Practices

### Use the Right Amount of Specificity

Be precise where it matters, flexible where it doesn't. Use concrete numbers and ranges instead of vague qualitative terms.

### Common Auxiliary Fields

**LLM Response Length**

When generating text with LLMs, it can help to control output length by specifying target word counts or token counts. This ensures consistent data structure and helps the model understand expectations.

- Combine descriptive terms with specific counts: "short (25-50 words)", "medium (100-200 words)", "long (300-500 words)"
- Avoid using vague terms alone: "short", "medium", "long" without numbers
- Note: LLMs approximate counts but aren't perfect counters - expect close but not exact adherence

## Field Properties Reference

When defining fields in compact format, each field has a Priority and a Field Type. The available attributes per type:

**All field types:**

- **Priority**: Core | Auxiliary
- **What it represents**: (Optional) Description if field name is not self-explanatory
- **Field Type**: Categorical | LLM-generated | Programmatic
- **Cardinality**: single | array of N | array of X-Y | variable
- **Generated When**: (Optional) Condition for whether this field is generated
- **Examples**: (Optional) Sample values

**Categorical-specific:**

- **Values**: (Required) Complete list of all possible values
- **Sampling Strategy**: (Optional) How to sample values (uniform, weighted, etc.)
- **Subcategory Of**: (Optional) Parent field name for dependent categorical relationships

**LLM-generated-specific:**

- **LLM Generation Instructions**: (Required) Which input fields to use and how, including quality and content constraints

**Programmatic-specific:**

- **Rule Specification**: (Required) How to generate the value, including method and any format/range constraints

For detailed syntax, examples, and guidance on writing fields in compact format, see [spec-format-guide.md](spec-format-guide.md).

## Sample Specifications

Two sample specs are provided for different scenarios. Refer to the one that matches the user's situation:

- [sample-spec-restaurant-reviews.md](sample-spec-restaurant-reviews.md) - **With input data**: use this as a reference when the user has seed examples or context documents. Shows input data preparation, seed-based LLM generation, and grounding in source data. Uses Bedrock_Converse format.
- [sample-spec-review-classification.md](sample-spec-review-classification.md) - **Without input data**: use this as a reference when generating data entirely from scratch with no input files. Uses HF_Prompt_Completion format.

## Conditional Fields Pattern

When user wants variable field combinations across records:

1. Define a **meta-field** (Categorical) that selects which sub-fields to generate
2. Define **sub-fields** with "Generated When" property referencing the meta-field
3. Only sub-fields selected by the meta-field will be generated for each record

See template for detailed example.

## Specification Template

See [spec-template.md](spec-template.md) for the complete specification structure.

<!-- markdownlint-disable-file MD036 -->
