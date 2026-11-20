# Spec Examples: Answer Correctness (examples 1 to 8)

Examples 1 to 8 of the dataset quality spec examples: the family that asks "is this answer right?". The routing tables, the use-case index and the spec-format notes are `spec-examples.md`; the Keep/Drop family is `spec-examples/keep-drop.md` and the measurement and inventory family is `spec-examples/measurements-and-inventory.md`. The structured `## Criteria` grammar is `structured-spec.md`. Every example here is written as open-ended prose.

### 1. Multiple-Choice Answer Correctness

**Use case:** Evaluating a model on a multiple-choice benchmark. Each row has the question with options, the model's response, and the correct option letter.

```markdown
# Multiple-Choice Answer-Correctness Judge

I'm evaluating a model on a multiple-choice benchmark. Each row has the question
with its options inlined, the model's response, and the gold option letter. The
model ends its reply with `Answer: X` giving the single chosen letter.

I want to know, per row, whether the model picked the correct option. Read the
chosen letter from the response's final `Answer:` line and compare it to the
reference letter, ignoring case. It's correct only when the two letters match;
if the letters differ, or the response has no answer line at all, it's wrong.
```

**Why this routes to `code`:** The criterion is mechanical — extract a letter, compare to reference. No LLM judgment needed, so it makes 0 LLM calls per row at judge time.

**Tip for leniency:** If the model sometimes writes `(B)` or `B)` instead of `B`, add: "Be lenient about surface form: casing doesn't matter, and surrounding punctuation or parentheses should be ignored."

---

### 2. Math Final-Answer Correctness

**Use case:** Grading a model on math word problems. The model shows its reasoning and ends with a final number.

```markdown
# Math Final-Answer Judge

I'm grading a model on math word problems. Each row has the question, the
model's worked response, and the gold final number. The model shows its
reasoning and ends with a line `Answer: N`.

I only care about the final numeric answer, not the reasoning steps. Tell me,
per row, whether the model's final number is correct. Read the number from the
response's final `Answer:` line, ignoring thousands separators, currency symbols,
and any trailing units, then compare it to the reference by value rather than as
a string — so "1,200", "$1200", and "1200.0" all count as the same number. It's
correct only when the two numbers are equal; it's wrong if they differ or if no
final number can be parsed from the response.
```

**Why this routes to `code`:** Numeric normalization + equality is deterministic. No ambiguity in what "correct" means.

---

### 3. Extractive QA Answer Acceptability

**Use case:** Evaluating a reading comprehension model. The model extracts a span from a passage; the gold answer is a reference span.

```markdown
# Extractive QA Answer Judge

I'm evaluating a reading comprehension model. Each row has a question, the
model's response (which ends with `Answer: <span>`), and the gold answer text.
Some questions are deliberately unanswerable from the passage; for those the
gold answer is empty and the model is expected to say it cannot answer.

I want a per-row judgment of whether the model's answer is acceptable. When
there is a gold answer, the response's span should convey the same answer — I'll
allow minor differences in wording, articles, casing, or punctuation, so I don't
need a character-for-character match, just the same meaning. When the question
is unanswerable (the gold answer is empty), the response is only acceptable if
it declines or says the passage doesn't contain the answer; fabricating a span
is wrong. Mark it correct when the answer is acceptable and wrong otherwise.
```

**Why this routes to `llm`:** "Same meaning" with tolerance for paraphrasing is genuinely semantic — a model call is needed to judge this. The service routes this to an `llm` criterion.

---

### 4. Yes/No Answer Correctness

**Use case:** Evaluating a yes/no reading comprehension task. Each row has a question, the model's response, and a gold "yes" or "no".

```markdown
# Yes/No Answer Judge

I'm evaluating a model on a yes/no reading comprehension task. Each row has a
question, the model's response ending with `Answer: X`, and the gold answer —
either "yes" or "no".

I want a per-row true/false of whether the model gave the correct yes/no answer.
Read the yes/no value from the response's final `Answer:` line, treating the
usual variants as equivalent — "Yes", "true", and "correct" all mean yes; "No"
and "false" mean no — and compare it to the reference. It's correct only when
the normalized answer matches the reference; it's wrong if it differs or if no
yes/no answer can be read.
```

**Why this routes to `code`:** Boolean normalization + equality is deterministic.

---

### 5. Mathematical Equivalence (Symbolic)

**Use case:** Grading competition math problems where answers can be expressed in multiple equivalent forms (`1/2`, `0.5`, `\frac{1}{2}`).

