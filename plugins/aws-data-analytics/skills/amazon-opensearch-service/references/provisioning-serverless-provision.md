# Amazon OpenSearch Serverless — Provision Collection

> The AWS MCP server is recommended for executing these commands but is not required — all steps use standard AWS CLI syntax.

## Prerequisites

1. Confirm AWS credentials: `aws sts get-caller-identity`
2. Save AWS account ID and principal ARN

## Step 1: Create Encryption Policy

Required before collection creation:

```bash
aws opensearchserverless create-security-policy \
  --name <collection-name>-encryption --type encryption \
  --policy '{"Rules":[{"ResourceType":"collection","Resource":["collection/<collection-name>"]}],"AWSOwnedKey":true}'
```

> For compliance workloads (PCI-DSS, HIPAA), use customer-managed keys: set `AWSOwnedKey:false` and provide a CMK ARN.

## Step 2: Create Network Policy

**Production (recommended):** Use VPC endpoint for secure private access:

```bash
aws opensearchserverless create-security-policy \
  --name <collection-name>-network --type network \
  --policy '[{"Rules":[{"ResourceType":"collection","Resource":["collection/<collection-name>"]},{"ResourceType":"dashboard","Resource":["collection/<collection-name>"]}],"VpceIds":["<vpce-id>"]}]'
```

**Last-resort dev/test (NOT for production):** `AllowFromPublic: true` exposes the collection to the entire internet — there is no IP scoping or auth gate at the network layer. AWS Security Code Scanner flags this as an open-network default. Prefer one of:

1. **VPC endpoint** (the production pattern shown above) — recommended for any non-throwaway environment.
2. **VPC endpoint with IP-allowlist via SecurityGroup** — when you need broader connectivity than a single VPC.
3. Only when neither is feasible (e.g. ad-hoc lab account with no VPC), use the public form below — and tear down the collection within hours, not days.

```bash
# ⚠️ Public access — entire internet can reach the endpoint. Dev/test ONLY,
# and even then prefer VPC endpoint with SG-scoped CIDR (see Step 5 below).
aws opensearchserverless create-security-policy \
  --name <collection-name>-network --type network \
  --policy '[{"Rules":[{"ResourceType":"collection","Resource":["collection/<collection-name>"]},{"ResourceType":"dashboard","Resource":["collection/<collection-name>"]}],"AllowFromPublic":true}]'
```

## Step 3: Create Data Access Policy

**Base policy (BM25 — least-privilege default).** Grants no `model` access. Use this as-is for plain keyword/BM25 collections:

```bash
aws opensearchserverless create-access-policy \
  --name <collection-name>-data --type data \
  --policy '[{"Rules":[{"ResourceType":"index","Resource":["index/<collection-name>/*"],"Permission":["aoss:CreateIndex","aoss:DescribeIndex","aoss:UpdateIndex","aoss:DeleteIndex","aoss:ReadDocument","aoss:WriteDocument"]},{"ResourceType":"collection","Resource":["collection/<collection-name>"],"Permission":["aoss:CreateCollectionItems","aoss:DescribeCollectionItems"]}],"Principal":["<principal_arn>"]}]'
```

**ML addendum (neural-sparse / agentic only).** Only when the collection uses ML, append this rule to the `Rules` array above — do NOT include it in BM25-only collections, because it grants every AOSS action on every model in the account:

```json
{"ResourceType":"model","Resource":["model/*/*"],"Permission":["aoss:*"]}
```

> **Note:** AOSS data access policies do not support IAM condition keys. Use network policies (VPC endpoints) and principal scoping for access control.
>
> **Tip:** Remove permissions not needed for your use case. For read-only collections, remove aoss:WriteDocument, aoss:UpdateIndex, aoss:DeleteIndex.
>
> For neural-sparse (semantic enrichment) or agentic strategies, the data access policy MUST also grant the `model` and `agent` ResourceTypes, and the `model` resource MUST be `model/*/*` (not `model/<collection-name>/*`), because semantic enrichment registers ML connectors at the account level rather than under the collection name. Omit these rules for plain BM25 collections, because BM25 uses no ML resources. For the full agentic data access policy, see [provisioning-serverless-agentic-setup.md](provisioning-serverless-agentic-setup.md).
>
> **Least-privilege warning:** `aoss:*` on `model/*/*` grants every AOSS action on every model in the account — broader than least-privilege ideally allows. AOSS does not expose scoped per-model ML actions for data access policies, so `aoss:*` is the narrowest functional grant here. Track it and tighten the `Permission` list if AOSS exposes granular model actions. See the fuller discussion in [provisioning-serverless-agentic-setup.md](provisioning-serverless-agentic-setup.md).

