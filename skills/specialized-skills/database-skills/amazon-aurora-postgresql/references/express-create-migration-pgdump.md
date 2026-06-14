# Migration Path 3: pg_dump / pg_restore

Part of [Migrating off Aurora Express Configuration](express-create-migration.md). Best for small datasets where a maintenance window is acceptable: dev/demo-scale migrations and one-time copies into a new cluster.

For the user to run — the skill does not execute these commands.

1. From a machine with PostgreSQL client tooling and network access to both clusters, dump the Express cluster:

   ```
   pg_dump \
     --host <express-cluster-endpoint> \
     --port 5432 \
     --username <master-user> \
     --dbname <database> \
     --format=custom \
     --file <database>.dump
   ```

2. Restore into the Full Configuration cluster:

   ```
   pg_restore \
     --host <full-config-cluster-endpoint> \
     --port 5432 \
     --username <master-user> \
     --dbname <database> \
     <database>.dump
   ```

Illustrative only. Adjust flags: `--no-owner`, `--no-privileges`, `--clean`, `--create`, `--jobs N` for parallel restore.

**Credentials:** retrieve the password from AWS Secrets Manager at run time and pass it to the client via a temporary `~/.pgpass` file (`chmod 600`, deleted after) referenced by `PGPASSFILE` — do NOT use `export PGPASSWORD` (visible in the process environment via `/proc/<pid>/environ`) or inline `--password`. Better still, if the source cluster has IAM database authentication enabled, generate a short-lived token with `aws rds generate-db-auth-token` and use that instead of a long-lived password. Source: [PostgreSQL pg_dump](https://www.postgresql.org/docs/current/app-pgdump.html) and [pg_restore](https://www.postgresql.org/docs/current/app-pgrestore.html) docs.

Considerations:

- The dump is a logical export; extensions, roles, and ownership metadata may need special handling. Use `--no-owner` and `--no-privileges` if the target has different role names.
- Large objects and sequences may need explicit handling.
- Downtime is dump + restore time, scaling roughly linearly with data size. For anything larger than a dev dataset, Path 1 or Path 2 is usually better.
