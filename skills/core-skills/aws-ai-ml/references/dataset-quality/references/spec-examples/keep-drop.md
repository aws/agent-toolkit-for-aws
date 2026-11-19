# Spec Examples: Keep/Drop (examples 9 to 16)

Examples 9 to 16 of the dataset quality spec examples: the family that asks "is this training sample worth keeping?". The routing tables, the use-case index and the spec-format notes are `spec-examples.md`; the answer-correctness family is `spec-examples/answer-correctness.md` and the measurement and inventory family is `spec-examples/measurements-and-inventory.md`. The structured `## Criteria` grammar is `structured-spec.md`.

## Dataset Quality Keep/Drop Specs

These specs answer a different question from the answer-correctness family: not "is this answer right?" but "is this training sample worth keeping?" They are written in a first-person curation voice ("I'm filtering…", "I want a keep/drop verdict…") and always end with an explicit keep/drop decision rule. Each spec names the row shape and calls out whether a criterion is mechanical (routes to `code`) or a judgment call (routes to `llm`).

These are the most directly useful spec patterns for evaluating training datasets.

A third family, **measurement specs** (example 17), asks for values rather than verdicts — use it when the user wants a quantity reported per record that no built-in metric covers, or wants it in the spec alongside their checks.

### 9. Tool-Call Validity (BFCL-style)

**Use case:** Screening function-calling training data. Each row has the user's request, the available function schemas, and the model's response (a JSON function call).

```markdown
# BFCL Tool-Call Validity Judge

I'm screening function-calling training data. Each row has the user's request,
the list of function schemas that were available (each with a name and typed
parameters), and the model's response, which is supposed to be a single JSON
function call.

I want a per-row keep/drop verdict on whether the call is well formed. First, the
response has to actually contain something — a blank or whitespace-only response
is dropped outright. Then, treating the call as a call to one of the provided
functions: the function name has to be one that was actually offered, every
required parameter has to be supplied, no made-up parameters that weren't declared
may be passed, and each argument's value has to match the type the schema declares
for it. Keep the row only when the call satisfies all of that; drop it when the
function name isn't in the provided list, a required argument is missing, an
undeclared argument appears, or a value is the wrong type. I'm judging structural
validity against the schema, not whether calling that function was the smartest
choice.
```

**Why this routes to `code`:** Schema/type validity is fully mechanical — extract the function name, check it against the list, verify required params, check types. Zero LLM judgment needed.

---

### 10. Instruction-Following Compliance (IFEval-style)

**Use case:** Keeping only training rows where the model obeyed explicit format constraints (word counts, casing, required keywords, bullet counts, ending phrases).

```markdown
# IFEval Instruction-Following Judge

I'm keeping only the training rows where the model actually obeyed the format
instructions it was given. Each row has the user's instruction and the model's
response. The instruction carries machine-checkable constraints — things like a
required word or sentence count, letter casing, mandatory or forbidden keywords, a
specific number of bullet points, a required ending phrase, or punctuation rules.

Per row, I want a keep/drop verdict on compliance. First, the response must be
non-empty — drop an empty or whitespace-only one. Then, read every explicit,
checkable constraint out of the instruction and verify the response against each:
the response keeps its place only if it satisfies all of them, and is dropped if
any single constraint is violated. These are objective checks — the count is
either right or wrong, the required phrase is either present or absent — so I'm not
asking whether the answer is good, only whether it followed the stated rules
exactly.
```

**Why this routes to `code`:** Format constraints are mechanical — counts, keyword presence/absence, casing. The spec explicitly tells the service not to judge quality, only compliance.

---

### 11. Safety Filtering (BeaverTails-style)

**Use case:** Filtering prompt/response training pairs to keep only safe ones. Includes a cheap non-empty sanity check plus a safety judgment.

```markdown
# BeaverTails Safety Judge

I'm curating a set of prompt/response pairs and want to keep only the ones that
are safe to train on. Each row has the user's prompt and the model's response.

Two things per row. First, a cheap sanity check: the response must be non-empty
and contain actual content, not blank or whitespace — drop it if it's empty.
Second, and this is the real question, is the response safe? A safe response is
free of harmful, unsafe, or policy-violating content across the usual harm
categories — violence, self-harm, hate, sexual content, crime, and dangerous
advice — and it either helps harmlessly or appropriately refuses when the request
itself is harmful. This is a judgment call about content and intent, not a keyword
scan: a response that discusses a sensitive topic responsibly is safe, while one
that provides actionable harm is not. Keep the row when the response is both
non-empty and safe; drop it otherwise.
```

**Why this has two routes:** Non-empty check → `code`. Safety judgment → `llm`. The spec explicitly labels the safety check as "a judgment call about content and intent, not a keyword scan" — that's the signal the service needs to route it to the LLM.

---

### 12. Helpfulness Filtering (HelpSteer2-style)

**Use case:** Filtering instruction-response pairs to keep only genuinely helpful ones for supervised training.

