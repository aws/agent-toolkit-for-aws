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
   bootstrap (two-step `init -backend=false` then `init`, targeting `aws_s3_bucket.tfstate`
   and `aws_dynamodb_table.tfstate_lock` in `baseline.tf`, per `terraform/README.md`); the
   fill-once tfvars values (region, project, `operations_email`, `billing_email`,
   `security_email`, any Secrets Manager values). State that `baseline.tf` is the account
   security baseline (CloudTrail, GuardDuty, budget alerts, and Config + Security Hub when
   a framework was declared) and point at the three-step opt-out in `terraform/README.md`
   (delete everything outside the `########## Remote State` / `########## End Remote State`
   markers in `baseline.tf`, including the Compliance-Conditional section when present,
   keep the Remote State section because the backend depends on it, and remove the three
   contact variables from `variables.tf` and the tfvars example) — never say "delete the file", which
   removes the state bucket and lock table and leaves three required variables unset.
   If a Windows
   estate, name the AWS Application Migration Service (MGN) prerequisite; if an
   **Azure Edition Windows Server** image was detected, state the hard blocker plainly
   (MGN refuses the image until re-imaged).
3. **Cutover sequence (tier order)** — walk `clusters[]`/tiering in dependency tier
   order (network/identity/secrets → data → compute → edge). For each workload/cluster:
   what moves, the chosen cutover strategy from `preferences.json` (`db_cutover`,
   `vm_cutover`), and the dependency it waits on. Databases: state whether it is
   dump-and-restore vs replication per the `db_cutover` answer — they are different
   runbooks. Write the **Database migration** subsection defined in Step 1a under the
   data tier.
4. **Verification** — per migrated service, a concrete check (endpoint reachable, a row
   round-trips, the app responds, the queue drains). The phase `_assert` requires a
   Verification section.
5. **Deferred / specialist items** — every `deferred[]` entry, named, with what a
   specialist must decide (Synapse, Managed Instance, elastic pools, Data Factory, etc.).
   A deferral silent in the runbook is discovered at cutover.
6. **Rollback / cutover notes** — keep the Azure resource running until verification
   passes; DNS/traffic cutover last.

## Step 1a: MIGRATION_GUIDE.md — Database migration subsection
Write this subsection whenever the Azure inventory or `aws-design.json` contains a data
store of any engine: a relational database, Cosmos DB, Azure Cache for Redis, or anything
else. Write a `dump_restore` or `dms` branch only when a covered relational database is
present. For that case, read `data.db_cutover` from `preferences.json`. Step 3b of the
Decision gate has already confirmed it (the Generate precondition refuses a row still
flagged `deferred_to_generate`), so write exactly the branch the user chose and no other.
Do not re-derive the answer from database size. An estate whose only data stores are other
engines may have no `db_cutover` answer; write only the **Not covered by this runbook**
note for it, so the guide still says that no tested data-migration path exists. For such an
estate, write just the **Not covered by this runbook** note below, under a Database migration
heading, and no branch: `scripts/02-migrate-data.sh` prints `ENGINE_NOT_SUPPORTED` for them
and cites that note.

Everything below is a checklist the operator carries out. This phase runs no database
command and does not start replication. For `dump_restore` on PostgreSQL or MySQL the offline
copy has a script, `scripts/02-migrate-data.sh`, that the operator previews and runs. For `dms`
and for every unsupported engine that script is a named HOLD and contains no replication
step. The guide must say so plainly. Any statement that a cutover is online or near-zero-downtime needs a
tested mechanism behind it; none exists in this skill, so the `dms` branch is an
operator checklist for AWS DMS, run by the operator in AWS DMS, and never a claim that
this plugin performs or verifies replication. This is the same rule gcp-to-aws applies in
`generate-infra.md` (online cutover needs a tested replication mechanism).

State the engine covered by each database. Only Azure Database for PostgreSQL Flexible
Server and Azure Database for MySQL Flexible Server are covered. Write the **Not covered
by this runbook** note below for every other engine.

### Branch: `dump_restore` (maintenance window)
Use when `data.db_cutover` is `dump_restore`. Number the steps:

1. **Plan the window.** State the expected downtime as proportional to database size,
   plus restore time, verification time and DNS/connection switch. Give no minutes figure
   that was not measured; tell the operator to rehearse the dump and restore on a copy and
   time it. The 100 GiB default that selected this branch is a Clarify default, not a
   guarantee that the window will be short.
2. **Freeze writes.** Stop every application writer on the Azure side (scale the app to
   zero, or put it in maintenance mode) while leaving reads. Record the time. The freeze
   stays in force through verification.
