# Render Clarify preferences contract

`preferences.json` validates against `schema-render-preferences.json`. Its `inventory_fingerprint` is the lowercase SHA-256 of the exact raw `render-resource-inventory.json` bytes used to derive questions.

Questions are unique and byte-sorted by `(resource_id or "", question_id)`. A completed artifact contains only `answered`, `defaulted`, or `not_applicable`; unresolved questions are retained in the interactive assumption sheet but prevent writing the completed artifact. Every row names the decision it can change and its user-visible consequence. Defaults require a named rule and `provenance: default`; answered values require `provenance: user`.

Values never contain secrets, credentials, database/Key Value content, or connection information. AI answers remain attached to the exact deferred profile state and cannot activate AI Design, Estimate, or Generate.
