# Amazon OpenSearch Serverless — Provision Collection

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

```bash
aws opensearchserverless create-access-policy \
  --name <collection-name>-data --type data \
  --policy '[{"Rules":[{"ResourceType":"index","Resource":["index/<collection-name>/*"],"Permission":["aoss:CreateIndex","aoss:DescribeIndex","aoss:UpdateIndex","aoss:DeleteIndex","aoss:ReadDocument","aoss:WriteDocument"]},{"ResourceType":"collection","Resource":["collection/<collection-name>"],"Permission":["aoss:CreateCollectionItems","aoss:DescribeCollectionItems"]},{"ResourceType":"model","Resource":["model/<collection-name>/*"],"Permission":["aoss:CreateMLResource"]}],"Principal":["<principal_arn>"]}]'
```

> **Note:** AOSS data access policies do not support IAM condition keys. Use network policies (VPC endpoints) and principal scoping for access control.
>
> **Tip:** Remove permissions not needed for your use case. For read-only collections, remove aoss:WriteDocument, aoss:UpdateIndex, aoss:DeleteIndex.

## Step 4: Create Collection

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
