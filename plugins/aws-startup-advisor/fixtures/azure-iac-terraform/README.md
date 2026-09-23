# azure-iac-terraform — Terraform discovery oracle

A synthetic Azure estate plus a deterministic asserter. This is the **external oracle**
for `azure-to-aws` Discover over Terraform.

## Why it exists

The DSL's `_assert` postconditions cannot verify correctness. The model both produces
the artifact and evaluates the assertion against it, so a run that improvises the ARM
type vocabulary from pretraining — instead of reading
`references/shared/arm-type-canonicalization.md` — still produces well-formed output,
still satisfies every shape assertion in `discover.md`, and still emits `HANDOFF_OK`.
That output would be stamped `confidence: deterministic`, which would be false, and
two runs of the same repo would disagree with each other.

An asserter written in Python is the only thing the model cannot reason its way past.

## What the corpus is built to catch

Every block in `workspace-terraform/` exists to pin a decision where a **plausible
improvisation and the correct answer diverge**. Facts a model gets right by accident
are deliberately not asserted — they cost review attention and prove nothing.

| Corpus construct                                                                           | What a good improviser produces                     | What the table requires                                                             |
| ------------------------------------------------------------------------------------------ | --------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `azurerm_linux_function_app`                                                               | `Microsoft.Web/functionApps`                        | `Microsoft.Web/sites` + `kind`                                                      |
| `azurerm_service_plan`                                                                     | `Microsoft.Web/serverFarms`                         | `Microsoft.Web/serverfarms` (lowercase f)                                           |
| `azurerm_redis_cache`                                                                      | `Microsoft.Cache/redis`                             | `Microsoft.Cache/Redis` — emission convention, NOT an ARM fact; matching folds case |
| `azurerm_cosmosdb_account`                                                                 | `Microsoft.CosmosDB/...`                            | `Microsoft.DocumentDB/databaseAccounts`                                             |
| `azurerm_resource_group`                                                                   | an ID with a `/providers/` segment                  | no `/providers/` segment                                                            |
| no `subscription_id` in the provider block                                                 | an invented GUID                                    | the `<subscription-unknown>` placeholder                                            |
| **5 web apps on one S1 plan**                                                              | 5 compute line items                                | 5 `hosted_on` edges into **one** plan                                               |
| a plan with **zero** apps                                                                  | omitted as uninteresting                            | inventoried, 0 inbound edges, idle finding                                          |
| app in `rg-app`, database in `rg-data`                                                     | edge dropped at the group boundary                  | edge preserved so clustering can merge                                              |
| a private endpoint                                                                         | mapped as a target                                  | skipped, but its `private_link` edge read                                           |
| `azurerm_iothub` (absent from the table)                                                   | a guessed `Microsoft.Devices/IotHubs`               | reported as untranslated                                                            |
| a registry module WITH its source in `.terraform/modules/`                                 | silence, per the blanket `.terraform/` ban          | its 2 resources discovered, tagged `tf_module`                                      |
| `azurerm_subnet_route_table_association`                                                   | an inventory entry, or an untranslated-type warning | no entry, no warning — one `network` edge                                           |
| `azurerm_bastion_host`                                                                     | an EC2 bastion instance                             | **Session Manager** — no host, no cost                                              |
| a registry `module` not in the workspace                                                   | silence                                             | a warning naming the module                                                         |
| `enabled_protocol = "SMB"`                                                                 | dropped                                             | carried — it is the EFS-vs-FSx input                                                |
| `kafka_enabled = true`                                                                     | dropped                                             | carried — it is the MSK-vs-Kinesis input                                            |
| `FIXTURE_SENTINEL_MUST_NOT_APPEAR` in 2 app settings + a VM password                       | recorded, or redacted in place                      | discarded entirely                                                                  |
| **5 local names reused across types** (`core`, `storefront`, `reporting`, `data`, `store`) | one entry per name, silently overwriting            | one entry per full `azurerm_type.name` address                                      |

The reused local names are deliberate and were a real bug: the first draft of this
asserter indexed on `tf_resource_name`, so five of its twenty-one type assertions were
silently pointed at the wrong resource. Identity is the full Terraform address.

