# Mode B — Prechecks & Checklists (Tasks 6–8)

Continues the Mode B workflow from [mode-b-discovery.md](upgrade-planning-mode-b-discovery.md) (Tasks 1–4) and [lts-recommendation.md](upgrade-planning-lts-recommendation.md) (Task 5).

## 6. Live Database Prechecks

Ask the customer how to connect:

1. **SSM Run Command** — requires an EC2 instance ID in the same VPC and DB credentials
2. **RDS Data API** — if enabled, no extra infrastructure needed
3. **Direct connection** — if publicly accessible or a tunnel is set up
4. **User runs the script** — you generate the SQL, the user pastes results back

Then run the MySQL precheck queries from [prechecks-mysql.md](upgrade-planning-prechecks-mysql.md).

**Constraints:**

- You MUST ask the user to choose the connection method — do not pick for them
- You MUST NOT create, access, or store AWS credentials or DB passwords directly. Use inline JSON payloads for SSM, user-supplied secret ARNs for Data API, or pre-configured tunnels for direct
- You MUST categorize every finding with one of: 🔴 Critical (blocks upgrade), 🟡 Warning (behavior change), 🟢 Clean
- You MUST generate a recommended parameter group configuration based on findings rather than returning raw query output

## 7. Query Load Analysis (Optional)

After schema prechecks, offer to analyze top queries. Use [query-load-mysql.md](upgrade-planning-query-load-mysql.md).

**Constraints:**

- You MUST run EXPLAIN in the MySQL format: `EXPLAIN FORMAT=JSON`
- You MUST categorize each query's upgrade risk with the same three-color system as task 6
- You SHOULD present findings in a compact table (summary, plan issue, upgrade impact, action) rather than raw EXPLAIN output

## 8. Pre- and Post-Upgrade Checklists

Provide:

- Pre-upgrade steps from [pre-checklist.md](upgrade-planning-pre-checklist.md)
- Post-upgrade validation from [post-checklist.md](upgrade-planning-post-checklist.md)

You MUST also surface the engine-specific upgrade **blockers and required cleanup items** directly in your response — do not leave them buried in the precheck files the user hasn't opened. These are the items that most commonly cause upgrade failures or silent breakage.

**For Aurora MySQL, surface at minimum** (from [prechecks-mysql.md](upgrade-planning-prechecks-mysql.md)):

- 🔴 **Reserved keywords** added in 8.0 used as unquoted identifiers — blocks queries post-upgrade.
- 🔴 **Removed data types / SQL features** (e.g., `utf8mb3` as default, `PRE_5_6_26_UTF8_JSON` flag, deprecated spatial functions).
- 🟡 **sql_mode and default charset/collation changes** — `utf8mb4_0900_ai_ci` becomes the default; application assumptions about collation ordering will shift.
- 🟡 **Query cache removal** (5.7 → 8.0) — if the cluster relied on query cache, expect CPU/latency delta after upgrade.
- 🟡 **Authentication plugin changes** — MySQL 8.0 defaults to `caching_sha2_password`; older clients may need `mysql_native_password`.

**Constraints:**

- You MUST include engine-specific sections of each checklist, not just common steps
- You MUST surface the engine-specific blockers inline in your response using the 🔴/🟡/🟢 taxonomy — listing only the file path is insufficient because users don't follow those references unprompted
- You MUST explicitly address items that don't apply to this upgrade path (e.g., state "Query cache removal — not applicable when upgrading Aurora MySQL 8.0 → 8.4, only relevant from a 5.7 source") rather than silently omitting them; otherwise the user can't tell whether you checked or forgot
- You MUST NOT execute any `modify-db-cluster --engine-version` command because this workflow is planning-only and production upgrades must go through the customer's change process
- You MUST recommend testing on a snapshot-restored cluster before production upgrade
- You SHOULD surface relevant documentation from [documentation-links.md](upgrade-planning-documentation-links.md)

For post-upgrade validation when the user reports a completed upgrade, see [post-upgrade-validation.md](upgrade-planning-post-upgrade-validation.md).
