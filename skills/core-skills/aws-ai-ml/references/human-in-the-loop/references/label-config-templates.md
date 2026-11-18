# Label Studio label_config templates

Translate the questions from `<project-dir>/specs/annotation_specification.md` into Label Studio XML. Combine snippets as needed inside one `<View>` root.

Reference: [Label Studio Tags Documentation](https://labelstud.io/tags)

## Tag types overview

Label Studio uses three tag categories:

- **Object tags** — display data to annotate: `<Text>`, `<Image>`, `<Audio>`, `<Paragraphs>`, `<HyperText>`, `<Table>`
- **Control tags** — annotate the objects: `<Choices>`, `<Labels>`, `<Rating>`, `<Number>`, `<TextArea>`, `<Pairwise>`, `<Ranker>`, `<Taxonomy>`
- **Visual tags** — layout and styling: `<View>`, `<Header>`, `<Style>`

Every control tag needs a unique `name` and a `toName` pointing at an object tag's `name`.

---

## Standard data fields

```xml
<Text name="instruction" value="$instruction"/>
<Text name="completion"  value="$completion"/>
<Text name="prompt"      value="$prompt"/>
```

Any key in your JSONL records becomes `$key` in the config. Keep field names stable across the dataset.

---

## Control tags reference

### Choices — single or multi-select classification

```xml
<Choices name="judgment" toName="completion" choice="single" showInLine="true">
  <Choice value="accept"/>
  <Choice value="reject"/>
</Choices>
```

For checkboxes (several answers), use `choice="multiple"`, e.g. `<Choices name="issues" toName="completion" choice="multiple">` with one `<Choice>` per issue tag.

Key attributes:

- `choice="single"` (default) or `choice="multiple"`
- `showInLine="true"` — render horizontally instead of vertically
- `required="true"` — annotator must select before submitting
- `perRegion="true"` — one annotation per selected region (for span/message-level)
- `hint="..."` on a `<Choice>` — text shown on hover, for the label's definition

### Rating — star scale

```xml
<Rating name="accuracy" toName="completion" maxRating="5"/>
```

Key attributes:

- `maxRating` — number of stars (default 5, max 10)
- `required="true"`
- `perRegion="true"` — rate per selected span/message

### Number — numeric score

```xml
<Number name="score" toName="text" min="1" max="5" required="true"/>
```

Key attributes:

- `min` / `max` — the ends of the scale
- `step` — the increment (default 1)
- `required="true"`

### TextArea — free-text input

```xml
<TextArea name="corrected_completion"
          toName="completion"
          rows="4"
          editable="true"
          maxSubmissions="1"/>
```

Key attributes:

- `rows` — visible height
- `editable="true"` — allow editing after submission
- `maxSubmissions` — how many text entries allowed (1 = single answer)
- `placeholder="hint text"` — greyed-out hint
- `required="true"`

### Labels — span-level entity tagging (NER)

```xml
<Labels name="entities" toName="text">
  <Label value="Person" background="red"/>
  <Label value="Organization" background="blue"/>
</Labels>
```

Key attributes:

- `background` — highlight color for the span
- Use with `<Text>` or `<HyperText>` object tags
- Annotator highlights text spans and assigns a label

### Taxonomy — hierarchical multi-level classification

```xml
<Taxonomy name="category" toName="completion">
  <Choice value="Technical"><Choice value="Programming"/><Choice value="Data Science"/></Choice>
  <Choice value="Non-technical"><Choice value="Business"/><Choice value="Legal"/></Choice>
</Taxonomy>
```

Key attributes:

- Nested `<Choice>` tags create a tree structure
- `maxUsages="1"` — limit selections
- `leafsOnly="true"` — only allow selecting leaf nodes

### Pairwise — side-by-side comparison (A/B preference)

```xml
<Pairwise name="comparison" toName="answer1,answer2"/>
```

Key attributes:

- `toName` must reference exactly two object tags (comma-separated)
- Annotator clicks the preferred side
- Used for reinforcement learning from human feedback (RLHF) preference collection

### Ranker — drag-to-rank ordering

```xml
<Ranker name="rank" toName="responses"/>
```

Used with a `<List>` or multiple `<Text>` objects to let annotators drag items into preferred order.

---

## Object tags reference

### Text — plain text display

```xml
<Text name="prompt" value="$prompt"/>
```

### Paragraphs — multi-turn dialogue / conversation

```xml
<Paragraphs name="dialogue" value="$conversation"
            nameKey="role" textKey="content"
            layout="dialogue"/>
```

Key attributes:

- `nameKey` — JSON field for speaker name (e.g. "role")
- `textKey` — JSON field for message content (e.g. "content")
- `layout="dialogue"` — chat-bubble style rendering

Data format:

```json
{"conversation": [
  {"role": "user", "content": "What is Python?"},
  {"role": "assistant", "content": "Python is a programming language."}
]}
```

### HyperText — rich HTML content

```xml
<HyperText name="webpage" value="$html"/>
```

Use only for HTML the user confirms is trusted (e.g. formatted documents or emails from their own system). Records are untrusted data (`overview.md` → Principle 4), and HTML that renders is shown, with whatever it contains, in every annotator's Studio session in the shared space. Step 3a.7's confirmation asks the user. For any other HTML, use `<Text>`, which shows the markup as text, or strip the markup before upload.

---

## Visual tags

### View — layout container

```xml
<View style="display: flex; gap: 20px;">
  <View style="flex: 1;">...</View>
  <View style="flex: 1;">...</View>
</View>
```

Supports inline CSS via `style` attribute. Use for multi-column layouts.

### Header — section title

```xml
<Header value="Review the response below"/>
```

### Style — CSS block

```xml
<Style>
  .prompt-box { background: #f0f0f0; padding: 10px; border-radius: 5px; }
</Style>
```

Apply classes via `className` on `<View>` tags.

---

## Complete examples

Each example's full `label_config` is a file under `code_templates/label-configs/`. Start from the closest one, change the field names (`$<field>`) to the record's fields and the choices to the approved questions, and write the result to `<project-dir>/specs/label_config.xml`.

### Direct correction (review + edit + status)

Template: `code_templates/label-configs/direct-correction.xml`

### LLM-as-Judge validation (multi-dimension rating)

Template: `code_templates/label-configs/llm-as-judge-validation.xml`

### Pairwise preference for RLHF

Template: `code_templates/label-configs/pairwise-preference-for-rlhf.xml`

Data format:

```json
{"prompt": "Explain recursion", "answer1": "Response A text...", "answer2": "Response B text..."}
```

### Named Entity Recognition (NER)

Template: `code_templates/label-configs/named-entity-recognition.xml`

### Text classification (sentiment / topic)

Template: `code_templates/label-configs/text-classification.xml`

The `Header` holds the question. When the labels come with definitions, put each in its `<Choice>`'s or `<Label>`'s `hint` (`<Choice value="positive" hint="the text praises the product"/>`), not in the `Header`.

### Multi-turn dialogue evaluation

Template: `code_templates/label-configs/multi-turn-dialogue-evaluation.xml`

Example task data:

```json
{"conversation": [{"role": "user", "content": "How do I reset my password?"},
  {"role": "assistant", "content": "Go to Settings > Security > Reset Password."},
  {"role": "user", "content": "I don't see that option."},
  {"role": "assistant", "content": "Which version of the app are you using?"}]}
```

### Document summarization grading

Template: `code_templates/label-configs/document-summarization-grading.xml`

### Response moderation (safety review)

Template: `code_templates/label-configs/response-moderation.xml`

### RAG retrieval evaluation

Template: `code_templates/label-configs/rag-retrieval-evaluation.xml`

### Extractive question answering

Template: `code_templates/label-configs/extractive-question-answering.xml`

### Numeric score (ordinal scale or rubric)

Template: `code_templates/label-configs/numeric-score.xml`

### Summary authoring

Template: `code_templates/label-configs/summary-authoring.xml`

### Supervised fine-tuning (prompt + response authoring)

Template: `code_templates/label-configs/supervised-fine-tuning.xml`

---

## Quick mapping from annotation spec to XML

| Spec phrase | XML snippet |
|---|---|
| "rate on a 1-5 scale" | `<Rating maxRating="5"/>` |
| "is this correct / acceptable" | `<Choices choice="single">` with accept/reject |
| "what is the correct answer" / "edit the response" | `<TextArea editable="true"/>` |
| "flag harmful or biased content" | `<Choices choice="multiple">` with issue tags |
| "rate and provide corrections" | `<Rating>` + `<TextArea>` |
| "which response is better" / "compare A vs B" | `<Pairwise>` with two `<Text>` objects |
| "highlight entities" / "tag spans" | `<Labels>` + `<Text>` |
| "classify the topic" / "what category" | `<Choices choice="single">` or `<Taxonomy>` |
| "rank these responses" | `<Ranker>` |
| "review this conversation" | `<Paragraphs layout="dialogue">` |
| "is the answer grounded in context" | Multiple `<Text>` + `<Choices>` per object |
| "summarize quality" | Side-by-side `<View>` layout + `<Rating>` |
| "copy the answer from the passage" | `<TextArea maxSubmissions="1"/>` on the passage `<Text>` |
| "score on a scale of N to M" (a number field, or a scale that does not start at 1) | `<Number min="N" max="M"/>` |
| "write a summary" | `<TextArea required="true"/>` |

---

## Constraints

- Every control tag needs a unique `name` attribute — export keys come from these
- A control whose answer Steps 6–8 use is named after that field of `references/local-review-guide.md` → Step 3b: Captured row schema: `corrected_completion`, `issues`, `reviewer_notes`, and the rating and code fields there (rename a template's `notes` or `rationale` to `reviewer_notes` when it holds the reviewer's notes). Steps 6–8 read the export by those names (`references/annotation-summary-guide.md` → Reading the feedback file). Other controls keep their task-specific names. A yes/no field (e.g. `has_security_vulnerability`) is a single-choice `<Choices>` with `<Choice value="Yes"/>` and `<Choice value="No"/>`. For auto-labeling input, use the control name `references/auto-labeling-input.md` gives
- Every control tag needs `toName` pointing at an object tag's `name` in the same `<View>`
- Keep the entire config under ~5KB; Label Studio parses and renders this on every task
- `<Choice value="...">` can be any string — spaces, mixed case, special characters all work
- For per-message annotation in dialogues, use `perRegion="true"` on control tags
