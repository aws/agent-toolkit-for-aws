# Aurora Upgrade Advisor Workflow

Guide customers through Aurora MySQL major and minor version upgrades. Identifies the cluster, recommends target versions (latest vs LTS), runs live prechecks, flags query-plan regressions, and surfaces pre- and post-upgrade checklists. Major version upgrades are blocked — see SKILL.md Safety guidance. This reference helps plan the upgrade.

Execute commands using available tools from the AWS MCP server when connected (sandboxed execution, audit logging, observability). Fall back to the AWS CLI or shell when the MCP server is not available.

## When This Applies

User mentions: upgrade Aurora cluster, what version should I upgrade to, pre-upgrade checklist, post-upgrade steps, Aurora LTS, upgrade prechecks, Aurora MySQL upgrade, or major/minor version upgrade.

## Two response modes

**Mode A — Advisory (no cluster named):** User asks a general question like "what version should I upgrade to?" or "what's the LTS version?" without specifying a cluster. **Skip directly to LTS recommendation** (see "Mode A workflow" below). Do NOT ask for cluster ID and region first — recommend the LTS version with rationale, then offer to run the live workflow if they want a cluster-specific assessment.

**Mode B — Cluster-specific (cluster named):** User names a cluster identifier or asks you to plan an upgrade for a specific cluster. Run the full workflow (Tasks 1–8) with live AWS calls. Tasks are split across:

- [mode-b-discovery.md](upgrade-planning-mode-b-discovery.md) — Tasks 1–4: permissions, no-fabrication guard, acquire parameters, identify the cluster, determine upgrade targets.
- [lts-recommendation.md](upgrade-planning-lts-recommendation.md) — Task 5: recommend two options (LTS vs latest), with the authoritative current-LTS table and trade-offs.
- [mode-b-prechecks-checklists.md](upgrade-planning-mode-b-prechecks-checklists.md) — Tasks 6–8: live database prechecks, query-load analysis, pre/post-upgrade checklists and engine-specific blockers.

When the user reports a **completed** upgrade and asks what to check now, route to [post-upgrade-validation.md](upgrade-planning-post-upgrade-validation.md) (must-surface Aurora items + immediate cluster-state checks) and [post-upgrade-detail.md](upgrade-planning-post-upgrade-detail.md) (statistics refresh, extension updates, plan verification, parameter-group-family migration, snapshot rollback window, monitoring window).

## Mode A workflow (advisory, ~3-4 paragraphs)

When the user asks "what version should I upgrade to?" with their current version (e.g., "I'm on 3.04") but no cluster ID:

1. **Lead with LTS recommendation.** State the designated Aurora MySQL LTS version (Aurora MySQL 3.10 LTS) and frame it as the recommended target. Be direct — don't ask for more info first.
2. **Explain LTS rationale:** longer support window (~3 years of critical fixes), fewer forced upgrade cycles, suitable when stability matters more than new features.
3. **Mention the latest non-LTS option** as the alternative for users wanting newer features, but make clear LTS is the default recommendation.
4. **State the upgrade path:** for major version jumps from old versions (e.g., Aurora MySQL 2.x → 3.x, i.e. MySQL 5.7 → 8.0-compatible), the upgrade may require an intermediate hop or Blue/Green deployment. Direct major-version upgrades require prechecks, a maintenance window, and a rollback plan.
5. **Offer the cluster-specific workflow** as a follow-up: "If you share your cluster ID and region, I can pull the exact valid upgrade targets, run prechecks, and produce a pre/post-upgrade checklist."

Mode A does NOT need cluster identifier, region, or live AWS calls. It is general guidance, version-independent. For the authoritative current-LTS table and the LTS/latest trade-offs, see [lts-recommendation.md](upgrade-planning-lts-recommendation.md).

## Troubleshooting

**Cluster not found.** Check region and cluster identifier. For Global Databases, use `describe-global-clusters` with the global cluster identifier.

**Engine version shows `-limitless`.** Not applicable to Aurora MySQL — Aurora Limitless is an Aurora PostgreSQL-only capability. If you are actually working with an Aurora PostgreSQL cluster, use the `amazon-aurora-postgresql` skill.

**Precheck queries time out via SSM.** Increase the SSM timeout, or switch to RDS Data API if enabled. Large schemas can take minutes for `information_schema` queries.

**RDS Proxy compatibility unclear.** Check target version release notes. If unclear, test on a snapshot-restored clone with the proxy attached before production.

**User wants to roll back after a successful upgrade.** Rollback requires snapshot restore — no in-place downgrade. If the cluster is functioning but has a regression, debug it rather than roll back. See the post-upgrade checklist for regression-hunting steps.

## Deep-Dive References

- [mode-b-discovery.md](upgrade-planning-mode-b-discovery.md), [lts-recommendation.md](upgrade-planning-lts-recommendation.md), [mode-b-prechecks-checklists.md](upgrade-planning-mode-b-prechecks-checklists.md) — the Mode B cluster-specific workflow (Tasks 1–8)
- [post-upgrade-validation.md](upgrade-planning-post-upgrade-validation.md), [post-upgrade-detail.md](upgrade-planning-post-upgrade-detail.md) — post-upgrade validation must-surface items and detailed procedures
- [prechecks-mysql.md](upgrade-planning-prechecks-mysql.md) — live precheck SQL
- [query-load-mysql.md](upgrade-planning-query-load-mysql.md) — regression detection via EXPLAIN
- [pre-checklist.md](upgrade-planning-pre-checklist.md), [post-checklist.md](upgrade-planning-post-checklist.md) — actionable checklists
- [documentation-links.md](upgrade-planning-documentation-links.md) — authoritative AWS documentation pointers
