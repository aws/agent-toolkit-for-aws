# Auth Model Selector

Decision guide for choosing the right authentication model for ElastiCache.

## Auth Model Comparison

| Auth Model | Where It Fits | Strengths | Constraints | Recommendation |
|------------|--------------|-----------|-------------|----------------|
| IAM auth + RBAC | Valkey 7.2+ / Redis OSS 7.0+ with cloud-native clients (Lambda, ECS, EKS) | Least-privilege; no password distribution; short-lived credentials; integrates with IAM roles | 15-minute token validity; 12-hour max connection lifecycle; no IAM re-auth inside MULTI/EXEC; requires IAM SDK integration in client | **Preferred for new builds** when clients support IAM token generation |
| RBAC + passwords in Secrets Manager | Valkey 7.2+ / Redis OSS 6.0+; libraries without IAM-token support; third-party integrations | Per-user ACLs via access strings; rotation via Secrets Manager with a custom Lambda function; works with any client library | Requires Secrets Manager setup and a custom Lambda rotation function; longer-lived credentials than IAM tokens | **Preferred alternative** when IAM auth is impractical |
| Legacy AUTH token | Node-based clusters only; existing clusters with a single shared password | Simple to configure; supported on older engine versions | Single shared password (up to two tokens during rotation); no per-user ACLs; not available on serverless; no built-in rotation | **Never for new builds.** Migration path to RBAC only. |

## Hard Rules

- **Serverless caches**: AUTH tokens are not supported. Use IAM auth or RBAC with passwords.
- **TLS required**: IAM auth and AUTH tokens require TLS. RBAC with passwords strongly recommends TLS but does not require it on node-based clusters. Serverless caches always have TLS enabled.
- **IAM auth**: Requires Valkey 7.2+ or Redis OSS 7.0+. Requires TLS (in-transit encryption). Available on both serverless and node-based. The IAM user ID and username must be identical; if they differ, authentication will fail.
- **IAM auth cache name**: Cache names are lowercased at creation time. Authenticating code must supply the cache name in lowercase in the presigned URL, or authentication will fail.
- **Legacy AUTH token**: Node-based only. Do not recommend for new deployments.

## Decision Flowchart

1. **Is this a serverless cache?**
   - Yes: AUTH tokens are not supported. Go to step 2.
   - No: All three models are available. Go to step 2.

2. **Does the client library support IAM token generation?**
   - Yes: Use IAM auth + RBAC.
   - No: Use RBAC with passwords stored in Secrets Manager with rotation enabled.

3. **Is this an existing cluster using a legacy AUTH token?**
   - Yes: Plan migration to RBAC. Create RBAC users, then use `modify-replication-group --auth-token-update-strategy SET --auth-token <token>` to switch from AUTH-only to RBAC-compatible mode. Test RBAC users, then remove the AUTH token.
   - No: Do not configure AUTH tokens.

## Access String Examples

| Use Case | Access String | Notes |
|----------|--------------|-------|
| Full access (app) | `on ~* +@all` | All commands, all keys |
| Read-only | `on ~* +@read -@write -@admin` | No writes, no admin |
| Scoped to key prefix | `on ~app:* +@read +@write` | Only keys starting with `app:` |
| Admin disabled (default user) | `off ~* -@all` | Locks out the default user |
| Read-only on specific prefix | `on ~cache:* +@read` | Read-only, scoped keys |
