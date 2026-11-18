# Synthetic Dataset Generation Specification Format Guide

## About This Specification Format

This specification uses a **field-driven generation approach** to create synthetic datasets. Records are generated one at a time, with each record governed by specific field values that vary across the dataset.

**How it works:**

- **Quality Standards** define the north star for data quality
- **Generation Constraints** provide specific rules for achieving those standards during generation
- **Data Verification** defines how to verify each record meets the standards after generation
- **Fields** define the structure of each record, grouped by generation step
- **Field Types** specify how each field is populated:
  - Categorical fields are sampled from finite sets
  - LLM-generated fields are created by LLMs conditioned on other fields
  - Programmatic fields are generated using deterministic code (Faker, templates, custom logic)
- Fields can depend on each other, creating realistic relationships and generation chains

**Why three field types?**

The three types map to three fundamentally different generation mechanisms:

- **Categorical** → Sample from a known list → `random.choices(values, weights)`
- **LLM-generated** → Make an LLM API call → Prompt construction + API call + response parsing
- **Programmatic** → Execute deterministic code → Faker calls, templates, computations, field copies

Categorical and Programmatic are both deterministic (no LLM), but they require different code patterns. Categorical fields have structured attributes (values list, sampling strategy, subcategories) while Programmatic fields use libraries, templates, or custom logic. Keeping them distinct gives the code generator unambiguous instructions.

**The spec has two layers:**

- **Context layer:** *Use Case Context* and *Quality Standards*. Describes what you want and what good looks like. Guides the creation of the rest of the spec.
- **Implementation layer:** *Input Data*, *Output Schema*, *Data Generation*, *Generation Constraints*, and *Data Verification*. The operational specification with the details of how to get the data you want. This layer drives code generation.

This guide covers both layers — data field definitions first, then the other spec sections.

---
## Writing Fields in Compact Format

Fields are written as one-liners under their generation step. The format is flexible — the spec-to-code generator understands natural language, so there's no rigid syntax to follow (see [A note on syntax](#a-note-on-syntax) below). The general pattern is:

```
- field_name (Priority): description and specification
```

Where **Priority** is either `Core` (P0, directly serves the use case) or `Auxiliary` (supporting field for realism/variation).

The rest of the line varies by field type. Below are the options and examples for each.
---
## Categorical Fields

Categorical fields sample from a finite set of values. The compact line specifies the values and how to sample them.

**What you can specify:**

- The list of possible values
- A sampling strategy (uniform by default, or weighted)
- Cardinality — single value or array (defaults to single if not stated)
- Subcategory relationship to another categorical field
- A condition for when the field is generated

**Examples:**

Simple uniform:

```
- sentiment (Core): one of [positive, negative, neutral]
```

Weighted distribution:

```
- sentiment (Core): weighted (40% positive, 30% negative, 30% neutral)
```

Weighted with description:

```
- product_category (Core): type of product being reviewed, weighted
    (25% Electronics, 20% Home & Kitchen, 15% Clothing & Accessories,
    10% Toys & Games, 10% Sports & Outdoors, 8% Beauty & Personal Care,
    5% Pet Supplies, 3% Automotive, 2% Books, 2% Health & Wellness)
```

Array with cardinality:

```
- review_aspects (Auxiliary): array of 1-3, select uniformly without
    replacement from [quality, value, shipping, customer service,
    durability, ease of use, design]
```

Subcategory of another field:

```
- product_subcategory (Core): subcategory of product_category —
    Electronics: [Laptops, Headphones, Smartphones],
    Clothing: [Shirts, Pants, Dresses],
    Books: [Fiction, Non-Fiction, Biography]
```

Conditional:

```
- detailed_category (Auxiliary): only when product_type is "Electronics",
    one of [Laptops, Headphones, Smartphones, Tablets]
```

Kitchen sink (all options in one field):

```
- product_subcategory (Core): type of product variant. Array of 1-2,
    subcategory of product_category —
    Electronics: [Laptops, Headphones, Smartphones],
    Clothing: [Shirts, Pants, Dresses].
    Weighted (50% first item, 30% second, 20% third).
    Only when user_type is "detailed".
```

---
## LLM-Generated Fields

LLM-generated fields are produced by an LLM call, sometimes conditioned on other fields. The compact line specifies which fields to use and how to prompt the LLM.

**What you can specify:**

- Which input fields to condition on
- Instructions for the LLM (content requirements, style, constraints)
- Cardinality (defaults to single if not stated)
- A condition for when the field is generated

**Examples:**

Simple:

```
- review_text (Core): Use product_category and sentiment. Write an
    authentic product review expressing the target sentiment.
```

With multiple inputs and detailed instructions:

```
- review_text (Core): Use product_category, sentiment, review_length,
    review_aspects, and customer_experience_level. Reason about how to
    construct an authentic review, then extract the final review from
    the chain-of-thought output.
```

Conditional:

```
- reviewer_bio (Auxiliary): only when complexity_level is "high". Use
    customer_experience_level and product_category. Brief 1-2 sentence
    reviewer persona description to condition review generation for
    more diverse writing styles.
```

