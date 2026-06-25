# OpenSearch Source Reference

Stable-core facts about self-managed OpenSearch as a source for in-place upgrades or migrations to
Amazon OpenSearch Service. Version-volatile details (exact latest GA 3.x version, current MA support
floor/ceiling) MUST be tagged `[verify]` and resolved against live docs in Step 8 of the workflow.

---

## Upgrade path table

AOS supports **multi-version blue/green jumps** within 2.x and within 3.x — do NOT step every minor.

| Source version | Required waypoints | Mechanism | Notes |
|---|---|---|---|
| OS 1.0–1.2 | 1.3 (mandatory intra-1.x hop) | Blue/green | Only OS 1.3 can upgrade to 2.x |
| OS 1.3 | 2.19 → 3.x | Blue/green (multi-version jump within 2.x allowed) | Example: 1.3 → 2.19 in one blue/green, then 2.19 → 3.x |
| OS 2.x | 2.19 (before crossing to 3.x) | Blue/green (jump directly to 2.19 from any 2.x) | Example: 2.5 → 2.19 in one blue/green (do NOT step 2.5→2.7→2.9…) |
| OS 2.19 | None | Blue/green to 3.x | `aws opensearch upgrade-domain --target-version OpenSearch_<concrete-3.x>` |
| OS 3.x | None | Blue/green within 3.x | Multi-version jump within 3.x allowed |

> Always pass a **concrete version string** in the upgrade command (e.g. `OpenSearch_3.0`). Do NOT write `OpenSearch_3.x` as a placeholder. Verify the latest GA 3.x version against AWS docs `[verify]`.

---

## Two walls forcing reindex on the way to OS 3.x

Both walls apply when the **source index was created on OS 1.x or early 2.x**. Name them explicitly
in any 1.x → 3.x or 2.x → 3.x recommendation.

### 1. Lucene 8 → 10 segment-format wall (load-bearing)

OS 1.x writes Lucene 8 segments. OS 3.x runs Lucene 10. Lucene's segment format is **forward-only** —
Lucene 10 cannot read Lucene 8. Any pre-OS-2.0 index MUST be reindexed on a 2.x intermediate before
the cluster reaches 3.x.

**When it applies:** any index whose segments were written by OS 1.x (i.e., the index was created on
a 1.x cluster and has not been force-merged/reindexed on 2.x).

**Fix:** On the 2.19 intermediate, reindex into a new index (same mapping). Validate doc count,
then cut over aliases. The reindex is what bridges the segment format.

### 2. NMSLIB engine removal

NMSLIB k-NN engine was deprecated in OS 2.19 and **removed in OS 3.0+**. Pre-existing NMSLIB indexes
must be reindexed into FAISS HNSW (or Lucene HNSW) before the 3.x hop.

**When it applies:** k-NN indexes using `"engine": "nmslib"` in index settings.

**Fix:** On the 2.x intermediate, create a new index with FAISS HNSW or Lucene HNSW and reindex.
Validate doc count + recall@10 against the baseline before proceeding to 3.x.

---

## OS 3.x breaking changes

Flag ≥1 of these when recommending a 3.x upgrade target or upgrade path.

| Change | Impact | Action |
|---|---|---|
| **JDK 21 minimum** (was JDK 17 in 2.x) | Plugins / custom code using JDK 17-only APIs may break | Audit custom plugins and client JVMs |
| **NMSLIB removed** | All NMSLIB k-NN indexes unreadable | Reindex to FAISS HNSW on 2.x intermediate (see wall #2 above) |
| Several k-NN index settings renamed / removed | Index creation with old settings fails | Verify current setting names against OS 3.x release notes `[verify]` |
| WLM (Workload Management) rename | API paths changed | Update any WLM automation scripts |

---

## OS → OpenSearch always-flag table (in-place upgrade sources)

Use as the audit checklist for upgrade assessment reports. For ES-source migrations, use
[source-elasticsearch.md](source-elasticsearch.md) instead.

| Feature | Concern | Severity | Lane | Action |
|---|---|---|---|---|
| OS 1.x indexes on a 3.x target | Lucene 8 → 10 segment wall | BLOCKING | risk-blocker | Reindex on 2.x intermediate before 3.x hop |
| NMSLIB k-NN indexes | Engine removed in 3.0 | BLOCKING | risk-blocker | Reindex to FAISS HNSW on 2.x intermediate |
| JDK version in custom plugins | JDK 21 minimum in 3.x | HIGH | risk-blocker | Audit and recompile plugins against JDK 21 |
| ISM policies using deprecated actions | OS 2.x deprecated some ISM operations | MEDIUM | migration-specific | Review and update ISM policies |
| Snapshot compatibility | OS snapshots are version-gated | HIGH | risk-blocker | Verify snapshot repo is accessible from target version `[verify]` |

---

## Always-true rules for OS in-place upgrade sources

- **Blue/green is the PRIMARY mechanism** — name it explicitly; do not describe it as a side-effect.
- **Multi-version blue/green jumps are allowed** within 2.x and within 3.x — do NOT prescribe stepping every minor version.
- **Mandatory waypoints**: OS 1.0–1.2 must reach 1.3 first; any 1.3+ or 2.x source crossing to 3.x must pass through 2.19.
- **Name both walls explicitly** for any 1.x → 3.x or 2.x → 3.x recommendation: the Lucene 8→10 segment wall AND the NMSLIB removal.
- **Concrete version string required** in all runbook commands — never `OpenSearch_3.x`.