## Step 4a: Create Collection Group (NextGen — default)

NextGen is the default serverless target for all strategies except conversational agentic search. A NextGen collection MUST belong to a collection group, so create the group before the collection. Because generation defaults and per-strategy support change over time, verify the current default generation and supported strategies against the AWS docs or `aws opensearchserverless` API capabilities before relying on this.

```bash
aws opensearchserverless create-collection-group \
  --name <collection-name>-group \
  --standby-replicas ENABLED \
  --generation NEXTGEN
```

- `--generation NEXTGEN` is REQUIRED, because omitting it creates a Classic group and NextGen-only features are unavailable and the generation cannot be changed after creation. Verify the current NextGen feature set against the AWS docs ([serverless-overview.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-overview.html)) rather than relying on a hardcoded list.
- `--standby-replicas ENABLED` is required for NextGen — NextGen groups reject `DISABLED`, which is a Classic-only dev/test option. This constraint is generation-specific and may be relaxed — verify whether `DISABLED` is supported for the chosen generation via the AWS docs, or attempt creation and handle any validation error (same pattern used for OCU values below).
- Capacity limits are optional. When set, each OCU value must be one of a service-defined set of allowed steps, and AOSS rejects any other value with an `Invalid value for maxIndexingCapacityInOCU` error. The allowed steps are service-specific limits that change over time — fetch the allowed values from the AWS docs ([serverless-scaling.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-scaling.html)), or attempt creation and parse the validation error message, rather than hardcoding a specific value:

  ```bash
  aws opensearchserverless create-collection-group \
    --name <collection-name>-group --standby-replicas ENABLED --generation NEXTGEN \
    --capacity-limits '{"minIndexingCapacityInOCU":4,"maxIndexingCapacityInOCU":16,"minSearchCapacityInOCU":4,"maxSearchCapacityInOCU":16}'
  ```

Then create the collection **into the group** instead of standalone:

```bash
aws opensearchserverless create-collection \
  --name <collection-name> --type <SEARCH|VECTORSEARCH> \
  --collection-group-name <collection-name>-group
```

> SEARCH and VECTORSEARCH are supported on NextGen while TIMESERIES is Classic-only (see assessment-gotchas.md §9). Supported collection types are generation-specific — verify the valid types against the AWS docs ([serverless-overview.html](https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-overview.html)) at creation time, or attempt creation and handle the validation error, rather than relying on this list.

### Add a collection to an existing group

```bash
aws opensearchserverless list-collection-groups          # find the group name + capacityLimits
aws opensearchserverless create-collection --name <new-name> --type <TYPE> \
  --collection-group-name <existing-group-name>
```

Before creating, verify an encryption policy and network policy already cover `<new-name>` (or a `collection/*` wildcard), because a collection cannot be created if no encryption policy matches its name.

## Step 4b: Create Collection (Classic — standalone fallback)

Use the Classic standalone flow **only when Classic is explicitly required** (e.g. a TIMESERIES collection, or a feature not yet on NextGen), because NextGen is the default target everywhere else in this runbook.

Choose type based on strategy:

- **VECTORSEARCH**: Dense vector search (semantic with dense embeddings)
- **SEARCH**: All other strategies (BM25, neural sparse, hybrid with neural sparse)

Neural sparse requires SEARCH type, not VECTORSEARCH.

```bash
aws opensearchserverless create-collection \
  --name <collection-name> \
  --type SEARCH \
  --description "Search application collection"
```

## Step 5: Wait for Collection Active

```bash
aws opensearchserverless batch-get-collection --names <collection-name>
```

Typically 1-3 minutes.

## Next Step

Proceed to [provisioning-serverless-deploy-search.md](provisioning-serverless-deploy-search.md).