```markdown
# HelpSteer2 Helpfulness Judge

I'm filtering instruction-response pairs down to the ones worth keeping for
supervised training. Each row has the user's prompt and the model's response.

Per row, I want two verdicts. The first is mechanical: the response has to be
non-empty and contain real content, so an empty or whitespace-only response is
dropped. The second is the substance — is the response genuinely helpful for what
the user asked? A helpful response addresses the actual request, stays relevant
and usable, and gives enough correct substance to satisfy the intent. A response
that is evasive, off-topic, superficial, or that dodges the question is not
helpful even if it's fluent. This is a judgment about whether the answer earns its
place in the dataset, so read the prompt and the response together and decide
whether a person would consider the response a good, on-target answer. Keep the
row when the response is non-empty and helpful; drop it otherwise.
```

**Why this has two routes:** Non-empty → `code`. Helpfulness judgment → `llm`. The phrase "a judgment about whether the answer earns its place" is the key — helpfulness can't be reduced to a rule.

---

### 13. PII Detection

**Use case:** Scrubbing a response corpus to drop any row whose response leaks personal data.

```markdown
# PII-Leak Judge

I'm scrubbing a response corpus and want to drop any row whose response leaks
personal data. Each row has the model's response text.

Per row, tell me whether the response contains personally identifiable
information — an email address, a phone number, a street address, a government id
such as an SSN, a credit-card number, or similar direct identifiers. This is a
mechanical detection task: these formats have recognizable, checkable structure
(an email has a local part, an "@", and a domain; an SSN is nine digits in the
familiar grouping; a card number passes a Luhn check), so decide by pattern, not by
opinion. Keep the row when the response is clean of such identifiers; drop it the
moment one is present. I care about the presence of the identifier, not whether it
happens to be real — a well-formed SSN-shaped string is a drop regardless.
```

**Why this routes to `code`:** PII formats have checkable structure — regex patterns, Luhn checks, digit groupings. The spec explicitly says "decide by pattern, not by opinion."

---

### 14. Language Match

**Use case:** Building a language-specific training set and dropping rows whose response is in the wrong language.

```markdown
# Language-Match Judge

I'm building an English-only training set and want to drop rows whose response
isn't in the expected language. Each row has the model's response and the target
language it was supposed to be written in (here, English).

Per row, decide whether the bulk of the response is actually written in the
target language. This is a mechanical language-identification check over the text,
not a quality judgment: a response predominantly in another language, or one that
is mostly non-linguistic filler, is a drop; short unavoidable borrowings (a proper
noun, a code snippet, a standard technical term) inside otherwise-English prose are
fine. Keep the row when the response is in the target language; drop it when it is
in the wrong language. I only care about the language of the text, never whether
the content is correct or helpful.
```

**Why this routes to `code`:** Language identification is mechanical — the spec says "a mechanical language-identification check over the text, not a quality judgment."

---

### 15. Coherence Check

**Use case:** Pre-filtering degenerate or incoherent responses before any quality evaluation — catching truncated, looping, or garbled outputs.

```markdown
# Coherence Judge

I'm filtering out responses that are degenerate or incoherent as text, before I
worry about whether they're correct. Each row has the user's prompt and the
model's response.

Per row, judge whether the response is coherent, well-formed prose: it reads as
fluent, grammatical language that holds together, stays on a consistent thread,
and doesn't collapse into repetition, truncated fragments, looping boilerplate, or
garbled output. This is a judgment about the readability and integrity of the
text, not about factual accuracy or helpfulness — a coherent response can still be
wrong, and I'll catch that elsewhere. Keep the row when the response is coherent
and intelligible; drop it when the text degenerates, repeats itself, cuts off
mid-thought, or is otherwise incoherent.
```

**Why this routes to `llm`:** Coherence is a readability judgment, not a pattern check. The spec explicitly says this is "a judgment about the readability and integrity of the text."

---

### 16. Composite Curation Gate (Mixed Route)

**Use case:** A single gate combining multiple quality checks that intentionally mix mechanical and judgment criteria — the most realistic production pattern.

```markdown
# Curation Keep-Gate (multi-criterion)

I'm running a single keep/drop gate over a response corpus that combines several
quality checks at once — the kind of composite filter a real curation pass uses.
Each row has the user's prompt and the model's response, and a row is kept only if
it clears every check.

I want four verdicts per row, and I know they don't all check the same way. First,
the response must be non-empty — a blank or whitespace-only response is dropped;
that's a trivial mechanical check. Second, it must not leak personal data such as
emails, phone numbers, or government ids — another mechanical, pattern-based check.
Those two are objective and should be decided by a program. Third, the response
must be safe: free of harmful or policy-violating content, or an appropriate
refusal — that's a judgment call. Fourth, it must be genuinely helpful for the
prompt: on-topic, relevant, and substantive rather than evasive — also a judgment
call. Keep the row only when all four hold; drop it if any single check fails. I'm
deliberately mixing mechanical checks with judgment ones in one grader so the
routing has to split within a single spec.
```

**Why this has mixed routes:** Non-empty → `code`. PII → `code`. Safety → `llm`. Helpfulness → `llm`. The spec explicitly labels each criterion's nature — "trivial mechanical check", "pattern-based check", "judgment call" — giving the service clear routing signals. This is the spec pattern most representative of real production curation pipelines.

---
