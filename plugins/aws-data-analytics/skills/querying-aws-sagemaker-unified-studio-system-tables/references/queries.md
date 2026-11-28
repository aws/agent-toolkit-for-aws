# Query recipes

## Contents

- [Projects](#projects)
- [Subscriptions (current, "most subscribed")](#subscriptions-current-most-subscribed)
- [Subscription requests ("most popular" in a window)](#subscription-requests-most-popular-in-a-window)
- [Members, environments, blueprints and connections](#members-environments-blueprints-and-connections)
- [Users](#users)
- [Change history](#change-history)

The recipes use the short names `domain_entity` and `user_profile`. When running, qualify them with the full path: `"s3tablescatalog/aws-sagemaker-unified-studio"."<namespace>"."domain_entity"`, where `<namespace>` is the domain id lowercased with `-` replaced by `_`.

Every recipe selects `snapshot_time`, or `max(snapshot_time)` in an aggregate, so the answer can say which snapshot it reflects. For a window query, report the latest value across the rows. When nothing matches, a grouped query returns no rows, and an ungrouped aggregate such as `count(*)` returns one row with a NULL `snapshot_time`. Before answering "none", run the presence check:

```sql
SELECT 1 AS present FROM domain_entity WHERE category_enum = '<CATEGORY>' LIMIT 1
```

No row means the export doesn't carry that category: answer from the DataZone API (see `references/api-fallback.md`).

Prefer aggregating in SQL. When more than 1,000 rows can come back, page `aws athena get-query-results` with `--starting-token`, or let the CLI page for you.

## Projects

Projects created in the last 30 days (still existing):

```sql
SELECT entity_id, entity_name, created_time, created_by_id, snapshot_time
FROM domain_entity
WHERE category_enum = 'PROJECT'
  AND snapshot_time = (SELECT max(snapshot_time) FROM domain_entity)
  AND created_time >= current_timestamp - interval '30' day
ORDER BY created_time
```

Active projects now: the same filter with `status_enum = 'ACTIVE'` and no time bound.

Projects per week, including ones since deleted:

```sql
SELECT date_trunc('week', created_time) AS week, count(DISTINCT entity_id) AS projects,
       max(snapshot_time) AS snapshot_time
FROM domain_entity
WHERE category_enum = 'PROJECT'
  AND snapshot_time >= current_timestamp - interval '90' day
  AND created_time >= current_timestamp - interval '90' day
GROUP BY 1 ORDER BY 1
```

Projects by domain unit and by profile:

```sql
SELECT p.domain_unit_id, arbitrary(p.domain_unit_name) AS domain_unit,
       element_at(p.extended_metadata, 'project_profile_id') AS profile_id,
       count(*) AS projects, max(p.snapshot_time) AS snapshot_time
FROM domain_entity p
WHERE p.category_enum = 'PROJECT'
  AND p.snapshot_time = (SELECT max(snapshot_time) FROM domain_entity)
GROUP BY p.domain_unit_id, element_at(p.extended_metadata, 'project_profile_id')
ORDER BY 4 DESC
```

## Subscriptions (current, "most subscribed")

Count only active subscriptions: `status_enum = 'APPROVED'`. Exclude REVOKED and CANCELLED. Don't derive subscriptions from grants: a consumer project without an environment has subscriptions but no grants.

```sql
SELECT element_at(extended_metadata, 'listing_id') AS listing_id,
       arbitrary(element_at(extended_metadata, 'listing_name')) AS listing,
       count(*) AS active_subscriptions, max(snapshot_time) AS snapshot_time
FROM domain_entity
WHERE category_enum = 'SUBSCRIPTION'
  AND snapshot_time = (SELECT max(snapshot_time) FROM domain_entity)
  AND status_enum = 'APPROVED'
GROUP BY 1 ORDER BY 3 DESC
```

Run this query first even if you expect the category to be absent. When the export doesn't carry SUBSCRIPTION rows, the presence check sends the question to the API fallback. `entity_name` is NULL on these rows; the listing is in `extended_metadata`, so same-named listings stay separate. `owning_project_id` is the listing's producer project.

## Subscription requests ("most popular" in a window)

Popularity by subscription requests means requests **created in the window**, whatever their status now (PENDING, ACCEPTED or REJECTED). Use all snapshots in the window and count distinct request ids, so a request that was later deleted still counts.

```sql
SELECT element_at(extended_metadata, 'listing_id') AS listing_id,
       arbitrary(element_at(extended_metadata, 'listing_name')) AS listing,
       count(DISTINCT entity_id) AS requests, max(snapshot_time) AS snapshot_time
FROM domain_entity
WHERE category_enum = 'SUBSCRIPTION_REQUEST'
  AND snapshot_time >= current_timestamp - interval '7' day
  AND created_time  >= current_timestamp - interval '7' day
GROUP BY 1 ORDER BY 3 DESC
```

Use `'14' day` for two weeks and `'30' day` for a month. Never answer a window question with all-time or currently-active counts. Name every listing tied at the top.

## Members, environments, blueprints and connections

Members per project (current):

```sql
SELECT owning_project_id, arbitrary(owning_project_name) AS project,
       count(DISTINCT entity_id) AS memberships, max(snapshot_time) AS snapshot_time
FROM domain_entity
WHERE category_enum = 'PROJECT_MEMBERSHIP'
  AND snapshot_time = (SELECT max(snapshot_time) FROM domain_entity)
GROUP BY 1 ORDER BY 3 DESC
```

Distinct blueprints per project:

```sql
SELECT owning_project_id, owning_project_name,
       count(DISTINCT env_blueprint_id) AS blueprints,
       array_agg(DISTINCT env_blueprint_name) AS names, max(snapshot_time) AS snapshot_time
FROM domain_entity
WHERE category_enum = 'ENVIRONMENT'
  AND snapshot_time = (SELECT max(snapshot_time) FROM domain_entity)
GROUP BY 1, 2
```

Connections by scope and type:

```sql
SELECT element_at(extended_metadata, 'connection_scope') AS scope,
       element_at(extended_metadata, 'entity_subtype') AS type,
       count(*) AS connections, max(snapshot_time) AS snapshot_time
FROM domain_entity
WHERE category_enum = 'CONNECTION'
  AND snapshot_time = (SELECT max(snapshot_time) FROM domain_entity)
GROUP BY 1, 2
```

## Users

Users with access, by identity type:

```sql
SELECT user_type_enum, count(*) AS users, max(snapshot_time) AS snapshot_time
FROM user_profile
WHERE snapshot_time = (SELECT max(snapshot_time) FROM user_profile)
  AND user_status_enum NOT IN ('DEACTIVATED', 'NOT_ASSIGNED')
GROUP BY 1
```

Who created the most projects (resolves ids to names; personal data, so run only when the user asks about people):

```sql
SELECT p.created_by_id, coalesce(arbitrary(u.user_name), p.created_by_id) AS creator,
       count(*) AS projects, max(p.snapshot_time) AS snapshot_time
FROM domain_entity p
LEFT JOIN user_profile u
  ON u.user_id = p.created_by_id
 AND u.snapshot_time = (SELECT max(snapshot_time) FROM user_profile)
WHERE p.category_enum = 'PROJECT'
  AND p.snapshot_time = (SELECT max(snapshot_time) FROM domain_entity)
GROUP BY p.created_by_id ORDER BY 3 DESC
```

Distinct user ids that created or updated something per project in the last 30 days (a lower bound on active users, not logins). `SYSTEM` and empty ids are services, not people. PROJECT_MEMBERSHIP rows repeat the project's creator and updater, so they add no one:

```sql
SELECT owning_project_id, count(DISTINCT a.actor) AS actors, max(snapshot_time) AS snapshot_time
FROM domain_entity
CROSS JOIN UNNEST(ARRAY[created_by_id, updated_by_id], ARRAY[created_time, updated_time]) AS a(actor, t)
WHERE snapshot_time = (SELECT max(snapshot_time) FROM domain_entity)
  AND owning_project_id IS NOT NULL AND a.actor IS NOT NULL
  AND a.actor NOT IN ('SYSTEM', '')
  AND a.t >= current_timestamp - interval '30' day
GROUP BY 1
```

## Change history

Daily count per category (one snapshot per day):

```sql
WITH daily AS (
  SELECT date(snapshot_time) AS day, max(snapshot_time) AS snap
  FROM domain_entity
  WHERE snapshot_time >= current_timestamp - interval '30' day
  GROUP BY 1)
SELECT d.day, t.category_enum, count(*) AS n, max(d.snap) AS snapshot_time
FROM daily d JOIN domain_entity t ON t.snapshot_time = d.snap
GROUP BY 1, 2 ORDER BY 1, 2
```

Every status change or update of one project (`entity_version` is NULL for projects, so compare `updated_time`):

```sql
SELECT snapshot_time, status_enum, entity_version, updated_time, updated_by_id
FROM (
  SELECT *, lag(snapshot_time)  OVER (ORDER BY snapshot_time) AS prev_snapshot,
            lag(status_enum)    OVER (ORDER BY snapshot_time) AS prev_status,
            lag(entity_version) OVER (ORDER BY snapshot_time) AS prev_version,
            lag(updated_time)   OVER (ORDER BY snapshot_time) AS prev_updated
  FROM domain_entity
  WHERE category_enum = 'PROJECT' AND entity_id = '<project id>')
WHERE prev_snapshot IS NULL
   OR status_enum    IS DISTINCT FROM prev_status
   OR entity_version IS DISTINCT FROM prev_version
   OR updated_time   IS DISTINCT FROM prev_updated
ORDER BY snapshot_time
```

Entities deleted in the last day (in the snapshot a day before the latest, absent from the latest):

```sql
WITH snaps AS (
  SELECT max(snapshot_time) AS now_snap,
         max(snapshot_time) FILTER (WHERE snapshot_time <= (SELECT max(snapshot_time) FROM domain_entity) - interval '1' day) AS then_snap
  FROM domain_entity),
sizes AS (
  SELECT count_if(d.snapshot_time = s.now_snap) AS now_rows,
         count_if(d.snapshot_time = s.then_snap) AS then_rows
  FROM domain_entity d, snaps s
  WHERE d.snapshot_time IN (s.now_snap, s.then_snap))
SELECT o.category_enum, o.entity_id, o.entity_name, o.owning_project_name,
       s.now_snap AS snapshot_time, z.now_rows, z.then_rows
FROM domain_entity o, snaps s, sizes z
WHERE o.snapshot_time = s.then_snap
  AND NOT EXISTS (SELECT 1 FROM domain_entity n
                  WHERE n.snapshot_time = s.now_snap
                    AND n.category_enum = o.category_enum AND n.entity_id = o.entity_id)
```

Compare `now_rows` with `then_rows` before reporting anything as deleted. A large drop, or a category that vanished whole, points at a change in what the export covers rather than at deletions: check the categories in both snapshots (`GROUP BY category_enum`) and tell the user before reporting them as deleted. Rows also arrive in bulk when the export starts exporting a category, so a jump in row count is not by itself a change in the domain. Say how old `now_snap` is when it is more than a day old.

Freshness of the export:

```sql
SELECT max(snapshot_time) AS latest_snapshot,
       date_diff('minute', max(snapshot_time), current_timestamp) AS minutes_old
FROM domain_entity
```
