# Annotation Question Design Guide

Guidelines `human-in-the-loop` uses in Step 2 to draft concrete annotation question text from the review recommendation. For auto-labeling's review set and cold-start sample, the question asks for the label itself instead: `references/auto-labeling-input.md` → What annotators see and answer. The recommendation (from context or from the user) says *what kind of review* is needed (e.g., "fact-checking with correction" for accuracy issues). This skill turns that into actual questions using the principles below.

## Question Design Principles

Tie each question to an issue from the `dataset-quality` scorecard (or the user's context), and use the same answer type and scale for the same dimension across records.

## Question Types by Quality Dimension

### Accuracy Issues (Low accuracy scores)

**Recommended approach:** Fact-checking with correction

**Sample questions:**

- "Is this response factually correct? (Yes/No)"
- "If incorrect, what is the correct information?"
- "Rate the factual accuracy on a scale of 1-5"
- "Identify any factual errors and provide corrections"

**Output format:** Boolean + text correction field

### Harmlessness Issues (Low harmlessness scores)

**Recommended approach:** Safety review with flagging

**Sample questions:**

- "Does this response contain harmful, biased, or inappropriate content? (Yes/No)"
- "If yes, explain the specific harm and suggest a safer alternative"
- "Rate the safety level: 1=Very harmful, 5=Completely safe"
- "Flag any content that violates safety guidelines"

**Output format:** Boolean + explanation + suggested revision

### Completeness Issues (Low completeness scores)

**Recommended approach:** Gap identification and extension

**Sample questions:**

- "Does this response fully address all parts of the question? (Yes/No)"
- "What key information is missing from this response?"
- "Rate completeness: 1=Major gaps, 5=Fully complete"
- "Provide additional content to make this response complete"

**Output format:** Rating scale + text field for missing content

### Relevance Issues (Low relevance scores)

**Recommended approach:** Relevance assessment with redirection

**Sample questions:**

- "Does this response directly address the question asked? (Yes/No)"
- "Rate relevance: 1=Off-topic, 5=Perfectly relevant"
- "If irrelevant, what should the response focus on instead?"
- "Rewrite the response to better address the original question"

**Output format:** Rating scale + text field for corrections

### Readability Issues (Low readability scores)

**Recommended approach:** Clarity improvement

**Sample questions:**

- "Is this response clear and easy to understand? (Yes/No)"
- "Rate clarity: 1=Very confusing, 5=Very clear"
- "Identify specific areas that need clarification"
- "Rewrite unclear sections for better readability"

**Output format:** Rating scale + text field for revisions

## Multi-Dimensional Issues

When multiple quality dimensions are problematic, use comprehensive review:

**Sample questions:**

- "Rate each dimension (1-5): Accuracy, Completeness, Relevance, Harmlessness, Readability"
- "For any dimension rated 3 or below, provide specific corrections"
- "What is the primary quality issue with this response?"
- "Rewrite this response to address all identified issues"

## Question Volume Guidelines

**Per record time estimates:**

- Simple binary questions: 30-60 seconds
- Rating scales (1-5): 60-90 seconds  
- Text corrections: 2-5 minutes
- Comprehensive review: 5-10 minutes

**Recommended question limits:**

- Low-confidence records (correction): 3-5 questions max
- Complex multi-dimensional issues: 5-7 questions max

Prefer structured answers (yes/no, a 1–5 scale, a fixed set of choices, a correction text field) over open-ended questions: Step 6 counts them and Step 8 applies them.
