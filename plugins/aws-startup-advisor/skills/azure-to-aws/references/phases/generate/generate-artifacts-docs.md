---
_fragment: artifacts-docs
_of_phase: generate
_contributes:
  - MIGRATION_GUIDE.md
  - README.md
---

# Generate — Documentation

> **Fragment unit.** See `generate.md` for how it is composed into the phase.

`MIGRATION_GUIDE.md` is the runbook: prerequisites, the cutover sequence in tier order,
and a Verification section per migrated service. `README.md` lists what was generated
and how to apply it.

Where a specialist gate deferred a resource, the guide says so plainly and names what a
specialist would need to decide. A deferral that does not surface in the runbook is a
deferral the customer discovers during cutover.

**Execute the steps in order.**

## Inputs

Read from `$MIGRATION_DIR/`: `aws-design.json` (`services[]`, `clusters[]` with `tier`,
`deferred[]`), `azure-resource-clusters.json` (tier ordering + justifications),
`preferences.json` (cutover answers, availability, licensing), `estimation-infra.json`
(cost tiers), and the emitted `terraform/` file list.

## Step 1: MIGRATION_GUIDE.md — the runbook

Required sections, in order:

1. **Overview** — one paragraph: what estate was found (workload count from
   `clusters[]`), what it becomes on AWS, and that this is a draft plan to review.
2. **Prerequisites** — an AWS account + credentials; Terraform ≥ 1.5; the S3 backend
   bootstrap (two-step `init -backend=false` then `init`, per `terraform/README.md`); the
   fill-once tfvars values (region, project, any Secrets Manager values). If a Windows
   estate, name the AWS Application Migration Service (MGN) prerequisite; if an
   **Azure Edition Windows Server** image was detected, state the hard blocker plainly
   (MGN refuses the image until re-imaged).
3. **Cutover sequence (tier order)** — walk `clusters[]`/tiering in dependency tier
   order (network/identity/secrets → data → compute → edge). For each workload/cluster:
   what moves, the chosen cutover strategy from `preferences.json` (`db_cutover`,
   `vm_cutover`), and the dependency it waits on. Databases: state whether it is
   dump-and-restore vs replication per the `db_cutover` answer — they are different
   runbooks.
4. **Verification** — per migrated service, a concrete check (endpoint reachable, a row
   round-trips, the app responds, the queue drains). The phase `_assert` requires a
   Verification section.
5. **Deferred / specialist items** — every `deferred[]` entry, named, with what a
   specialist must decide (Synapse, Managed Instance, elastic pools, Data Factory, etc.).
   A deferral silent in the runbook is discovered at cutover.
6. **Rollback / cutover notes** — keep the Azure resource running until verification
   passes; DNS/traffic cutover last.

## Step 2: README.md — what was generated

List the generated artifacts (the `terraform/` files, `MIGRATION_GUIDE.md`,
`migration-report.html`), a one-line "how to apply" (`cd terraform && terraform init …`),
and the cost-tier note: Premium/Balanced/Optimized are pricing scenarios on one map; this
Terraform is the Balanced baseline. The phase `_assert` requires README to list the
generated artifacts.

## Status — implemented (build step: Generate)

Implemented, mirroring gcp-to-aws's `generate-artifacts-docs.md`: MIGRATION_GUIDE with
Prerequisites + tier-ordered cutover + per-service Verification + deferred items, and a
README that lists artifacts and the cost-tier note. Azure specifics added: MGN /
Azure-Edition-Windows prerequisite, and db/vm cutover strategy driven by the Clarify
answers.