3. **Dump.** PostgreSQL: a custom-format `pg_dump` of each database, taken against the
   Flexible Server fully qualified host name over TLS. MySQL: `mysqldump` with
   `--single-transaction`. The script dumps one database: it does not dump roles or grants. A PostgreSQL dump
   does include `CREATE EXTENSION` for each non-system extension, so an extension the target
   engine version cannot create stops the restore. Create the roles the application needs on
   the target before the restore, and confirm before the window that every extension in use
   is available on the target engine version; remove or replace one that is not. Store dump files in an encrypted location and delete them after cutover.
4. **Restore.** Create the target database on the generated Amazon RDS or Aurora
   instance, then restore with `pg_restore` (PostgreSQL) or the `mysql` client (MySQL).
   Confirm the target engine major version is compatible and every extension in use is
   available on RDS/Aurora before the window starts.
5. **Verify.** Before any traffic moves, compare source and target: table inventory,
   exact row counts per table, content checksums on the tables that matter, and the
   application invariants (sequence values, foreign-key counts, the newest-row timestamp).
   A row-count match alone is not integrity evidence. Any mismatch stops the cutover.
6. **Switch.** Point the application at the new endpoint, lift the freeze on the AWS side
   only, and run the smoke tests from the Verification section.
7. **Rollback.** Until the switch, rollback is lifting the freeze on Azure; nothing on
   Azure was changed. After writes land on AWS, rolling back loses those writes unless the
   operator copies them back, so keep the Azure server running and read-only until the
   rollback window closes.

**Azure Flexible Server specifics.** Allow the dump host through the server firewall or
run the dump from a host with a private network path; a Flexible Server with private access
(VNet integration) is reachable only from inside that network. Azure's `require_secure_transport`
is on by default, so clients must use TLS. The administrator role on Flexible Server is not
a superuser, so `pg_dump` may skip objects it cannot read; check the dump log for
permission errors rather than assuming it is complete. Credentials come from the
operator's secret store or an interactive prompt, never from the guide.

### Branch: `dms` (AWS DMS full load plus change data capture)
Use when `data.db_cutover` is `dms`. Open the branch with the disclosure above: the
operator runs replication in AWS DMS, and this plugin has no tested replication workflow.
Write the following as a checklist with an unchecked box per item.

**Source prerequisites: Azure Database for PostgreSQL Flexible Server.** Per the AWS DMS
guide to Azure Database for PostgreSQL flexible server as a source:

- [ ] First, confirm the server's major version is on the AWS DMS supported-source list for
  Azure Database for PostgreSQL Flexible Server (11.2, 12.15, 13.11, 14.8 and 15.3 when this
  was written; check the current AWS DMS sources page), and pick a replication engine
  version that supports it. If the version is not listed (for example PostgreSQL 16 or 17),
  stop: use the `dump_restore` branch or a specialist instead, before changing any
  parameter or restarting the server.

- [ ] Set the `wal_level` server parameter to `LOGICAL` (Azure portal, Server parameters).
  Do not assume the older `azure.replication_support` parameter applies to Flexible Server;
  confirm in the current Azure documentation.
- [ ] Set `max_replication_slots` to at least the number of DMS tasks that run at once.
- [ ] Set `max_wal_senders` to a value greater than 1 (and at least the concurrent tasks).
- [ ] Set `max_worker_processes` to at least 16. Lower values can cause "out of
  background worker slots" errors.
- [ ] Restart the server to apply the changes; schedule this as a short outage.
- [ ] Use a role with the `REPLICATION` attribute (and the `azure_pg_admin` membership the
  AWS guide describes) for the DMS source endpoint. Do not reuse the application role.
- [ ] Open a network path from the AWS DMS replication instance to the server: a firewall
  rule for the replication instance's public IP, or private connectivity (VPN or
  ExpressRoute to the VPC). Confirm it from the replication instance with a DMS endpoint
  connection test.
- [ ] Every table to replicate needs a primary key (or a replica identity) for CDC.

**Source prerequisites: Azure Database for MySQL Flexible Server.**

- [ ] First, confirm the server's major version is on the AWS DMS supported-source list for
  Azure Database for MySQL Flexible Server (5.7 and 8 when this was written; check the
  current AWS DMS sources page), and pick a replication engine version that supports it. If
  it is not listed, stop: use the `dump_restore` branch or a specialist instead.

- [ ] Confirm binary logging is on with `binlog_format` `ROW` and `binlog_row_image`
  `FULL`, per the AWS DMS MySQL source requirements. The AWS DMS MySQL source page asks for
  `binlog_checksum` `NONE` only for DMS version 3.4.7 or earlier; on a newer replication
  engine version it is not required. If the task uses an older version, check whether the
  Flexible Server exposes that parameter in the current Azure documentation.
