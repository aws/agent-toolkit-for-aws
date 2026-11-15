---
_assemble: assemble-preferences
_of_phase: clarify
_reads:
  - global
  - compute
  - data
  - storage
  - workflow
  - network
_produces:
  - preferences.json
---

# Assemble preferences

Build candidate rows only from applicable fragment rules. Give each row a stable `question_id`, optional `resource_id`, topic, decision changed, current evidence, and consequence. Deduplicate by `(resource_id, question_id)` and byte-sort by resource ID (null as empty bytes), then question ID.

Present one consolidated assumption sheet. Ask unresolved essential questions in small batches. Persist every row with exactly one disposition:

- `answered`: user supplied the value; provenance is `user`.
- `defaulted`: a named design rule supplies the value; record the rule and user-visible consequence.
- `not_applicable`: an eliminator or inventory fact proves the question cannot affect this resource.
- `unresolved`: no decisive fact or approved default exists. This disposition blocks completion.

Do not create a preference row merely to ask the user to select an AWS product. Re-read the inventory and preferences, verify the raw-inventory SHA-256, reject duplicate rows, require every applicable resource selector's decisive inputs, validate against `schema-render-preferences.json`, and write canonical JSON atomically. Only a document with zero `unresolved` rows may hand off to Design.
