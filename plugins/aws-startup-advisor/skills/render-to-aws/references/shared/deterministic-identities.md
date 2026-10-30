# Deterministic Render identities

All identity inputs are Unicode NFC strings joined with NUL (`U+0000`), encoded as UTF-8, and hashed with SHA-256 lowercase hexadecimal. IDs retain the first 24 hexadecimal characters. Canonical JSON uses NFC strings, sorted object keys, compact separators, finite numbers, and one trailing newline.

- Canonical resource: `resource\0<kind>\0<Render ID or Blueprint identity>` becomes `rr-<24hex>`. Blueprint identity is `kind\0project-or-_\0environment-or-_\0normalized JSON pointer\0name`.
- Edge: `edge\0<type>\0<from ID>\0<to ID>\0<canonical attributes without trailing newline>` becomes `re-<24hex>`.
- Cluster: `cluster\0<member ID 1>...\0<member ID n>` after member byte-sort becomes `rcl-<24hex>`.
- Build artifacts use their Render ID or immutable digest. If neither exists, normalization rejects the object rather than inventing an artifact.
- Workflow version, task, run, and attempt resources use the same resource rule with their distinct canonical kind.

Duplicate normalized semantic identities, duplicate generated IDs, and hash collisions are errors. They are never merged by suffix. Resources and cluster members sort by ID UTF-8 bytes. Edges sort by `(type, from_id, to_id, id)` UTF-8 bytes. Drift sorts by `(resource_id, field, selected_source)` UTF-8 bytes. Every other semantically unordered object collection sorts by its declared ID; scalar collections sort by normalized UTF-8 bytes.
