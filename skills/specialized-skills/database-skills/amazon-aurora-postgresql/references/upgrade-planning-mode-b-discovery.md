# Mode B — Discovery (Tasks 1–4)

Cluster-specific workflow. Run these with live AWS calls after the user names a cluster. Continue to [lts-recommendation.md](upgrade-planning-lts-recommendation.md) (Task 5) and [mode-b-prechecks-checklists.md](upgrade-planning-mode-b-prechecks-checklists.md) (Tasks 6–8).

## 1. Check Permissions

**Constraints:**

- You MUST confirm AWS credentials allow `rds:DescribeDBClusters`, `rds:DescribeDBEngineVersions`, and `rds:DescribeDBInstances` before starting
- You MUST pause if credentials are missing — tasks 3–6 require live AWS access
- You MAY proceed with checklist-only tasks (7) without AWS access

## 1a. No Fabrication When Live AWS is Unreachable

If credentials are missing, the cluster isn't found, or any `describe-*` call fails, you MUST report the exact failure to the user and stop that step. There is no "demonstration mode" for this workflow — fabricating example `describe-db-clusters` or `describe-db-engine-versions` output and then recommending targets derived from it produces a plausible-looking answer with no factual basis, and users have acted on those fabricated answers.

**Constraints:**

- You MUST NOT invent values for `EngineVersion`, `Engine`, `DBClusterParameterGroup`, `ValidUpgradeTarget`, instance class, `Status`, or any other field that a `describe-*` call would return, because the user will reasonably assume those values came from their cluster
- You MUST NOT describe such invented output as "expected output shape" or "representative" and then use it as the basis for a recommendation, because that is the exact pattern that misled users in past runs
- You MUST NOT claim in a completion summary that you "used `describe-db-engine-versions` as source of truth" when you did not execute it — self-reporting contradicting the transcript is worse than the original fabrication
- When the cluster cannot be queried, you MUST either (a) show the exact commands the user should run and ask them to paste the JSON output, or (b) ask the user to supply the current engine + version so you can advise on upgrade paths from general knowledge, clearly labeled as non-authoritative
- You MAY present LTS/latest trade-offs and checklists (tasks 5, 8) from general knowledge even without live data, because those are genuinely version-independent guidance
- You MUST NOT present a specific target version (e.g., "upgrade to 16.4") as a recommendation unless `describe-db-engine-versions` actually returned it, because valid targets depend on the current version and change over time

## 2. Acquire Target Parameters

Required: **cluster identifier** (string) and **region** (string, AWS region code, default `us-east-1`).

Optional: **target version** (string, e.g. `16.4`; omit to see all options), **connection method** for live prechecks (one of `ssm`, `data-api`, `direct`, `user-runs-script`).

**Constraints for parameter acquisition:**

- You MUST ask for cluster identifier and region upfront in a single prompt
- You MUST confirm the captured values before running discovery
- You SHOULD offer the four connection methods as choices when ready for prechecks — do not pick for them

## 3. Identify the Cluster

```bash
aws rds describe-db-clusters --db-cluster-identifier <cluster_id> --region <region> \
  --query "DBClusters[0].{Engine:Engine,EngineVersion:EngineVersion,Status:Status,EngineMode:EngineMode,DeletionProtection:DeletionProtection,StorageEncrypted:StorageEncrypted,DBClusterParameterGroup:DBClusterParameterGroup}"
```

If not found, check for Global Database with `describe-global-clusters`. Get instance class with `describe-db-instances --filters "Name=db-cluster-id,Values=<cluster_id>"`.

**Constraints:**

- You MUST detect and handle clusters with no DB instances (empty `DBClusterMembers`). These are usually Aurora Limitless, paused clusters, or mid-migration states. Limitless has a separate upgrade path (`-limitless` engine versions); confirm the variant with the user before proceeding
- You MUST check whether the returned `EngineVersion` contains `-limitless` (e.g. `16.6-limitless`). If it does, confirm with the user that this is an Aurora Limitless cluster and branch to the Limitless-specific upgrade path. Do NOT proceed to task 4 with standard Aurora assumptions
- You MUST NOT offer standard Aurora upgrade targets for a Limitless cluster, or vice versa, because the upgrade paths are incompatible

## 4. Determine Upgrade Targets

```bash
aws rds describe-db-engine-versions --engine <engine> --engine-version <current_version> --region <region> \
  --query "DBEngineVersions[0].ValidUpgradeTarget[*].{EngineVersion:EngineVersion,IsMajorVersionUpgrade:IsMajorVersionUpgrade}"
```

**Constraints:**

- You MUST verify version info via `describe-db-engine-versions` rather than hard-coding because the LTS version and valid targets change over time
- You MUST filter out `-limitless` entries when the source cluster is standard Aurora, and vice versa