The secret sentinel is a greppable token rather than a realistic-looking credential on
purpose: a realistic one would trip `gitleaks`, which runs over this repo, and a
sentinel makes the assertion unambiguous.

## Layout

| Path                              | Role                                                                                                                                                                                               |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `workspace-terraform/`            | the committed INPUT — 31 resources, 1 resolvable module (source on disk under `.terraform/modules/`), 1 unresolvable module, 1 association-only resource                                           |
| `expected-iac-terraform.json`     | pinned Discover facts                                                                                                                                                                              |
| `check_expected_iac_terraform.py` | the Discover oracle                                                                                                                                                                                |
| `after-discover/`                 | GOLDEN Discover output — **30 resources** (31 declared, minus the association-only one) and **5 clusters**. Regenerated from capability run 4, so it is algorithm-traced rather than hand-authored |
| `expected-design.json`            | pinned Design pass-1 facts                                                                                                                                                                         |
| `check_expected_design.py`        | the Design oracle                                                                                                                                                                                  |
| `after-clarify/`                  | GOLDEN Clarify output — a **BLOCKED** clarify. The scripted user declines to state Azure spend, so an ESSENTIAL row is null and the phase gates                                                    |
| `clarify-answers.json`            | the scripted user for that branch                                                                                                                                                                  |
| `clarify-answers-complete.json`   | the scripted user for the COMPLETING branch. **No golden yet** — see the note in that file                                                                                                         |
| `after-design/`                   | GOLDEN Design output — a **completing** design, 16 mapped + 1 deferred. From capability run 4                                                                                                      |

Both asserters are **golden**: each is expected to exit 0 against its committed tree,
so running them is how you confirm a change has not moved the pinned facts.

## Running it

```sh
# 1. copy the corpus into a scratch workspace and run the skill there
cp -r workspace-terraform/. /tmp/azure-probe/ && cd /tmp/azure-probe
#    ...invoke azure-to-aws and let Discover (then Design) run...

# 2. point each asserter at the run directory it produced
python3 <this-dir>/check_expected_iac_terraform.py /tmp/azure-probe/.migration/<MMDD-HHMM>
python3 <this-dir>/check_expected_design.py        /tmp/azure-probe/.migration/<MMDD-HHMM>
```

A `FAIL` naming a specific canonical type is the signal that
`arm-type-canonicalization.md` was not consulted. A `FAIL` naming DynamoDB, EFS, or
Kinesis is the signal that `knowledge/design/fast-path-services.json` was not.

## The Design oracle

`after-design/aws-design.json` is a **completing** design: 16 mapped services, 1 deferred,
every one of the 30 resources accounted for exactly once.

**It replaced `after-design-halted/` on 2026-09-07, because that state became
unreachable.** The corpus's `azurerm_iothub` used to STOP Design unconditionally — the
skill could not name it, so it could not show the resource was free. It now **derives** to
`Microsoft.Devices/iothubs`, `Microsoft.Devices` is a `namespace_routing` gate, and the
resource defers cleanly. A golden for a state the skill can no longer produce is worse than
no golden, because every shape assertion still passes against it.

So the assertion inverted: the oracle now requires that halt **not** occur, and requires
the derived type to appear in `deferred[]` — mapped or deferred, never quietly skipped. The
benign-skip guard survives the inversion unchanged, and it is still the sharpest assertion
here: recording a cost-bearing derived type under a skip code satisfies every shape check,
lets the phase emit `HANDOFF_OK`, and produces an estimate quietly missing a resource.

`pending_rubric[]` is asserted **empty**. That assertion also inverted when the rubrics
landed: at step 3 a resource _mapped past_ a missing rubric file was improvisation; now a
resource still _parked as pending_ is a run that did not load files that exist. Same defect,
opposite side.

`clusters[]` carries `pattern_status: "catalog_absent"` because `design-refs/patterns.md`
does not exist yet, so the asserter checks only that field and the
`target_architecture`-is-null rule. Sizing numbers are dev-tier defaults **stated as
such**: the `knowledge/design/*-sizing.json` tables are not on disk. Note the deliberate
asymmetry — a missing SIZING table degrades a number's precision, while a missing RUBRIC
file would cost the service choice itself, which is why only the latter halts.

