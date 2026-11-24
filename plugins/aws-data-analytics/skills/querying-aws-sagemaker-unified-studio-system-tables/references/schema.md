# Usage table schemas

Both tables live in `"s3tablescatalog/aws-sagemaker-unified-studio"."<namespace>"`, where `<namespace>` is the domain id lowercased with `-` replaced by `_`. They are partitioned by day on `snapshot_time` and sorted by `snapshot_time`, then `category_enum` (`domain_entity`) or `user_id` (`user_profile`).

To confirm the live schema:

```bash
aws glue get-table --catalog-id "<ACCOUNT>:s3tablescatalog/aws-sagemaker-unified-studio" \
  --database-name "<namespace>" --name "domain_entity" --region <REGION> \
  --query "Table.StorageDescriptor.Columns[].{name:Name,type:Type}"
```

## Snapshot contract

- A daily export writes one snapshot of the whole inventory. All rows from one run share one `snapshot_time`, so a day partition usually holds one snapshot.
- A rerun replaces that day's partition in one commit. A run that fails writes nothing, so the latest snapshot can be more than a day old: check freshness (`references/queries.md`) before answering a "right now" question.
- Rows expire 365 days after their `snapshot_time`.
- Row key for de-duplication: `(snapshot_time, category_enum, entity_id)` in `domain_entity`, `(snapshot_time, user_id)` in `user_profile`.
- `schema_version` is the table's column-set version and is `1` on every row so far. It doesn't change when the export starts filling a column or exporting a category, so an older snapshot can hold NULLs or lack a category that a newer one has. Don't use it to decide whether a NULL means "not captured".

## domain_entity

| Column | Type | Meaning |
|---|---|---|
| `snapshot_time` | timestamptz, required | When the snapshot was captured. Partition key. |
| `domain_id` | string, required | Domain the entity belongs to, as issued (`dzd-...`). |
| `category_enum` | string, required | Row type. Declared: DOMAIN, DOMAIN_UNIT, PROJECT, PROJECT_PROFILE, PROJECT_MEMBERSHIP, ENVIRONMENT, ENVIRONMENT_BLUEPRINT, DESIGNATION, CONNECTION, SUBSCRIPTION, SUBSCRIPTION_REQUEST, NOTEBOOK, ASSET. Not every declared category is in every domain's export: check what this export holds with a `GROUP BY category_enum` on the latest snapshot. |
| `entity_id` | string, required | Id of the entity, unique only within `(domain_id, category_enum)`. For PROJECT it is the project id. For DOMAIN it is an internal id, not the `dzd-` id: use `domain_id` for that. For PROJECT_MEMBERSHIP it is `<project id>#<principal id>`, followed by `#<designation>` when the member has one. |
| `entity_version` | string | Revision of the entity at `snapshot_time`; increments when the entity changes. Populated for NOTEBOOK and ASSET only, NULL for every other category: to detect changes elsewhere, compare `updated_time`. |
| `entity_name` | string | Display name; its meaning depends on the category. Not an identifier. NULL for PROJECT_MEMBERSHIP, SUBSCRIPTION and SUBSCRIPTION_REQUEST. |
| `owning_project_id` | string | Project that owns the entity. Populated for NOTEBOOK, ASSET, ENVIRONMENT, PROJECT_MEMBERSHIP and CONNECTION (a domain-scoped connection can carry one too). NULL for PROJECT (the row is the project), DOMAIN, DOMAIN_UNIT, PROJECT_PROFILE, ENVIRONMENT_BLUEPRINT and DESIGNATION. For SUBSCRIPTION and SUBSCRIPTION_REQUEST it is the project that owns the subscribed listing (the producer); the subscribing project isn't exported. |
| `owning_project_name` | string | Name of that project at `snapshot_time`. If NULL, join to the PROJECT row with the same id. |
| `domain_unit_id` | string | Domain unit the entity is filed under (PROJECT, PROJECT_PROFILE, CONNECTION, DESIGNATION). |
| `domain_unit_name` | string | Name of that domain unit. |
| `parent_domain_unit_id` | string | DOMAIN_UNIT rows only: the parent unit's `entity_id`, for a self-join. |
| `status_enum` | string | Lifecycle state, per category. PROJECT: ACTIVE, MOVING, DELETING, DELETE_FAILED, UPDATING, UPDATE_FAILED. DOMAIN: AVAILABLE, CREATING, CREATION_FAILED, DELETING, DELETED, DELETION_FAILED. PROJECT_PROFILE: ENABLED, DISABLED. NOTEBOOK: ACTIVE, ARCHIVED, SYNC_IN_PROGRESS, SYNC_FAILED. Other categories report their own state names (subscriptions: APPROVED, REVOKED, CANCELLED; subscription requests: PENDING, ACCEPTED, REJECTED). NULL for DOMAIN_UNIT, CONNECTION, ASSET, ENVIRONMENT_BLUEPRINT and PROJECT_MEMBERSHIP, meaning not applicable. |
| `created_time` | timestamptz | When the entity was first created. Use for "created in the last N days". |
| `created_by_id` | string | Who created it: a `user_profile.user_id`, the literal `SYSTEM` for a service-created entity, or an empty string on the DOMAIN row. NULL for SUBSCRIPTION and SUBSCRIPTION_REQUEST. On PROJECT_MEMBERSHIP rows it is the project's creator, not the member's. Join to `user_profile.user_id`. |
| `updated_time` | timestamptz | When it was last updated. On PROJECT_MEMBERSHIP rows, the project's last update. |
| `updated_by_id` | string | Last updater: a user id, `SYSTEM`, or an empty string on the DOMAIN row. NULL for SUBSCRIPTION and SUBSCRIPTION_REQUEST. On PROJECT_MEMBERSHIP rows, the project's last updater. |
| `extended_metadata` | map<string,string> | Per-category extras; see below. |
| `schema_version` | string, required | Table schema version that wrote the row. |
| `account_id` | string | 12-digit AWS account the entity is provisioned into. For PROJECT rows this is the domain account. |
| `region_name` | string | AWS Region, for example `us-east-1`. The domain's Region on every row except ENVIRONMENT, which carries its own; it is not the Region of an asset or notebook. |
| `description` | string | Customer-authored description, up to 2,048 characters. |
| `domain_name` | string | The domain's name at `snapshot_time`, copied onto every row (older snapshots may set it on the DOMAIN row only). |
| `env_blueprint_id` | string | Environment blueprint behind the entity (ENVIRONMENT rows). Join to the ENVIRONMENT_BLUEPRINT row. Not enforced as a reference, so a join can miss; use `count(DISTINCT ...)`. |
| `env_blueprint_name` | string | Name of that blueprint. |