```markdown
# Mathematical Equivalence Judge

I'm grading a model on competition math problems. Each row has the question,
the model's worked response ending with `Answer: <expr>`, and the gold answer.
Unlike simple arithmetic, answers here are often fractions, radicals, or
symbolic expressions — things like `1/2`, `0.5`, `\frac{1}{2}`, or `2\sqrt{3}`.

I want to know, per row, whether the model's final answer is mathematically
equivalent to the gold answer — not merely string-identical. Compare the
expression on the response's final `Answer:` line to the reference by value and
meaning, treating equivalent forms as equal: `1/2`, `0.5`, and `\frac{1}{2}`
are the same, and `2\sqrt{3}` equals `\sqrt{12}`. A different-looking but equal
expression is still correct; it's wrong only when the value genuinely differs.
```

**Why this routes to `llm`:** Symbolic equivalence can't be reduced to string comparison. This is a deliberate contrast with Example 2 (math final-answer): same domain, different routing because the *intent* differs.

---

### 6. Instruction Following (Mixed Route)

**Use case:** Evaluating whether a model follows explicit instructions. Each row has the instruction and the model's response. The instruction may contain both checkable format constraints and a semantic request.

```markdown
# Instruction-Following Judge

I'm evaluating whether a model follows explicit instructions. Each row has the
instruction the model was given and the model's response. The instruction
includes verifiable constraints — for example "reply in exactly three bullet
points", "do not use the letter e", or "end with the word DONE".

I care about two separate things. First, did the response obey every explicit,
checkable format constraint stated in the instruction — counts, required or
forbidden tokens, a required ending, casing, and the like? I read the
constraints straight from the instruction and check them against the response;
it passes only if all of them hold, and fails if any is violated. Second,
setting formatting aside, did the response actually fulfil the substance of what
was asked — the right task, on the right topic? That passes if it genuinely
responds to the request and fails if it ignores, misreads, or answers something
else.
```

**Why this has two routes:** The first criterion (format constraints) routes to `code` — mechanical counting and token checking. The second (semantic relevance) routes to `llm`. One spec, two derived criteria, two routes.

---

### 7. Dataset Quality Gate (With Aggregate Threshold)

**Use case:** Screening a batch of model responses before accepting the dataset. You want both per-row verdicts and a single dataset-level accept/reject decision based on a pass rate threshold.

```markdown
# Dataset Quality Gate

I'm screening a batch of model responses before accepting the dataset. Each row
has the model's response, ending with `Answer: X`, and a gold reference. I want
two things out of this: a per-row correctness verdict, and a single
dataset-level decision on whether the batch is good enough to accept.

Per row, the response is correct when the answer on its final `Answer:` line
matches the reference after trimming surrounding whitespace and normalizing case.
Then, across the whole batch, I want a single accept/reject: the batch is
acceptable when at least 80% of rows are correct, and should be rejected
otherwise. So the dataset-level decision reduces over the per-row verdicts — it's
the batch's pass rate checked against that 80% threshold.
```

**Why this has two criteria:** The per-row check routes to `code`. The aggregate threshold is a dataset-level criterion that reduces over the row verdicts — it also routes to `code` since it's a deterministic threshold over a computed rate.

**Note for the agent:** This pattern uses `scope: aggregate` in the structured format. When helping a user write this as a structured spec, the aggregate criterion needs `inputs:` pointing to the row criterion's id and a `threshold:` object (e.g. `{"min_rate": 0.80}`).

---

### 8. Customer Support Q&A Quality

**Use case:** Evaluating training data for a support assistant. Each record has a prompt (user question) and a completion (assistant answer). This is the most common dataset quality evaluation use case pattern for fine-tuning datasets.

```markdown
# Customer Support Q&A Dataset

Training data for a support assistant that answers account, billing, and product
questions.

## Data Verification
Each record should meet the following quality bar:
- The prompt must be present and non-empty.
- The completion must be present and at least twenty words.
- The completion must actually answer the question that was asked.
- The completion must not contain placeholder text such as "TODO" or "TBD".
```

**Why this has mixed routes:** The first two criteria (presence and length) route to `code`. The third (relevance) routes to `llm`. The fourth (no placeholder text) routes to `code`.

**This is the most common starting point for BYOD dataset evaluation.** When a user wants to evaluate a fine-tuning dataset against their quality bar, this pattern — structural checks plus a semantic relevance check — covers the vast majority of use cases.

---

<!-- markdownlint-disable-file MD001 -->
