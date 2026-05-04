# Patterns for S3 Vectors at Scale

For current limits: search AWS docs for `"S3 Vectors limitations and restrictions"`

## When to Use S3 Vectors

Use S3 Vectors for large, long-term vector data that doesn't require the
high-throughput performance of in-memory vector databases. S3 Vectors provides a
cost-optimized data foundation with query performance optimized for long-term
storage and infrequent access of data. You also benefit from a storage
architecture with strong consistency guarantees, ensuring subsequent queries
always include your most recently added data.

S3 Vectors delivers subsecond latency for infrequent queries and as low as 100ms
for more frequent queries.

## Multi-Tenant Patterns

**Per-tenant index** (recommended for isolation):

- Each tenant gets their own index within a shared vector bucket
- Queries naturally scoped to one tenant
- Easy to delete a tenant's data (delete the index)
- Use when: tenants need strict isolation, different schemas, or independent scaling

**Single index with metadata filtering** (simpler):

- All tenants share one index, filter by `tenant_id` metadata
- Simpler to manage, single query endpoint
- Use when: tenants have identical schemas and moderate scale
- Risk: noisy neighbor if one tenant dominates the index

## Batch Ingestion Pattern

For large-scale ingestion (millions of vectors):

1. Batch vectors into groups of up to 500 per PutVectors call
2. Use parallel workers with backoff on `ServiceUnavailableException`
3. For sustained throughput beyond per-index limits, shard across multiple indexes
4. Search AWS docs for `"S3 Vectors limitations and restrictions"` for current per-call and per-second limits

## SSE-KMS Encryption

To create a vector bucket with SSE-KMS:

```bash
aws s3vectors create-vector-bucket \
  --vector-bucket-name <BUCKET_NAME> \
  --encryption-configuration '{"sseType":"aws:kms","kmsKeyArn":"arn:aws:kms:<REGION>:<ACCOUNT>:key/<KEY_ID>"}'
```

You MUST use the full KMS key ARN (not alias or key ID). The KMS key policy MUST grant
`kms:GenerateDataKey` and `kms:Decrypt` to the S3 Vectors service principal `indexing.s3vectors.amazonaws.com`.
Encryption cannot be changed after bucket or index creation.

For full KMS policy examples, search AWS docs for `"S3 Vectors data encryption KMS"`.

## Migration Pattern

When migrating from another vector DB (pgVector, AOSS, etc.):

1. Create vector bucket and index matching source dimensions + distance metric
2. Export vectors from source (with metadata)
3. Batch PutVectors into S3 Vectors
4. Verify with QueryVectors using known test vectors
5. S3 Vectors only supports `cosine` and `euclidean` — if source used dotProduct,
   use `cosine` on normalized vectors as equivalent
