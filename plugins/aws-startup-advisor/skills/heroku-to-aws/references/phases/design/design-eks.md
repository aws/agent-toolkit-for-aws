---
_fragment: eks-mapping
_of_phase: design
_contributes:
  - aws-design.json
---

# EKS Design Branch

> Conditional formation-mapping fragment. Fires only when the compute target preference
> selects EKS; the prose below gates on that value (skip when `elastic_beanstalk`, `ecs-fargate`, or
> absent). When active, it maps ALL formations to EKS pods + a single `eks_cluster`
> aggregate, contributing to `aws-design.json`. The mapping-engine fragment
> (`design-mapping.md`) handles the EB/Fargate paths and all non-formation resources.

---

## EKS Branch Logic

When the compute target preference indicates EKS:

1. **For EACH formation resource** in the inventory:
   - If `config.process_type == "release"`, skip it and add the same run-once deployment-hook warning used by the EB/Fargate mapping. Do NOT create an EKS Deployment for release commands.
   - Look up dyno type in the `eks-pod-sizing.json` knowledge (`rows.<dyno_type>`), matching `config.dyno_type` case-insensitively.
     - **If NOT found**: Reject this formation entry. Add to `warnings[]`:

       > "Unsupported dyno type: `{dyno_type}`. Cannot map to EKS. Please contact support or provide manual sizing."

       Do NOT produce an EKS mapping for this formation, and do NOT count it toward `total_pods` for node-group sizing. Continue to the next resource.
     - **If found**: Extract `req_cpu`, `req_mem`, `lim_cpu`, `lim_mem`, and the node type per the CPU architecture resolution.
   - Produce an EKS Deployment entry with pod resource requests and limits
   - Set `aws_service: "EKS"`
   - Preserve dyno quantity as `replicas` (0–100)
   - If process type is `web` → include Kubernetes Service (type: LoadBalancer) with AWS LB Controller annotations
   - If process type is NOT `web` → Deployment only (no Service)

2. **Produce single EKS cluster entry** (constants from the `eks-pod-sizing.json` knowledge → its `cluster` block):
   - `cluster_name`: from `cluster.cluster_name` (`"heroku-migration-cluster"`)
   - `kubernetes_version`: query the latest EKS-supported stable version at generation time (`aws eks describe-addon-versions`); if the query is unavailable, fall back to `cluster.kubernetes_version_fallback`. Do not hardcode — EKS deprecates older versions on a rolling basis.
   - Node group type: from `cluster.node_group_type_by_pref` keyed on the preference (`eks-managed` → `self-managed`, more control; `eks-or-ecs` → `managed`, less operational burden)
   - Addons: from `cluster.addons`

3. **Node group sizing:**
   - Determine the largest dyno type present across all formations.
   - Select instance type using the **largest-pod-class-wins** rule: use the recommended `node_type` (or `node_type_arm64` when `preferences.workshop.cpu_architecture` is `arm64` and that column exists — see `design-mapping.md` CPU architecture resolution) for the largest dyno present, ranked by the JSON's `node_size_rank` (higher = larger). On a rank tie between `m6i.4xlarge` and `r6i.4xlarge` (or their `m6g`/`r6g` arm counterparts), prefer the general-purpose family unless a RAM-optimized dyno (`*-l-ram`) is the only dyno at that rank. All pods from smaller classes fit on those nodes with room to spare.
   - Calculate node count:
     - `min_size` = 2 (HA)
     - `desired_size` = `max(min_size, ceil(total_pods / 4))` — clamp UP to `min_size`; AWS rejects `desired_size < min_size`, which would otherwise happen for small workloads (`total_pods <= 4`).
     - `max_size` = `desired_size + 2`
   - System overhead per node: from the JSON's `system_overhead_per_node` (500m CPU, 512Mi memory).

4. **Non-formation resources unchanged:**
   - Postgres → RDS/Aurora (existing path)
   - Redis → ElastiCache (existing path)
   - Kafka → MSK (existing path)
   - Add-ons → Fast-Path Table (existing path)

---

## All-or-Nothing Rule

When EKS is selected, ALL formation-type resources map to EKS. No mixing of Fargate and EKS for formations within the same migration. This avoids operational complexity of two container orchestrators.

---

## EKS Service Entry in aws-design.json

```json
{
  "service_id": "eks:<heroku-app>:<process-type>",
  "source_resource_id": "formation:<heroku-app>:<process-type>",
  "heroku_app": "<heroku-app>",
  "aws_service": "EKS",
  "confidence": "deterministic",
  "aws_config": {
    "region": "<target-region>",
    "cluster_name": "<cluster.cluster_name>",
    "namespace": "<heroku-app>",
    "deployment_name": "<process-type>",
    "replicas": <quantity>,
    "container_image": "placeholder:<heroku-app>-<process-type>",
    "process_type": "<process-type>",
    "resources": {
      "requests": { "cpu": "<rows.<dyno>.req_cpu>", "memory": "<rows.<dyno>.req_mem>" },
      "limits": { "cpu": "<rows.<dyno>.lim_cpu>", "memory": "<rows.<dyno>.lim_mem>" }
    },
    "load_balancer": <true if web, false otherwise>,
    "node_group_type": "<managed|self-managed>"
  }
}
```

## EKS Cluster Entry in aws-design.json

```json
{
  "eks_cluster": {
    "cluster_name": "<cluster.cluster_name>",
    "kubernetes_version": "<queried latest stable, else cluster.kubernetes_version_fallback>",
    "node_group_type": "<managed|self-managed, from cluster.node_group_type_by_pref>",
    "node_groups": [
      {
        "name": "general",
        "instance_types": ["<node_type of the largest dyno present, per node_size_rank>"],
        "min_size": 2,
        "max_size": <calculated>,
        "desired_size": <calculated>
      }
    ],
    "addons": "<cluster.addons>"
  }
}
```

## Error Handling

- **Unrecognized dyno type**: Same rejection as the Fargate path — reject that formation, warn naming the unsupported type, and continue (see EKS Branch Logic step 1)
- **Empty Procfile**: Same rejection as Fargate path — at least one process type required
- **Node sizing overflow**: If no single instance type fits the aggregate, use the largest recommended type and increase node count