Exact prompt:

```
- review_text (Core): Use this exact prompt: "You are a
    {customer_experience_level} customer writing a review for a
    {product_category} product. Write a {review_length} review that
    is {sentiment}. Focus on these aspects: {review_aspects}. Write
    naturally, as if posting on an online store."
```

Kitchen sink (all options in one field):

```
- product_details (Auxiliary): array of 2-3. Use product_category and
    price_tier. Generate specific but fictional product attributes
    (e.g., model name, key feature, material) that the review should
    reference. Only when review_length is "medium" or "long".
```

---
## Programmatic Fields

Programmatic fields are generated by deterministic code — Faker, templates, field copies, or custom logic. The compact line specifies the method and any constraints.

**What you can specify:**

- The generation method (Faker, template, field copy, custom logic)
- Format or range constraints
- Cardinality (defaults to single if not stated)
- A condition for when the field is generated

**Common patterns:**

Faker:

```
- customer_name (Auxiliary): Faker: name
```

Faker with format constraint:

```
- phone_number (Core): Faker: phone_number, format XXX-XXX-XXXX
```

Template (string interpolation from other fields):

```
- full_name (Core): Use template "{first_name} {last_name}"
```

Field copy:

```
- classification_label (Core): Copy value from sentiment
```

Custom logic with range:

```
- age (Auxiliary): random integer, range 18-65
```

Sequential ID:

```
- record_id (Core): sequential IDs starting from 1000, must be unique
    across all records
```

Faker with cross-field constraint:

```
- end_date (Core): Faker: date_between, must be 30-365 days after
    start_date
```

Conditional:

```
- pii_address (Core): only when pii_selection contains "pii_address".
    Faker: address, single-line format (no newlines)
```

---

## Use Case Context

This is the "why" of the dataset. It should answer three questions:

1. What is the business problem or task?
2. Who will use the generated data (or the model trained on it)?
3. How will the data be used?

Keep it to a short paragraph. The goal is to give anyone reading the spec enough context to understand the purpose without needing external docs, and to help drive the creation of the rest of the spec.

**Tips:**

- Be specific about the downstream task (e.g., "train a sentiment classifier" not "ML purposes")
- Mention the domain if it matters (e.g., "US-based online retailer", "legal contracts")
- If the data format matters (e.g., SFT instruction-response pairs), say so here

**Examples:**

Simple:

```
Generate a dataset of product reviews with sentiment labels for
training a classification model. Each sample contains an
instruction-response pair where the instruction asks to classify
a review's sentiment and the response provides the correct label.
```

With more context:

```
Generate a natural language inference (NLI) dataset from legal
contract documents. For each premise (a clause extracted from a
legal contract), generate three hypotheses — one entailed, one
contradicting, one neutral — to create a balanced NLI training set.
```

---

## Quality Standards

High-level criteria for what "good data" looks like. These are the north star — Generation Constraints and Data Verification both flow from these.

Write them as a short bulleted list. Each standard should be a quality dimension with a brief explanation of what it means for this dataset.

**Common quality dimensions:**

- Accuracy / correctness
- Naturalness / authenticity
- Diversity (across categories, styles, lengths, etc.)
- Consistency (labels match content, cross-field agreement)
- Domain relevance

**Tips:**

- These should be high-level goals, not specific rules (those go in Generation Constraints and Data Verification)

**Example:**

```
- Authenticity: Reviews must reflect genuine customer experiences,
    not template-like output
- Sentiment accuracy: Labels must accurately match the expressed
    sentiment in the review
- Diversity: Cover a range of product categories, review lengths,
    and writing styles
- Naturalness: Written in conversational English with realistic
    customer language
```

---

## Input Data

Describe any data provided as input to the generation pipeline. REQUIRED whenever the job is given input data; skip it only when the dataset is generated entirely from scratch. This section is the only place the planner learns the input's schema — it is handed the file's path and nothing else, so an undeclared input gets its key names guessed, and a wrong guess silently drops every record.

Keep it compact: the filename, each record key with a short gloss, and which key the generation targets. A few hundred characters is enough. It does not need an indented JSON block, a category list, or generation strategy — that belongs in the generation sections.

Get the schema by reading the input file when it is reachable; a few records is enough, and the file is authoritative. Do not infer it from an upstream document or a similarly-named artifact, and ask the user only when the file cannot be read.

Input data typically falls into three categories:

- **Seed examples**: Representative input-output pairs that demonstrate expected quality and format. Used as few-shot examples or style references.
- **Context documents**: Files the generator should reference during data creation (e.g., source documents to summarize, raw text to label).
- **Reference material**: Domain knowledge, large value sets, or schemas that the generator should draw from (e.g., a CSV of 500 product names, a company FAQ, a JSON schema for output format).

For each input file or directory, describe:

1. The file format (JSONL, CSV, directory of TXT files, etc.)
2. The schema or structure of each record
3. How it will be used in generation

**Tips:**