### extended_metadata keys

Read with `element_at(extended_metadata, '<key>')`. A key is absent, not NULL, when there is no value. To see which keys a category carries in this domain:

```sql
SELECT DISTINCT k
FROM domain_entity
CROSS JOIN UNNEST(map_keys(extended_metadata)) AS t(k)
WHERE category_enum = 'PROJECT'
  AND snapshot_time = (SELECT max(snapshot_time) FROM domain_entity)
```

| Key | On | Meaning |
|---|---|---|
| `project_category`, `project_profile_id` | PROJECT | Project category and the profile it was created from |
| `connection_scope` | CONNECTION | `DOMAIN` or `PROJECT` |
| `ancestor_domain_unit_ids` | DOMAIN_UNIT | Text of the ancestor domain unit ids; an empty string on the root unit |
| `name_entry_type` | DESIGNATION, PROJECT_PROFILE | ACCEPTED, AUTO_ACCEPTED or MANUAL |
| `member_user_id`, `member_group_id` | PROJECT_MEMBERSHIP | The member: a user id, a group id, or both. `entity_id` uses the user id when there is one |
| `member_identity_type`, `designation` | PROJECT_MEMBERSHIP | The member's identity type and role in the project |
| `project_status` | PROJECT_MEMBERSHIP | Status of the parent project; non-ACTIVE means stale access |
| `environment_id` | Entities inside an environment | The environment they belong to |
| `entity_subtype` | Categories with subtypes | Subtype within the category |
| `is_user_scoped` | CONNECTION | Whether the connection belongs to a single user. Can be an empty string; treat that as unknown, not false |
| `resource_type_enum`, `resource_id`, `catalog`, `namespace`, `resource_name`, `resource_description` | ASSET | Source coordinates of the asset, for example the Glue database and table; for a Glue table, `resource_id` is the table ARN, which also gives its Region |
| `listing_id`, `listing_name` | SUBSCRIPTION, SUBSCRIPTION_REQUEST | Id and name of the subscribed listing. The listing's owning (producer) project is `owning_project_id` |

SUBSCRIPTION and SUBSCRIPTION_REQUEST rows have no listing-id column and `entity_name` is NULL. Group them on `element_at(extended_metadata, 'listing_id')` and label them with `listing_name`.

## user_profile

| Column | Type | Meaning |
|---|---|---|
| `snapshot_time` | timestamptz, required | Snapshot time. |
| `schema_version` | string, required | Table schema version. |
| `domain_id` | string, required | Domain. |
| `user_id` | string, required | The user; the join target for `created_by_id` and `updated_by_id`. |
| `entity_id` | string, required | Id of the profile record itself. |
| `user_name` | string | For SSO users the IAM Identity Center user name; for IAM users the IAM principal ARN. Captured at profile creation and not refreshed. Personal data. |
| `email` | string | Email on the profile, or NULL. Personal data. |
| `user_type_enum` | string | `IAM` or `SSO`. |
| `user_status_enum` | string | ASSIGNED, NOT_ASSIGNED, ACTIVATED, DEACTIVATED. Treat DEACTIVATED and NOT_ASSIGNED as without access, and say so when you report "users with access". |
| `iam_principal_arn` | string | IAM users only. Identifies a principal. |
| `group_profile_id` | string | Group profile that granted access, or NULL. |
| `created_time`, `updated_time` | timestamptz | Profile creation and last update. |
| `extended_metadata` | map<string,string> | Extra attributes. `iam_principal_id` is `<role id>:<session name>` and can name a person. |
| `domain_name` | string | Domain name at `snapshot_time`. |

Show `user_name`, `email`, `iam_principal_arn` and `extended_metadata` only when the user asked about specific people; prefer counts otherwise.
