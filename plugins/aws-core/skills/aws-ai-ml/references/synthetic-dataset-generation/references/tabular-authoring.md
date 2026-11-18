# Tabular Spec Preparation

Detects whether the user's request is a tabular data generation task and, when it is, hardens the spec with per-format directives (CSV / Parquet / SQLite), gates on explicit user approval, and uploads the hardened spec.

**When to use this reference:** The parent `overview.md` routes here from Step 1b. Load this file and follow it from the start on every entry — it owns tabular detection, spec hardening, the hard-gate approval, and the hardened-spec upload. When it finishes (or when it determines the request is NOT tabular), control returns to `overview.md` at Step 1c.

This reference is MANDATORY once the parent has routed here.

This step handles two paths:

- **From scratch** — user described their schema in the prompt (no spec file exists). Author the full spec with tabular directives built-in.
- **BYO spec** — user provided or uploaded a spec file. Harden it by adding missing tabular directives.

If early tabular detection fired in `overview.md` Step 1 (user's prompt contained tabular signals), proceed directly to Sub-step A below — no need to re-analyze.

If early detection did NOT fire, read the spec file and analyze whether this is a tabular use case. This step is mandatory — never skip the analysis.

**Anti-tabular signals — if ANY of these are present, do NOT trigger tabular detection regardless of other signals:**

- User explicitly requests one of the 9 supported LLM output formats (see `supported-output-formats.md`)
- Spec's `generator` section produces natural language text (conversations, Q&A pairs, summaries, instructions, preference pairs)
- Spec's `verify_sample` checks NLP quality metrics (coherence, relevance, fluency, faithfulness, groundedness)
- User's goal mentions "fine-tuning", "instruction tuning", "RLHF", "DPO", or "preference data"
- Input `.csv` is used as **reference context** (FAQ lookups, metadata) rather than as a schema to replicate

If any anti-tabular signal is present → skip this reference, return to `overview.md` Step 1c.

**Tabular signals** (any 2+ of these, AND no anti-tabular signals → likely tabular):

- Spec mentions column names, schemas, or field-level definitions
- `generator` section describes outputting rows, records, or comma/tab-separated values
- `verify_sample` checks field counts, data types, or column presence (not NLP quality like coherence/relevance)
- Input data is `.csv` AND the spec references its columns/schema (CDG tabular)
- Input data is `.sqlite` or `.db` (database seed — always tabular)
- No input data but spec defines a column schema inline with value constraints (NCDG tabular)
- Language like "augment", "synthetic rows", "match distribution", "preserve relationships", "database", "transaction records"

**IMPORTANT:** S3 path alone (e.g., `/tabular/` in the URI) is NOT a valid signal. Detection must be based on spec content or the user's stated goal — never on file path heuristics.

**If tabular signals detected:**

Surface to the user:

> "Based on your spec, this appears to be a **tabular data generation** task (generating structured rows matching a schema) rather than an LLM training data task. The output will be in `Custom` format — each sample will be a structured row, not one of the 9 LLM training formats (Bedrock_Converse, OpenAI_Messages, etc.).
>
> Would you like me to proceed with tabular generation?"

⏸ Wait for user to confirm or deny.

**If user confirms tabular — YOU MUST COMPLETE ALL 3 SUB-STEPS BEFORE RETURNING TO `overview.md` STEP 1C:**

**Sub-step A: Write or harden the spec.**

   **Path 1 (From scratch):** If no spec file exists (user described schema in prompt), author the complete spec from their description. Structure it with `## Overall Goal`, `## prepare_batch`, `## generator`, `## verify_sample` sections. Incorporate all tabular directives below from the start — no separate "hardening" pass needed.

   **Path 2 (BYO spec):** If the user provided a spec file, take it and add the tabular directives below. Write the complete hardened spec as a markdown code block.

   **Ask the user their preferred output format** (if not already stated):

- **CSV** (default) — streaming, append-friendly, universal compatibility
- **Parquet** — columnar, compressed, best for ML pipelines and analytics
- **SQLite** — relational database file, best for app prototyping and multi-table with FKs

   Record their choice. This affects both the spec directives and the notebook config.

   **In both paths, the spec MUST include format-specific directives. Append the shared directives below, PLUS the per-format directives for the user's chosen format (CSV / Parquet / SQLite), PLUS the matching `## Tabular Output Constraints` code block verbatim.**

   **── Shared directives (ALL formats) ──**

   **In `generator`** — append:

- "All dates as YYYY-MM-DD. All timestamps as YYYY-MM-DDTHH:MM:SS. No other date formats."

   **In `verify_sample`** — append:

- Type checks derivable from the spec (e.g., "Confirm field 3 is a positive integer.").

   **── Per-format directives — append the group for the user's chosen format ──**

   **CSV (default)**

   `generator`:

- "Output one CSV row with N comma-separated values matching the column order: [column list]." (replace N and column list with actual values)
- "The column order is fixed and must be identical for every sample."
- "For missing or NULL values, output an empty field (two consecutive commas). Do NOT output the string 'NULL' or 'None'."
- "If any field value contains a comma, double-quote, or newline, wrap the entire field in double quotes."
- "If a quoted field contains a double-quote, escape it by doubling it (write `\"\"` for each literal `\"`)."
- "Round all decimal values to 2 decimal places unless the spec explicitly requires more precision."

   `verify_sample`:

- "Confirm the output has exactly N non-empty or intentionally-empty comma-separated fields."
- "Validate date fields match the pattern YYYY-MM-DD using re.match(r'^\d{4}-\d{2}-\d{2}$', value). Do NOT use datetime.strptime()."
- "Validate timestamp fields match YYYY-MM-DDTHH:MM:SS using re.match(). Do NOT use datetime.strptime()."

   **Parquet**

   `generator`:

- "Output a JSON object with exactly these keys in this order: [column list]. This will be converted to a Parquet row."
- "Every sample must have the same keys. Missing values: use `null` (JSON null, not the string)."
- "Numeric fields must be actual numbers (int/float), not strings."

   `verify_sample`:

- Type checks matching the schema (int fields are int, float fields are float, no stringified numbers).

   **SQLite**

   `generator`:

- "Output a JSON object with exactly these keys: [column list]. This will be inserted into a SQLite table."
- "Every sample must have the same keys. Missing values: use `null`."
- "Foreign key values MUST reference existing primary key values from the referenced table."

   `verify_sample`:

- FK reference checks (if multi-table), type checks, uniqueness checks for PKs.

   **── `## Tabular Output Constraints` code block — append the one matching the chosen format verbatim ──**

   CSV:

   ```
   ## Tabular Output Constraints
   - Output format: CSV
   - One record per sample. Do not output multiple rows in a single sample.
   - Column order is fixed per the schema defined above. Every sample must match.
   - NULL/missing values: empty field (consecutive commas in CSV).
   - Text escaping: double-quote fields containing commas, quotes, or newlines; escape embedded quotes by doubling (RFC 4180).
   - Dates: YYYY-MM-DD. Timestamps: YYYY-MM-DDTHH:MM:SS.
   - Decimals: round to 2 places unless spec says otherwise.
   - IDs: if generating sequential IDs, start from a value that avoids collisions with existing data.
   ```

   Parquet:

   ```
   ## Tabular Output Constraints
   - Output format: Parquet (converted from streaming CSV)
   - One JSON object per sample. Keys must match the schema exactly.
   - Missing values: JSON null.
   - Dates: YYYY-MM-DD. Timestamps: YYYY-MM-DDTHH:MM:SS.
   - Numeric fields: actual numbers, not quoted strings.
   - Decimals: round to 2 places unless spec says otherwise.
   ```

   SQLite:

   ```
   ## Tabular Output Constraints
   - Output format: SQLite (converted from streaming CSV)
   - One JSON object per sample. Keys must match the schema exactly.
   - Primary keys: must be unique across all generated samples.
   - Foreign keys: must reference valid primary key values from the referenced table.
   - Missing values: JSON null.
   - Dates: YYYY-MM-DD. Timestamps: YYYY-MM-DDTHH:MM:SS.
   - Numeric fields: actual numbers, not quoted strings.
   ```

   **── Multi-table (any format) ──**

   If the user's spec defines multiple related tables, generate them in **ONE spec and ONE job** — this is the default and the platform supports it. Do NOT author a separate spec per table and do NOT launch a job per table. The platform maintains foreign-key integrity across tables within a single job and writes one output file per table (e.g. `customers.csv`, `orders.csv`, or all tables in one `output_samples.sqlite`).

   Write a single spec that describes **all** tables and their FK relationships together, and configure the generator to output each sample as a `[table_name, {field: value, ...}]` JSON tuple (or a list of such tuples for a parent + its children group). The spec MUST state:

- "Each sample is a JSON array: [table_name_string, row_object] (or a list of these tuples to emit a parent row and its child rows together)."
- "Generate parent rows before child rows. Every FK must reference a previously generated PK (from this sample or an earlier one)."

   See the "Multi-Relational" example in [sample-spec-tabular-augmentation.md](sample-spec-tabular-augmentation.md) for the exact single-spec, single-job structure.

   **Exception — one job per table.** Only split into a separate spec and job per table if the user **explicitly asks** for that, or if a single multi-table job has already failed and per-table generation is being used as a fallback. In that case generate the parent table first, then child tables, and include the parent table's schema in each child spec for FK awareness. Never make this the default.

   **── Seed data from SQL/database context ──**

   If the user provides a `.sqlite` or `.db` file as input context (via InputDataS3Uri), the service extracts each table as a CSV and hands those to the generator. Add to `prepare_batch`:

- "Load each extracted CSV with `pandas.read_csv`."
- "Introspect schema per table: columns, types, FK relationships (from CSV headers and content)."
- "Sample distribution characteristics: min/max for numerics, distinct counts for categoricals, null rates."
- "Generated data must match the schema and distributions of the seed tables."

**Sub-step B is a HARD GATE.** You MUST stop and show the hardened spec to the user. You MUST NOT create a notebook, write any code, or return to `overview.md` Step 1c until the user has replied with explicit approval. If you skip this step, the output is invalid. This is not optional regardless of conversation length or complexity.

COMPLIANCE CHECK: Your message MUST contain BOTH of these: (1) the full hardened spec in a markdown code block, AND (2) an approval question asking the user to review before you proceed. If your response does not contain the spec text AND an approval question, you have violated this gate.

For example:

> "I've hardened your spec with explicit tabular output directives for [FORMAT] format. Please review before I proceed:"
>
> ```markdown
> [THE COMPLETE HARDENED SPEC TEXT HERE]
> ```
>
> "Does this look good? I'll upload this to S3 and use it for generation."

⏸ Wait for user to approve the hardened spec. Do NOT return to `overview.md` Step 1c until the user explicitly approves.

**Sub-step C: Upload the hardened spec.** Save the hardened spec to a local file and upload to S3. Ask the user whether to overwrite the original spec file (irreversible unless bucket versioning is on) or upload as a new file. Update `SPEC_S3_URI` to point to the hardened version.

Only after all 3 sub-steps complete → return to `overview.md` Step 1c.

**If user says "no, this is for LLM training":**

Warn them: "Note that if the output doesn't match one of the 9 supported LLM formats, it will be classified as `Custom`. This is fine for hub storage but won't be directly usable with format-specific fine-tuning pipelines without a transformation step." Then return to `overview.md` Step 1c.

**If no tabular signals detected:** Skip this reference, return to `overview.md` Step 1c.

## Return to overview

- Tabular path complete (Sub-steps A, B, C done, `SPEC_S3_URI` updated) → return to `overview.md` at **Step 1c: Delivery Mode**.
- User declined tabular, or no tabular signals detected → return to `overview.md` at **Step 1c: Delivery Mode** without changes to `SPEC_S3_URI`.
