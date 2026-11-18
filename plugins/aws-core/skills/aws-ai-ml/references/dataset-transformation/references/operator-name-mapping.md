# Operator Name Mapping (intent → API operator)

Maps the skill's **intents** (the vocabulary the user and upstream skills speak) to
the **API operator wire names** (see `api-operator-configs.md`).
Used when the routing logic (see `routing-and-guardrails.md`) sends a transformation to the
API lane. This table maps a user intent to the operator name.

The API operator set is fixed by the service. Do NOT
invent operator names — unknown names are rejected by the service.

## Mapping table

| Intent                            | API operator(s)                  | Kind   | Notes                                                                                                                                                                                                                    |
| --------------------------------- | -------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `dedup`                           | **ExactDedup** OR **FuzzyDedup** | 1:1    | One dataset in, one dataset out with duplicates removed. Defaults to near/fuzzy (FuzzyDedup); use exact (ExactDedup) only on request — see below.                                                                        |
| `split`                           | **Split**                        | 1:many | Emits multiple outputs (e.g. train/val/test); `transform(...)` returns `List[DataSet]`. See `api-operator-configs.md` for `Ratios` / `Seed` / `Method`; a **stratified** split uses `StratifyField` (see `op_split.md`). |
| `merge`                           | **Merge**                        | many:1 | Takes no Config; ≥2 inputs enforced by the service (`api-execution-flow.md` uses a 2-input cap with chained pairwise merges).                                                                                            |
| `schema_transform`                | **SchemaConversion**             | 1:1    | Use only when the requested result is exactly expressible by a documented `TargetFormat`. A broad field/column-transform intent alone is not a built-in match; otherwise follow capability-choice precedence in `api-execution-flow.md`. |
| `filter` (schema/format validity) | **SchemaFilter**                 | 1:1    | Drops records failing the expected format.                                                                                                                                                                               |
| `filter` (text quality)           | **TextQualityFilter**            | 1:1    | Urls / Alphanumeric / WordRepetition / CharRepetition / Mojibake / CharacterLength / AverageLineLength.                                                                                                                  |
| `filter` (language)               | **LanguageFilter**               | 1:1    | Keeps rows whose detected language is in `Languages` and scores at least `MinScore`; drops the rest, and always drops rows with no detectable text. API lane only, one flat text field.                                 |
| `redact` / `filter` (PII)         | **PiiRedaction**                 | 1:1    | Finds PII in one field per row (`MessagesField` or `TextField`) and tags, redacts (`[TYPE]` markers), or drops those rows per `DefaultAction` / `ActionMap`. API lane only.                                             |

> **Intents not in the table above.**
> These do not have a deterministic built-in API operation. Do NOT invent
> operator names for them. On the **local lane**, handle supported local
> operations with the matching local workflow. On the **API lane**, use the
> capability-choice precedence in `api-execution-flow.md`.
> See that reference for CodeGen and direct-BYOC paths and
> `routing-and-guardrails.md` for the complete routing rules.

## Intent dialogue & disambiguation

- **`dedup` has two variants — default to fuzzy.** When the user says "deduplicate,"
  default to **near/fuzzy** duplicates (similar-but-not-identical → FuzzyDedup). State
  that default in the first routing/confirmation response and retain it in the Step 4
  summary; use **exact** (byte/normalized-equal → ExactDedup) only when the user asks for
  it. Do not block on the choice.
- **`filter` maps three ways** — clarify whether they mean dropping malformed-format
  records (SchemaFilter), low-quality text by a known metric (TextQualityFilter), or rows
  outside a set of languages (LanguageFilter: "keep only English", "drop non-English
  rows"). For a language filter, confirm the language codes and whether low-confidence
  detections should also go (`MinScore`); unless the user arrives from a `dataset-quality` `language_detection` run,
  offer that metric first to show the language mix and how many rows would go, and
  submit the filter after the user takes or declines it.
- **PII requests default to PiiRedaction** ("remove PII", "redact emails", "mask
  personal data", "drop rows with SSNs"), never to a local text filter or
  generated substitute by default. API capability overrides are owned by
  `api-execution-flow.md`. Confirm the field to scan (propose the chat or text
  field from the detected schema, or the column a `dataset-quality` run used,
  before asking) and the action: redact (replace the PII spans), drop (remove
  the row), or
  tag (keep everything and only report it), overall or per entity type (`ActionMap`).
  Unless the user arrives from a `dataset-quality` `pii_detection` run, offer that metric first to
  estimate how much PII there is, and submit after the user takes or declines it.
- **Dropping a named column is not PiiRedaction**, even when the column holds PII ("strip
  the PII column customer_name", "remove the email column"). That is a column change
  that follows the normal routing (`routing-and-guardrails.md`): `schema_transform` on the
  local lane; on the API lane, use the capability-choice precedence in
  `api-execution-flow.md`.
  `PiiRedaction` finds PII inside the text of one field and never removes a column.