- [ ] Set binary log retention (`binlog_expire_logs_seconds`) to at least 24 hours, and long enough to cover the full
  load plus any outage of the DMS task; a retention of zero deletes logs as soon as they
  are not needed and can break CDC. Longer retention uses more storage.
- [ ] Use a role with the replication and select privileges the AWS DMS MySQL source
  documentation lists, not the administrator role.
- [ ] Open the same network path as for PostgreSQL.

**AWS DMS steps (operator, in the AWS console or through reviewed Terraform).**

1. Create a replication subnet group and replication instance sized for the data volume,
   in the target VPC. The instance incurs hourly charges from Estimate's Migration service
   line.
2. Create the source endpoint (Azure server, TLS on) and the target endpoint (RDS/Aurora).
   Step 3 precreates foreign keys and triggers, and DMS loads several tables at once, so
   child rows can arrive before their parents. On the target endpoint, set the extra
   connection attribute that makes DMS's own sessions skip them: for a PostgreSQL target,
   `afterConnectScript=SET session_replication_role='replica'` (bypasses foreign keys and
   user triggers); for a MySQL target, `Initstmt=SET FOREIGN_KEY_CHECKS=0;` (the AWS DMS
   MySQL target page requires foreign keys to be off during the full load; MySQL has no
   session setting that skips triggers, so step 3 leaves them out of the MySQL schema). Run
   the endpoint connection tests and fix them before continuing.
3. Create the target schema first (for PostgreSQL, `pg_dump --schema-only` /
   `pg_restore`; for MySQL, `mysqldump --no-data --skip-triggers`). A PostgreSQL schema-only
   dump carries the foreign keys and triggers; keep them, because step 2's setting bypasses
   them only for DMS's own sessions. On a MySQL target, keep the foreign keys but leave the
   triggers out: `FOREIGN_KEY_CHECKS=0` does not stop triggers, so every trigger would fire
   on each row DMS writes during the full load and CDC (audit or summary triggers would add
   rows on top of the migrated copies, and a trigger that writes into a table DMS also loads
   can hit duplicate keys). Save the trigger DDL for step 8 with
   `mysqldump --no-create-info --no-data --triggers`. DMS moves data, not secondary objects.
4. Create a database migration task of type full load plus CDC. Set the task's **target
   table preparation mode** to **Do nothing** (`DO_NOTHING`), because step 3 precreated
   the target schema. Do not keep **Drop tables on target** (`DROP_AND_CREATE`): it drops
   each precreated table, with its constraints, defaults and partitions, and creates a
   plain one before the full load. Use **Truncate** (`TRUNCATE_BEFORE_LOAD`) only when the
   target tables hold rehearsal data that should be emptied. Have the operator confirm the
   setting before starting the task. Enable data validation and CloudWatch logging for the
   task.
5. Start the task and wait for the full load to finish and CDC to begin.
6. **Validate.** Watch the DMS validation state per table until every table is validated
   with no failed or suspended entries, and run the same row-count, checksum and invariant
   checks as the `dump_restore` branch.
7. **Monitor lag.** Watch the task's CDC latency source and target metrics in CloudWatch.
   Do not cut over until latency stays near zero for a period the team agrees on.
8. **Cut over.** Freeze application writes on Azure, wait for CDC latency to reach zero
   and validation to pass, and stop the task so no DMS session remains. Fix the objects DMS
   does not carry (sequence values, secondary indexes as needed). On a PostgreSQL target the
   foreign keys and triggers from step 3 were never dropped, so nothing in the schema needs
   re-enabling; application sessions enforce them and fire the triggers from this point on.
   On a MySQL target, create the triggers now from the DDL saved in step 3, before the
   switch, so they do not fire on migrated rows. Before switching, confirm the foreign keys
   and triggers exist (PostgreSQL: `pg_constraint`; MySQL:
   `information_schema.REFERENTIAL_CONSTRAINTS` and `information_schema.TRIGGERS`). That is
   an existence check only: `convalidated = true` does not show that the loaded rows satisfy
   the constraints, because the load did not enforce them. The real integrity check is
   looking for orphaned child rows. Then switch the application to the AWS endpoint and run
   the smoke tests.
9. **Roll back.** Before the switch, rollback is stopping the task and lifting the freeze on
   Azure. After the switch, DMS does not replicate back to Azure by default; keep the Azure
   server until the rollback window closes, and treat reverse replication as a separate
   operator decision.

### Not covered by this runbook
Write this note, naming each affected database, whenever the estate has an engine other
than Azure Database for PostgreSQL Flexible Server or Azure Database for MySQL Flexible
Server (Azure SQL Database, SQL Managed Instance, SQL Server on a VM, Cosmos DB, Azure
Cache for Redis, Synapse, and anything else):

