# Vendored shared files — DO NOT EDIT

These files are **synced copies** of the plugin-level canonical source under
`plugins/aws-startup-advisor/skills/shared/`. They are vendored into this skill
so the skill folder is **self-contained** — it runs standalone (lifted out, zipped,
or used on its own) without reaching outside its own directory.

**Do not hand-edit anything in this directory.** Edit the canonical source instead,
then run `python3 plugins/aws-startup-advisor/tools/sync-vendored.py` from the repository root to bring every
skill's `references/vendored/` copy back in sync. Every copy must stay **byte-identical**
to the canonical source; CI runs `python3 plugins/aws-startup-advisor/tools/sync-vendored.py --check`
(`mise run lint:vendored-parity`) and fails on any drift, any copy with no canonical source,
any row in the table below with no file on disk, and any file on disk with no row. It cannot
see a new `skills/shared/` file no skill vendors yet — adding one here means the copy **and** a row.

| Vendored path                    | Canonical source                               |
| -------------------------------- | ---------------------------------------------- |
| `ai/bedrock-pricing-cache.md`    | `skills/shared/ai/bedrock-pricing-cache.md`    |
| `dsl/INTERPRETER.md`             | `skills/shared/dsl/INTERPRETER.md`             |

This skill vendors the DSL interpreter contract and the provider-neutral Bedrock pricing
cache. It does not vendor the shared
state schema (`skills/shared/state/phase-status.schema.json`) — agent-advisor's
`.phase-status.json` carries advisor-specific keys and statuses, declared in
SKILL.md § State file per INTERPRETER.md § Skill bindings.
