# heroku-to-aws Shared References

This directory holds references shared _within_ the heroku-to-aws skill (across its
phases). It no longer symlinks the gcp-to-aws sibling skill — heroku-to-aws is
self-contained.

| File                                      | Purpose                                                         |
| ----------------------------------------- | --------------------------------------------------------------- |
| `application-source-contract.schema.json` | Future application-source request and findings definitions      |
| `application-source-contract.md`          | Contract semantics and retained-field purpose review            |
| `heroku-pricing-cache.md`                 | Heroku plan pricing (source-side baseline for the estimate)     |
| `schema-discover-heroku.md`               | `heroku-resource-inventory.json` schema                         |
| `schema-workshop-scenarios.md`            | What-if workshop `scenarios/` + `preferences.workshop` contract |

## Vendored plugin-shared data

Cross-skill data that other DSL migration skills also use has a canonical home in the
plugin-neutral `skills/shared/` tree (not owned by any single skill). To keep this
skill **self-contained** (runnable standalone, without reaching outside its own
directory), those files are VENDORED into `references/vendored/` — byte-identical
copies kept in step by hand. Phase frontmatter `_knowledge` and `INTERPRETER.md`
reference the vendored copies, never the external source:

| Vendored path                                               | Purpose                                      |
| ----------------------------------------------------------- | -------------------------------------------- |
| `references/vendored/dsl/INTERPRETER.md`                    | the DSL runtime contract (the interpreter)   |
| `references/vendored/state/phase-status.schema.json`        | `.phase-status.json` schema (JSON Schema)    |
| `references/vendored/estimate/estimation-infra.schema.json` | `estimation-infra.json` schema (JSON Schema) |
| `references/vendored/estimate/complexity-tiers.json`        | Migration complexity-tier thresholds         |
| `references/vendored/pricing/aws-infra-pricing.json`        | Cached AWS infrastructure pricing            |

See `references/vendored/README.md` for the sync contract. Do NOT hand-edit the
vendored copies — edit the canonical source and copy it over every vendored copy in
the same change.

The gate protocol, re-entry, and phase-status lifecycle that used to live in shared
gcp prose are now defined in `INTERPRETER.md` (§ Gate protocol, § `_re_entry_guard`,
§ The interpreter loop) and each phase's `_preconditions` / `_postconditions`
frontmatter.