### Why `azurerm_iothub` and not something more obvious

The untranslated-type case needs a type that is **durably** absent from
`arm-type-canonicalization.md`. An earlier draft used `azurerm_dev_test_lab`, which turned
out to be fragile: the first coverage pass over the canonicalization table added
DevTest Labs, and this fixture silently stopped testing anything. IoT is out of this
skill's scope by design — neither startup-weighted nor specialist-gated — so a coverage
pass will not absorb it. It also carries a real `sku` block, which makes it cost-bearing on
the three-part test as well as by the untranslated-type rule, so the corpus comment is now
literally true.

### What the Design oracle checks

- **The table itself** — `knowledge/design/fast-path-services.json` for its required rows,
  the precedence invariant (a canonical type resolves to at most one disposition), and the
  App Runner ban. A design is only as trustworthy as the rows it claims to have read.
- **The `deterministic` label in BOTH directions** — every expected row carries it, and
  every entry carrying it names a type that really is in `direct_mappings` with a target
  that row allows. The second direction is what catches an improvised label.
- **Pass-2 outcomes**, each with its plausible-but-wrong answer recorded so the failure
  message names it.

Three fast-path rows exist because a single mechanical discriminator fully determines the
target, so there is no rubric left to run — and each has a famous wrong answer:

| Corpus construct                             | The improviser's answer | The table's answer              |
| -------------------------------------------- | ----------------------- | ------------------------------- |
| Cosmos account, `kind: MongoDB`              | DynamoDB                | **DocumentDB**                  |
| storage share, `enabled_protocol = "SMB"`    | EFS                     | **FSx for Windows File Server** |
| Event Hubs namespace, `kafka_enabled = true` | Kinesis                 | **MSK**                         |

And four rubric outcomes where the wrong answer is the _tempting_ one:

| Corpus construct                               | The tempting answer | The rubric's answer   | Why the tempting one is wrong                                                                                                                                                                                                                                       |
| ---------------------------------------------- | ------------------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S1 plan hosting 5 web apps                     | Fargate             | **Elastic Beanstalk** | App Service is a managed platform; containers change two variables at once mid-migration                                                                                                                                                                            |
| Y1 consumption plan hosting a function app     | Elastic Beanstalk   | **Lambda**            | Y1 is consumption — there is no worker capacity to size                                                                                                                                                                                                             |
| Windows VM                                     | Fargate             | **EC2**               | containerising a Windows VM is a re-architecture nobody asked for                                                                                                                                                                                                   |
| Postgres with `ZoneRedundant` HA on the source | Aurora              | **RDS single-AZ**     | **the most valuable assertion here.** No availability answer was recorded. The source says what they _bought_, not what they _need_; inferring Aurora from silence inflates the estimate with no visible cause. The source HA posture surfaces as a FINDING instead |

## Scope

Terraform only, and Discover + Design pass 1 only. Both are pure functions of
committed input — no pricing, no rubric judgment — so the assertions can be strict
rather than tolerance-based.

**Not covered, and honestly so:**

- **The specialist gates.** The corpus contains no Managed Instance, elastic pool,
  Synapse workspace, Data Factory, or SQL-Server VM image, so no gate fires and the
  five gate rows are reviewed rather than verified. A gate fixture belongs with build
  step 5, when `database.md` exists to be the thing a gate is chosen _instead of_.
- **The `accounting` check is redundant on this corpus.** All 27 resources are already
  covered by a more specific assertion (9 deterministic + 5 pending + 7 skips + 6
  consumed apps), so it cannot fail alone here. It is kept because it is the check
  that survives a corpus change.
- **The cluster merge/split** (build step 4) and the **Estimate reservation baseline**.
  The corpus already contains the inputs for both.

## Both trees, and how the asserter stays identical

`check_expected_design.py` reaches the mapping table at
`../../skills/azure-to-aws/knowledge/design/fast-path-services.json`, a path that
resolves the same way in the `advisor/` and `migrate/` plugin trees. That is what lets
the two copies stay byte-identical under `drift:check`.
