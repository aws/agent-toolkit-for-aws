# Dataset Quality Evaluation Spec Examples

Example requirements documents for spec-driven evaluation. Use these as references when helping a user write a dataset quality spec.

These are written as **open-ended prose** — the simpler form most users will produce naturally, and what the dataset quality evaluation service handles well via LLM-based criteria extraction. A spec does not need special syntax: describe what a good record looks like in plain language.

For users who want stable, reproducible evaluations (e.g. repeating the same evaluation across dataset versions), the structured `## Criteria` format pins each requirement to an explicit `id` and `type`. See [Spec Format](#spec-format) at the bottom for the difference.

## Expected Routing

Each spec's criteria will be classified by the service as `code` (deterministic, 0 LLM calls per row) or `llm` (semantic, one model call per row). The routing determines cost and reproducibility.

Routing is independent of what a criterion *produces*. A criterion is either a **check** (pass/fail per row, or one verdict for the dataset) or a **metric** (a measured value, no threshold). Either kind can route to `code` or `llm`. Examples 1–16 are checks; example 17 shows metrics.

**Answer-correctness specs (examples 1–8):**

| Spec | What it evaluates | Expected route | Notes |
|---|---|---|---|
| Answer correctness (multiple choice) | Option letter match | **code** | Mechanical extraction + equality |
| Answer correctness (math) | Final number match | **code** | Numeric normalization + equality |
| Answer correctness (extractive QA) | Span acceptability | **llm** | "same meaning" is fuzzy, not mechanical |
| Yes/no answer correctness | Boolean match | **code** | Boolean normalization + equality |
| Mathematical equivalence | Symbolic equivalence | **llm** | `1/2 ≡ 0.5` is not string equality |
| Instruction following | Format compliance + semantic relevance | **code** + **llm** | Mechanical constraints vs. semantic judgment |
| Dataset quality gate | Per-row correctness + batch pass-rate | **code** + **code** | Row-level verdict + aggregate threshold |
| Customer support Q&A quality | Completeness + relevance + no placeholders | **code** + **llm** | Mix of structural and semantic checks |

**Dataset quality keep/drop specs (examples 9–16):**

| Spec | What it evaluates | Expected route | Notes |
|---|---|---|---|
| Tool-call validity | Function name + param + type validity | **code** | Mechanical schema check |
| Instruction-following compliance | Format constraint obedience | **code** | Counts, keywords, casing — all checkable |
| Safety filtering | Non-empty + safe content | **code** + **llm** | Sanity gate is code; safety judgment is llm |
| Helpfulness filtering | Non-empty + genuinely helpful | **code** + **llm** | Sanity gate is code; helpfulness judgment is llm |
| PII detection | Personal data presence | **code** | Pattern/format detection; or offer the built-in `pii_detection` metric and let the user choose (`spec-authoring.md`) |
| Language match | Response in target language | **code** | Language identification check |
| Coherence check | Fluent, non-degenerate text | **llm** | Readability judgment, not a pattern |
| Composite curation gate | Non-empty + no PII + safe + helpful | **code** + **llm** | All four criteria in one spec, routes split internally |

---

## Example Specs

The examples are on three family pages, one per question they answer:

- `spec-examples/answer-correctness.md`: examples 1 to 8, "is this answer right?" (prose).
- `spec-examples/keep-drop.md`: the Keep/Drop family text and examples 9 to 16, "is this training sample worth keeping?" (prose).
- `spec-examples/measurements-and-inventory.md`: examples 17 to 20, values rather than verdicts (17 in prose; 18 to 20 structured).

Open only the family page the use case needs. The index below names the page and the example for each use case.

| Use case | Example | Page |
|---|---|---|
| Multiple-choice benchmark, the correct option letter is given | 1 | `spec-examples/answer-correctness.md` |
| Math problems with a final numeric answer | 2 | `spec-examples/answer-correctness.md` |
| Extractive QA, an acceptable span rather than one exact string | 3 | `spec-examples/answer-correctness.md` |
| Yes/no questions | 4 | `spec-examples/answer-correctness.md` |
| Symbolic math, equivalent forms count as correct | 5 | `spec-examples/answer-correctness.md` |
| Instruction following with a mix of code and judged checks | 6 | `spec-examples/answer-correctness.md` |
| A quality gate with an aggregate pass-rate threshold | 7 | `spec-examples/answer-correctness.md` |
| Customer-support Q&A quality | 8 | `spec-examples/answer-correctness.md` |
| Tool-call validity (BFCL-style) | 9 | `spec-examples/keep-drop.md` |
| Instruction-following compliance (IFEval-style) | 10 | `spec-examples/keep-drop.md` |
| Safety filtering (BeaverTails-style) | 11 | `spec-examples/keep-drop.md` |
| Helpfulness filtering (HelpSteer2-style) | 12 | `spec-examples/keep-drop.md` |
| PII detection in a spec, next to the built-in `pii_detection` | 13 | `spec-examples/keep-drop.md` |
| Language match | 14 | `spec-examples/keep-drop.md` |
| Coherence check | 15 | `spec-examples/keep-drop.md` |
| A composite curation gate (mixed route) | 16 | `spec-examples/keep-drop.md` |
| Measurements reported alongside checks (metric criteria) | 17 | `spec-examples/measurements-and-inventory.md` |
| Characterize a benchmark (annotation-style, structured) | 18 | `spec-examples/measurements-and-inventory.md` |
| Inventory a dataset with no per-row model calls | 19 | `spec-examples/measurements-and-inventory.md` |
| The documents as the authority, and a judge text of your own | 20 | `spec-examples/measurements-and-inventory.md` |

## Spec Format

Two forms are supported and auto-detected by the service.

### Open-ended prose (simpler, recommended for first-time use)

Any document without a `## Criteria` section. The service extracts criteria using an LLM. Examples 1 to 8 (`spec-examples/answer-correctness.md`) all use this form.

Use this when:

- The user is writing a spec for the first time
- The requirements may evolve and the user wants flexibility
- The spec is descriptive and may contain context alongside the rules

### Structured `## Criteria` format (for repeatable runs)

The structured format (its fields, the continuation rules, the one job-level switch, the parse errors and warnings) and the Criterion grammar are `structured-spec.md`; read it only when a spec takes this form. Worked structured examples are 18 to 20 on `spec-examples/measurements-and-inventory.md`.
