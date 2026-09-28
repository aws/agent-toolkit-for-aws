# Vendored shared files — DO NOT EDIT

These files are **synced copies** of the plugin-level canonical source under
`plugins/aws-startup-advisor/skills/shared/`. They are vendored into this skill
so the skill folder is **self-contained** — it runs standalone (lifted out, zipped,
or used on its own) without reaching outside its own directory.

**Do not hand-edit anything in this directory.** Edit the canonical source instead,
then re-copy it over every skill's `references/vendored/` copy of the same file.

Every copy must stay **byte-identical** to the canonical source. A stale copy means
this skill and the canonical source disagree, so verify the copies match (for example
with `md5sum`) after editing the canonical file.

| Vendored path        | Canonical source                   |
| -------------------- | ---------------------------------- |
| `dsl/INTERPRETER.md` | `skills/shared/dsl/INTERPRETER.md` |

This skill vendors ONLY the DSL interpreter contract. It does not vendor the shared
state schema (`skills/shared/state/phase-status.schema.json`) — agent-advisor's
`.phase-status.json` carries advisor-specific keys and statuses, declared in
SKILL.md § State file per INTERPRETER.md § Skill bindings.
