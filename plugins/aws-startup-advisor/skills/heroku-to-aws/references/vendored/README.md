# Vendored shared files — DO NOT EDIT

These files are **synced copies** of the plugin-level canonical source under
`plugins/aws-startup-advisor/skills/shared/`. They are vendored into this skill
so the skill folder is **self-contained** — it runs standalone (lifted out, zipped,
or used on its own) without reaching outside its own directory.

**Do not hand-edit anything in this directory.** Edit the canonical source instead,
then bring every vendored copy back in sync:

```sh
# from the repository root
python3 tools/sync-vendored.py          # copies skills/shared/<path> over every vendored copy
python3 tools/sync-vendored.py --check  # what CI runs (mise run lint:vendored-parity)
```

CI fails when any vendored copy differs from its canonical source or has no canonical
source at all, so a change to `skills/shared/` that forgets the copies cannot merge.

| Vendored path                           | Canonical source                                      |
| --------------------------------------- | ----------------------------------------------------- |
| `dsl/INTERPRETER.md`                    | `skills/shared/dsl/INTERPRETER.md`                    |
| `state/phase-status.schema.json`        | `skills/shared/state/phase-status.schema.json`        |
| `estimate/complexity-tiers.json`        | `skills/shared/estimate/complexity-tiers.json`        |
| `estimate/estimation-infra.schema.json` | `skills/shared/estimate/estimation-infra.schema.json` |
| `estimate/pricing-mode.md`              | `skills/shared/estimate/pricing-mode.md`              |
| `estimate/ri-sp-eligibility.md`         | `skills/shared/estimate/ri-sp-eligibility.md`         |
| `pricing/aws-infra-pricing.json`        | `skills/shared/pricing/aws-infra-pricing.json`        |
| `workshop/workshop-invariants.md`       | `skills/shared/workshop/workshop-invariants.md`       |
