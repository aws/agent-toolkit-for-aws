# azure-to-aws's own shared references

Skill-OWNED reference material: artifact schemas, extraction rules, and the Azure-side
contracts that only this skill needs. Edit these directly.

Not to be confused with `references/vendored/`, which holds byte-synced copies of the
plugin-neutral canonical sources under `skills/shared/`. Those are **not** editable
here — see `references/vendored/README.md`.

| File                           | What it owns                                                                  |
| ------------------------------ | ----------------------------------------------------------------------------- |
| `schema-discover-azure.md`     | `azure-resource-inventory.json` + `azure-resource-clusters.json` shapes       |
| `schema-preferences.md`        | `preferences.json` shape and the assumption-sheet disposition vocabulary      |
| `schema-workshop-scenarios.md` | `scenarios/index.json` shape and the workshop preference-patch contract       |
| `arm-type-canonicalization.md` | the `azurerm_* → Microsoft.*` table, the traps, and `azure_id` reconstruction |
| `extract-terraform.md`         | Terraform extraction rules, per-type attributes, edges, secret boundary       |

Landing later, per the build sequence: `extract-bicep.md`,
`extract-arm.md`, `azure-live-security-contract.md`,
`schema-discover-rdfa.md`, `schema-discover-billing.md`, `schema-discover-ai.md`,
`azure-pricing-cache.md`, and `migration-complexity.md`.
