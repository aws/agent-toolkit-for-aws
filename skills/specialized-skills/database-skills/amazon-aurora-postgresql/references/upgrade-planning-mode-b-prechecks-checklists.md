# Mode B — Prechecks & Checklists (Tasks 6–8)

Continues the Mode B workflow from [mode-b-discovery.md](upgrade-planning-mode-b-discovery.md) (Tasks 1–4) and [lts-recommendation.md](upgrade-planning-lts-recommendation.md) (Task 5).

## 6. Live Database Prechecks

Ask the customer how to connect:

1. **SSM Run Command** — requires an EC2 instance ID in the same VPC and DB credentials
2. **RDS Data API** — if enabled, no extra infrastructure needed
3. **Direct connection** — if publicly accessible or a tunnel is set up
4. **User runs the script** — you generate the SQL, the user pastes results back

Then run the PostgreSQL precheck queries from [prechecks-postgresql.md](upgrade-planning-prechecks-postgresql.md).

**Constraints:**

- You MUST ask the user to choose the connection method — do not pick for them
- You MUST NOT create, access, or store AWS credentials or DB passwords directly. Use inline JSON payloads for SSM, user-supplied secret ARNs for Data API, or pre-configured tunnels for direct
- You MUST categorize every finding with one of: 🔴 Critical (blocks upgrade), 🟡 Warning (behavior change), 🟢 Clean
- You MUST generate a recommended parameter group configuration based on findings rather than returning raw query output

## 7. Query Load Analysis (Optional)

After schema prechecks, offer to analyze top queries. Use [query-load-postgresql.md](upgrade-planning-query-load-postgresql.md).

**Constraints:**

- You MUST run EXPLAIN in the PostgreSQL format: `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`
- You MUST categorize each query's upgrade risk with the same three-color system as task 6
- You SHOULD present findings in a compact table (summary, plan issue, upgrade impact, action) rather than raw EXPLAIN output

## 8. Pre- and Post-Upgrade Checklists

Provide:

- Pre-upgrade steps from [pre-checklist.md](upgrade-planning-pre-checklist.md)
- Post-upgrade validation from [post-checklist.md](upgrade-planning-post-checklist.md)

You MUST also surface the engine-specific upgrade **blockers and required cleanup items** directly in your response — do not leave them buried in the precheck files the user hasn't opened. These are the items that most commonly cause upgrade failures or silent breakage.

**For Aurora PostgreSQL, surface at minimum these five items** (from [prechecks-postgresql.md](upgrade-planning-prechecks-postgresql.md), categorized with the 🔴/🟡/🟢 taxonomy):

- 🔴 **Logical replication slots** — active slots BLOCK the upgrade. Inactive slots must be dropped before upgrading.
- 🔴 **Prepared transactions** — any rows in `pg_prepared_xacts` BLOCK the upgrade.
- 🔴 **Unknown-type columns** — any column with `typname = 'unknown'` blocks the upgrade.
- 🟡 **Hash indexes and REINDEX** — only required when upgrading **from a pre-PG-10 source**. For a PG 15 → PG 16 upgrade, REINDEX of hash indexes is **not applicable** — say so explicitly, don't leave the user to wonder.
- 🔴 **Unsupported `reg*` type columns** (`regproc`, `regprocedure`, `regoper`, `regoperator`, `regconfig`, `regdictionary`, `regnamespace`, `regcollation`) — `pg_upgrade` CANNOT persist these OID-referencing types; their presence in user tables BLOCKS the upgrade (it fails). Remove or convert them before upgrading. Only `regclass`, `regtype`, and `regrole` survive an upgrade.
- 🟡 **Extension compatibility** — not all extensions are supported on every target. Enumerate via `SELECT extname, extversion FROM pg_extension` and cross-check against target-version support.
- 🟡 **Reserved words added in newer majors** — check schema object names and queries against the target version's reserved word list; rename or quote before upgrading.

**Constraints:**

- You MUST include engine-specific sections of each checklist, not just common steps
- You MUST surface the engine-specific blockers inline in your response using the 🔴/🟡/🟢 taxonomy — listing only the file path is insufficient because users don't follow those references unprompted
- You MUST explicitly address items that don't apply to this upgrade path (e.g., state "Hash index REINDEX — not applicable for PG 15→16, only relevant from pre-PG-10 sources") rather than silently omitting them; otherwise the user can't tell whether you checked or forgot
- You MUST NOT execute any `modify-db-cluster --engine-version` command because this workflow is planning-only and production upgrades must go through the customer's change process
- You MUST recommend testing on a snapshot-restored cluster before production upgrade
- You SHOULD surface relevant documentation from [documentation-links.md](upgrade-planning-documentation-links.md)

For post-upgrade validation when the user reports a completed upgrade, see [post-upgrade-validation.md](upgrade-planning-post-upgrade-validation.md).