- Use code blocks for schemas so the structure is unambiguous
- If you have multiple input sources, list each one separately
- Be explicit about what role each input plays

**Example:**

```
- contract_pairs.jsonl — JSONL file of unlabeled premise-hypothesis
    pairs from legal contracts. Each line:
    {
        "premise": "text excerpt from a legal contract",
        "hypothesis": "example hypothesis (style reference)"
    }

- demo_examples.jsonl — JSONL file of labeled examples for few-shot
    prompting. Each line:
    {
        "premise": "text excerpt from a legal contract",
        "hypothesis": "a hypothesis about the premise",
        "label": "entailment | contradiction | neutral"
    }
```

---

## Input Data Preparation

Describe preprocessing steps applied to input data before generation begins. This section is optional — skip it if no preprocessing is needed.

This is where you specify things like:

- Parsing and loading input files
- Filtering out bad or incomplete records
- Deduplication
- Splitting, joining, or converting fields
- Sampling a subset

**Tips:**

- Write steps as a numbered or bulleted list
- Write instructions clearly enough that a person could unambiguously follow them, in tandem with the format specification — there's no prescribed syntax
- Focus on what you're doing to the data to make it ready, not how it will be used (that goes in the field definitions)

**Example:**

```
- Parse contract_pairs.jsonl and drop any records where premise
    is empty or under 10 words
- Deduplicate premises (some contracts repeat clauses)
- From demo_examples.jsonl, filter to only examples where label
    confidence > 0.9
```

---

## Generation Constraints

This section is optional. It's a place for cross-cutting rules that apply across all generated samples, rather than to a specific field. Most constraints can and should go directly in the field definitions — use this section for guidance that doesn't naturally belong to any single field.

**Tips:**

- If a constraint only applies to one field, put it in that field's definition instead
- Be concrete and actionable

**Examples of things that fit here:**

- "Avoid overly generic or template-like language" (applies to all LLM fields)
- "No two samples should have the same combination of product_category and sentiment" (cross-record constraint)
- "All generated names should be culturally diverse" (applies to multiple fields)

---

## Data Verification

Verification procedures applied to each generated record. This is the "did we actually achieve the Quality Standards?" check.

There are two types of checks: Structural (programmatic) and Semantic (LLM-based)

### Structural checks
Deterministic validations — format, field presence, value ranges, cross-field consistency. These are relatively fast and cheap.

**Common structural checks:**

- Required fields are present and non-empty
- Values are within allowed sets or ranges
- Array fields have the right number of elements
- Cross-field consistency (e.g., label matches a categorical field)
- Text length within specified bounds

### Semantic checks (LLM-based)
Use an LLM to validate content quality — things that can't be checked deterministically. These are slower and more expensive, so use them for the checks that matter most.

**Common semantic checks:**

- Classify content and compare to the intended label
- Check that generated text is grounded in provided context
- Verify that content meets quality criteria (naturalness, relevance)

**Note:** By default, all semantic checks are covered in a single LLM call. But you can specify to use multiple LLM calls if you'd prefer.

**Tips:**

- Structural checks are typically cheaper and faster -- Use these when you can
- Use semantic checks sparingly for the validations that really matter
- For semantic checks, consider requesting structured output (e.g., XML format) for reliable parsing
- For semantic checks, think carefully about how many distinct LLM calls to make
- A good heuristic: think about what would make you reject a sample if you were reviewing it by hand

**Full example (single LLM call):**

```
1. Structural checks:
    - review_aspects: 1-3 unique values from the allowed list,
        no duplicates
    - response: one of [positive, negative, neutral], exactly
        matches sentiment (case-sensitive)
    - review_text word count: within review_length spec
        (short: 20-50, medium: 50-100, long: 100-200) ±10% tolerance

2. Semantic checks (LLM-based):
    - Classify the sentiment expressed in review_text
    - Request prediction in XML format for reliable parsing
    - Reject sample if predicted sentiment does not match the
        sentiment field
```

**Full example (multiple LLM calls):**

```
1. Structural checks:
    - review_aspects: 1-3 unique values from the allowed list,
        no duplicates
    - response: one of [positive, negative, neutral], exactly
        matches sentiment (case-sensitive)

2. Semantic checks (LLM-based):
    - LLM Call 1:
        - Classify the sentiment expressed in review_text
        - Reject if predicted sentiment does not match the
            sentiment field
    - LLM Call 2:
        - Validate that the tone matches the restaurant_type
            (e.g., casual language for fast casual, refined
            language for fine dining)
        - Check for any toxic or offensive content
        - Reject sample if either check fails
```

---
## A note on syntax

There is no rigid syntax to follow. The spec-to-code generator understands natural language, so the examples given are just one way to express each concept. For instance, these all mean the same thing:

```
- sentiment (Core): weighted (40% positive, 30% negative, 30% neutral)
- sentiment (Core): sample from positive, negative, or neutral with
    weights 40/30/30
- sentiment (Core): the review's overall sentiment — positive (40%),
    negative (30%), or neutral (30%)
```

What matters is that the information is there (what the values are, how to sample them), not the exact phrasing.
