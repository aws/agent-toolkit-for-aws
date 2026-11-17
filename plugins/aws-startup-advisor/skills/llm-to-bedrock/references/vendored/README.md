# Vendored shared files: DO NOT EDIT

These files are **synced copies** of the plugin-level canonical source under
`plugins/aws-startup-advisor/skills/shared/`. They are vendored into this skill
so the skill folder is **self-contained**: it runs standalone (lifted out, zipped,
or used on its own) without reaching outside its own directory.

**Do not hand-edit anything in this directory.** Edit the canonical source instead,
then run `python3 plugins/aws-startup-advisor/tools/sync-vendored.py` from the repository root to bring every
skill's `references/vendored/` copy back in sync. Every copy must stay **byte-identical**
to the canonical source; CI runs `python3 plugins/aws-startup-advisor/tools/sync-vendored.py --check`
(`mise run lint:vendored-parity`) and fails on any drift, any copy with no canonical source,
any row in the table below with no file on disk, and any file on disk with no row.

| Vendored path                      | Canonical source                                 |
| ---------------------------------- | ------------------------------------------------ |
| `ai/bedrock-pricing.json`          | `skills/shared/ai/bedrock-pricing.json`          |
| `ai/models/anthropic-bedrock.json` | `skills/shared/ai/models/anthropic-bedrock.json` |
| `ai/models/openai-bedrock.json`    | `skills/shared/ai/models/openai-bedrock.json`    |

This skill vendors the Bedrock token-rate table read by `scripts/bedrock_pricing.py`, and the
Anthropic/OpenAI model catalogs read by `scripts/model_catalog.py` (inference-profile prefixes and
per-model endpoint Regions for `iam_policy.py` and `preflight_bedrock.py`). The catalogs are rendered
from `skills/shared/ai/models/bedrock-model-registry.json`; change the registry, rebuild, then sync. The
`telemetry/` directory is generated separately and is not listed here.
