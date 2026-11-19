# Synthetic Data Specification Template

## Use Case Context
[Describe the business problem, the target audience or end users, and how the generated data will be used.]
## Quality Standards
[High-level criteria for what good data looks like for this use case. Defines the general direction and goals for data quality. For example, accuracy, naturalness, diversity, domain relevance, consistency, etc.]
## Input Data
[Required whenever the job is given input data; omit this section entirely when generating from scratch. Describe the input data provided for generation. This may include seed examples (representative input-output pairs that demonstrate expected quality and format) and/or context documents (files the generator should reference during data creation). Name each file and give the schema of its records — that is the only channel by which the generator learns what is in the file.]
## Input Data Preparation (optional)
[Preprocessing steps applied to input data when it is provided.]
## Output Schema
[The output format for each generated record. Must match one of the 9 supported formats so the generated data passes the platform's format detector. See `supported-output-formats.md` for the full list, selection guide, and exact schemas. State the format name and show the JSON structure with field placeholders.]

```
{
  ...
}
```

## Data Generation
### Data Fields
[Field definitions using compact procedural format, grouped by generation step.]

1. **Sample categorical attributes** with specified distributions:
    - field_name (Priority): description, distribution
    - ...
2. **LLM-generated fields**:
    - field_name (Priority): description and generation instructions
    - ...
3. **Compute programmatic fields**:
    - field_name (Priority): description. Faker/template/custom logic.
    - ...

### Generation Constraints (optional)
[Specific rules and guidelines for achieving the quality standards during data generation.]
### Additional Notes (optional)
[Edge cases, special considerations, implementation hints]
## Data Verification

### Verification Mode
[Choose one: `deterministic` or `llm-augmented` (default: `llm-augmented`)]

> Note: The default above applies to standalone authoring only.

- **deterministic**: Verification uses only pure Python checks (format, field presence, value ranges, regex, word counts). Faster generation, no LLM cost during verification. Use when quality can be fully validated with structural rules.
  - When chosen, include: "Do not use LLM to verify samples. All verification must be pure Python only. Do not make any LLM calls in the verification function."
- **llm-augmented**: Verification includes an LLM call per record for semantic quality checks (e.g., "does the sentiment label match the text?"). More thorough but slower and more expensive — can cause generation failures if checks are too strict.
  - When chosen, include: "Verification MUST include an LLM call to semantically validate each generated record. The verify_sample function must call the LLM to check subjective quality criteria. Do not skip the LLM verification step."

### Checks

1. **Structural checks**:
    [Format, field presence, value ranges — always included regardless of mode.]

2. **Semantic checks (LLM-based)** (only if verification mode is `llm-augmented`):
    [Consolidated into a single LLM call per record. Use Best-of-K threshold by default — e.g. "Use a single LLM call to verify the following, and accept the sample if at least K checks pass: check1, check2, ..." where K is determined by the number of checks (N≤2: all must pass, N=3–4: K=N-1, N≥5: K=N-2). Only use "accept the sample if ALL checks pass" if the customer explicitly requires strict validation.]
