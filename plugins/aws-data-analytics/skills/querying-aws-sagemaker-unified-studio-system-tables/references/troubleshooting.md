# Debugging with the usage tables

## Contents

- [Entities stuck or failed right now](#entities-stuck-or-failed-right-now)
- [When did it start, and what changed then](#when-did-it-start-and-what-changed-then)
- [Who changed it](#who-changed-it)
- [Which project owns a failing resource in another service](#which-project-owns-a-failing-resource-in-another-service)
- [Access problems ("I can't see / open / query X")](#access-problems-i-cant-see--open--query-x)
- [Limits to state plainly](#limits-to-state-plainly)

The usage tables record state, not events: each snapshot says what every entity looked like when it was taken. To debug, find the snapshots where something changed and line them up with the failure the user sees. Then go to the owning service (AWS Glue, Amazon Athena, Amazon Redshift, Amazon EMR, Amazon MWAA, AWS Lake Formation, AWS CloudFormation) in the account the row names. `region_name` is the domain's Region except on ENVIRONMENT rows, so take the Region from the resource itself (a Glue table ASSET carries its ARN in `extended_metadata['resource_id']`).

`domain_entity` and `user_profile` are the short names; qualify them with the full path when running, as in `references/queries.md`.

## Entities stuck or failed right now

```sql
SELECT category_enum, entity_id, entity_name, status_enum, updated_time, updated_by_id,
       owning_project_name, account_id, region_name, snapshot_time
FROM domain_entity
WHERE snapshot_time = (SELECT max(snapshot_time) FROM domain_entity)
  AND (   (category_enum = 'PROJECT'         AND status_enum IN ('DELETING','DELETE_FAILED','UPDATING','UPDATE_FAILED','MOVING'))
       OR (category_enum = 'DOMAIN'          AND status_enum IN ('CREATING','CREATION_FAILED','DELETING','DELETION_FAILED'))
       OR (category_enum = 'NOTEBOOK'        AND status_enum IN ('SYNC_IN_PROGRESS','SYNC_FAILED'))
       OR (category_enum = 'PROJECT_PROFILE' AND status_enum = 'DISABLED'))
ORDER BY updated_time
```

- A transitional state (`DELETING`, `UPDATING`, `MOVING`, `CREATING`, `SYNC_IN_PROGRESS`) that has lasted many snapshots means the entity is stuck, not busy. Count how many snapshots it has held that state.
- A project stuck in `DELETING` or `DELETE_FAILED` usually still has resources behind it. List its CONNECTION, ENVIRONMENT, NOTEBOOK and ASSET rows (by `owning_project_id`) and check those resources in the named account.

## When did it start, and what changed then

```sql
SELECT snapshot_time, status_enum, entity_version, updated_time, updated_by_id
FROM domain_entity
WHERE category_enum = '<CATEGORY>' AND entity_id = '<id>'
  AND snapshot_time >= current_timestamp - interval '7' day
ORDER BY snapshot_time
```

- The first snapshot with the new status brackets the change between the previous snapshot and this one. `updated_time` gives the exact time when the source recorded it. `entity_version` is set only on NOTEBOOK and ASSET rows; for other categories rely on `status_enum` and `updated_time`.
- Check what else changed in that window across the domain, which often points at the cause (a profile disabled, a connection replaced, a blueprint removed). Compare consecutive snapshots inside the window, not the latest snapshot: `updated_time` holds only an entity's most recent update, so an entity changed again later, or deleted since, would be missed. The query starts two days before the window so the first snapshot in it has one to compare with. A change shows up in the first snapshot after it happens, so end the window a day after the failure.

```sql
WITH s AS (
  SELECT snapshot_time, category_enum, entity_id, entity_name, status_enum, entity_version,
         created_time, updated_time, updated_by_id,
         lag(snapshot_time)  OVER (PARTITION BY category_enum, entity_id ORDER BY snapshot_time) AS prev_snapshot,
         lag(status_enum)    OVER (PARTITION BY category_enum, entity_id ORDER BY snapshot_time) AS prev_status,
         lag(entity_version) OVER (PARTITION BY category_enum, entity_id ORDER BY snapshot_time) AS prev_version,
         lag(updated_time)   OVER (PARTITION BY category_enum, entity_id ORDER BY snapshot_time) AS prev_updated
  FROM domain_entity
  WHERE snapshot_time BETWEEN TIMESTAMP '<start> UTC' - interval '2' day AND TIMESTAMP '<end> UTC')
SELECT snapshot_time AS first_seen_in, category_enum, entity_id, entity_name,
       prev_status, status_enum, updated_time, updated_by_id,
       prev_snapshot IS NULL AS appeared,
       created_time >= TIMESTAMP '<start> UTC' AS created_in_window
FROM s
WHERE snapshot_time >= TIMESTAMP '<start> UTC'
  AND (prev_snapshot IS NULL
       OR status_enum    IS DISTINCT FROM prev_status
       OR entity_version IS DISTINCT FROM prev_version
       OR updated_time   IS DISTINCT FROM prev_updated)
ORDER BY snapshot_time, category_enum
```

`appeared` marks an entity first seen in the window. It was created there only if `created_in_window` is true; otherwise the export started exporting its category then, or it was missing from earlier snapshots. For entities deleted in the window, run the deleted-entities recipe in `references/queries.md` with its two bounds replaced by the window's: `max(snapshot_time) FILTER (WHERE snapshot_time <= TIMESTAMP '<end> UTC') AS now_snap` and `max(snapshot_time) FILTER (WHERE snapshot_time < TIMESTAMP '<start> UTC') AS then_snap`.

Validate `<start>` and `<end>` as `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS` before substituting them. A date alone is valid in these literals and means 00:00:00 UTC: Athena reads `TIMESTAMP '2026-11-05 UTC'` as `2026-11-05 00:00:00 UTC`.

## Who changed it

Resolve `updated_by_id` and `created_by_id` through `user_profile`. This returns personal data; show it only because the user asked who made the change.

```sql
SELECT user_id, user_name, user_type_enum, user_status_enum, snapshot_time
FROM user_profile
WHERE snapshot_time = (SELECT max(snapshot_time) FROM user_profile) AND user_id = '<id>'
```

No match means a service identity, such as the literal id `SYSTEM` (or an empty id on the DOMAIN row), not a person.

## Which project owns a failing resource in another service

When a Glue job, Athena or Redshift query, EMR step, notebook or connection fails, find the owner first.

- **A Glue or Redshift table:** ASSET rows carry the source coordinates in `extended_metadata` (`resource_type_enum`, `catalog`, `namespace`, `resource_name`; for a Glue table `resource_id` is the table ARN) plus `owning_project_id` and `account_id`. `region_name` is the domain's Region; take the table's Region from its ARN.

```sql
SELECT entity_id, entity_name, owning_project_name, account_id,
       element_at(extended_metadata, 'resource_id') AS resource_arn,
       element_at(extended_metadata, 'catalog') AS catalog,
       element_at(extended_metadata, 'namespace') AS database_name,
       element_at(extended_metadata, 'resource_name') AS table_name, snapshot_time
FROM domain_entity
WHERE category_enum = 'ASSET'
  AND snapshot_time = (SELECT max(snapshot_time) FROM domain_entity)
  AND lower(element_at(extended_metadata, 'resource_name')) = lower('<table name>')
```

- **A connection:** CONNECTION rows give the name, `connection_scope`, owning project (domain-scoped connections can carry one too), account and Region. A connection that disappeared, or whose `updated_time` changed, right before failures started is a strong lead (`entity_version` is NULL for connections).
- **An environment or blueprint:** ENVIRONMENT rows give `env_blueprint_id` and `env_blueprint_name`, `account_id` and `region_name` (an environment's own Region), which say where the compute or tooling stack lives.

Then query that service directly in that account and Region, for example the Glue job runs or the Redshift query history for the table name.

## Access problems ("I can't see / open / query X")

- Is the user a member? PROJECT_MEMBERSHIP rows for the project, current snapshot: match `extended_metadata['member_user_id']` to the user's id. A member added through a group appears under `['member_group_id']`, and the group's own membership has to be resolved separately. A membership on a project whose `extended_metadata['project_status']` is not ACTIVE is stale access.
- Is the user's profile usable? `user_status_enum` DEACTIVATED or NOT_ASSIGNED in `user_profile` points to no domain access, whatever the memberships say; confirm with the DataZone API before telling the user.
- Did the membership disappear? Compare the user's membership rows across snapshots to find the snapshot where it was removed. The actor columns on membership rows belong to the project, so they don't say who removed the member.

## Limits to state plainly

- The tables lag by up to about a day, more when an export run fails. For "right now" questions, give the snapshot time, and confirm with the DataZone API if the user needs live state.
- They record creates and updates, not logins or reads. "Active users" from these tables is a lower bound.
- They contain no error messages. They say what failed and when; the reason is in the owning service.