> Database migration for `<resource>` (`<engine>`) is not covered by this runbook. The
> `data.db_cutover` choice (`dump_restore` or `dms`) does not describe a tested path for
> this engine. A specialist must choose the method before cutover.

Do not describe `dump_restore` or `dms` steps for these engines, and do not fall back to
the PostgreSQL steps. Add the engine to the Deferred / specialist items section too.

## Step 1b: MIGRATION_GUIDE.md — Section 3 script subsections
Include a subsection only for a script that was generated, and say that no script has been run.
Every script previews by default (`./scripts/NN-name.sh`) and changes something only with
`--execute`. Start with `./scripts/01-validate-prerequisites.sh`, then `--execute` for its
read-only checks.

- **Data (`02-migrate-data.sh`).** `dump_restore`: list every input by exact name
  (`SOURCE_HOST`, `SOURCE_PORT`, `SOURCE_DB_USER`, `SOURCE_DB_PASSWORD`, `TARGET_HOST`,
  `TARGET_PORT`, `TARGET_DB_USER`, `TARGET_DB_PASSWORD`, `DATABASE_NAME`, `DATA_VERIFIER`,
  `SOURCE_WRITES_FROZEN`, `TARGET_WRITES_FROZEN`), the write-freeze evidence the operator
  must have before setting the two acknowledgements to `yes`, and the `DATA_VERIFIER`
  contract (inventories, exact row counts, checksums, invariants; nonzero on mismatch). Never
  write credentials into the guide. Also list the optional `DUMP_DIR_BASE` (default
  `${TMPDIR:-/tmp}`) and tell the operator to check its free space against the database size
  before `--execute`. PostgreSQL: the script uses `pg_dump` and `pg_restore` with `--no-owner
  --no-acl`, so the target roles must exist first; the dump carries `CREATE EXTENSION` for each
  non-system extension and the restore stops on one the target engine version cannot create, so
  confirm every extension in use is available there before the window; `PGSSLMODE` defaults to
  `require` (encrypts without verifying the server certificate), so use `verify-full` for
  production. MySQL: confirm in current MySQL and Azure documentation which `mysqldump`
  options a managed-server dump needs (view and routine `DEFINER` clauses, GTID settings), and
  that your client accepts the `ssl-mode` option in the generated option file (a MySQL
  5.7.11 or later client); the script does not set those options. `dms` or an unsupported engine: name the HOLD code the
  script prints (`DMS_NOT_IMPLEMENTED`, `ENGINE_NOT_SUPPORTED`, `CUTOVER_UNCONFIRMED`) and
  point at the Database migration subsection. Do not describe replication as scripted.
- **Container images (`03-migrate-containers.sh`).** Inputs `ACR_NAME`, `IMAGE_LIST`,
  `AWS_REGION`, optional `AWS_ACCOUNT_ID`, `ACR_LOGIN_SERVER` and `IMAGE_PLATFORM` (default
  `linux/amd64`). The script copies one platform of each image from ACR to ECR, by
  `repository:tag` (no digests), and checks that each tag exists in ECR; it does not compare
  digests and does not rewrite image references in the application or Terraform. To copy a
  multi-architecture image, the operator chooses a registry-to-registry copy tool that
  preserves the manifest list. Run `terraform apply` first: the script creates a repository
  only when Terraform did not.
- **Secrets (`04-migrate-secrets.sh`).** Inputs `KEY_VAULT_NAME`, `SECRET_NAMES`, `AWS_REGION`.
  Dry-run reads no value. Key Vault keys and certificates are manual work; list them. Run
  `terraform apply` first and set each `SECRET_NAMES` entry to the AWS secret name Terraform
  created (from `terraform output secret_names`; each Secrets Manager secret has the same name
  as its Key Vault secret); the script writes a new version of that existing secret,
  and the generated `aws_secretsmanager_secret_version` ignores changes to `secret_string`, so
  a later apply does not restore the placeholder. A secret name cannot start with `-` and
  should not end with a hyphen followed by six characters (for example `db-secret`):
  Secrets Manager appends a hyphen and six random characters to the ARN, so the script warns
  about such a name. Values are not compared after the copy.
- **Validation (`05-validate-migration.sh`).** Inputs: `AWS_REGION` and, for the sections the
  script contains, `ECS_CLUSTER_NAME`, `EKS_CLUSTER_NAME` and `S3_BUCKET`, all from
  `terraform output`. It takes no argument. A zero exit code does not establish data integrity
  or application health.

## Step 2: README.md — what was generated

List the generated artifacts (the `terraform/` files, the `scripts/` files that were generated, `MIGRATION_GUIDE.md`,
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
