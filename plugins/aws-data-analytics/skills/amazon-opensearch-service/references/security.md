# Security — Amazon OpenSearch controls

Every assessment / recommendation MUST include a Security section that confirms each control below.

## Three security layers

```
[Network] → [Domain Access Policy] → [Fine-Grained Access Control (FGAC)]
```

### 1. Network

| Pattern | When |
|---|---|
| **VPC + Interface VPC endpoint** | Production. Private connectivity from your VPC to AOS. |
| **VPC + ENI** (older pattern) | Production legacy. ENI in VPC subnets. |
| **Public endpoint + IAM** | Dev/test, or when external SaaS integration requires public access |
| **Public endpoint + IP allowlist** | Tightening public — pair with Domain Access Policy IP filter |

VPC ↔ AOS endpoint traffic is regional; cross-AZ data transfer within an AOS cluster is FREE.

### 2. Domain Access Policy (resource-based)

JSON policy on the domain itself. Controls which IAM principals can call `https://<domain>/*`. Cluster-level coarse grain.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "AWS": "arn:aws:iam::<account>:role/<app-role>" },
      "Action": "es:ESHttp*",
      "Resource": "arn:aws:es:<region>:<account>:domain/<domain-name>/*"
    }
  ]
}
```

### 3. Fine-Grained Access Control (FGAC)

Adds **document-level / field-level / role-based** authorization on top.

**Requirements** (once enabled, **cannot be disabled**):

- OpenSearch / Elasticsearch 6.7+
- HTTPS enforced
- Encryption at rest enabled
- Node-to-node encryption enabled

**Master user** is either:

- An **IAM principal** (signed Sig v4 requests) — no password
- A **username/password in the internal user database**

The master user is automatically mapped to `all_access` and `security_manager` roles.

### IAM master vs internal user database

| | IAM master user | Internal user master |
|---|---|---|
| **Authentication** | Sig v4 signed requests | HTTP basic auth (username/password) |
| **Authorization** | FGAC roles (NOT IAM permissions) | FGAC roles |
| **Best for** | App-to-AOS integrations | Human users, dashboards, simple setups |
| **Password rotation** | N/A (use IAM role rotation) | AOS API or dashboards |

**IAM master gotcha:** IAM is just authentication. Authorization is by FGAC permissions, NOT IAM permissions.

## FGAC built-in roles

| Role | Use |
|---|---|
| `all_access` | Master user; do not assign to humans |
| `security_manager` | Manage internal users + roles |
| `kibana_user` / `dashboards_user` | Read-only Dashboards access |
| `readall` | Read all indexes |
| `manage_snapshots` | Create/restore snapshots |
| `ultrawarm_manager` | Manage UltraWarm migrations (AWS-only role) |
| `cold_manager` | Manage Cold storage migrations (AWS-only role) |
| `ml_full_access` | Manage ML Commons models (AWS-only role) |
| `notifications_full_access` / `notifications_read_access` | Notification destinations |

**AWS does NOT offer:** `observability_full_access`, `observability_read_access`, `reports_read_access`, `reports_full_access` (these are upstream-only roles).

## Custom FGAC role example

```json
PUT _plugins/_security/api/roles/app-readonly
{
  "cluster_permissions": ["cluster_composite_ops_ro"],
  "index_permissions": [{
    "index_patterns": ["app-*"],
    "allowed_actions": ["read"],
    "fls": ["~secret_field"],
    "masked_fields": ["pii_email"],
    "dls": "{ \"term\": { \"tenant_id\": \"${attr.internal.tenant}\" } }"
  }],
  "tenant_permissions": [{
    "tenant_patterns": ["app_tenant"],
    "allowed_actions": ["kibana_all_read"]
  }]
}
```

- **DLS** (Document-Level Security): query that filters which docs the role can see
- **FLS** (Field-Level Security): which fields are visible (`~field` excludes; `field` includes)
- **Field masking**: hash or pattern-mask field values

## Authentication backends (FGAC)

OpenSearch FGAC supports multiple backends:

| Backend | When |
|---|---|
| **Internal user database** | Simple setups; AOS-stored usernames + bcrypt passwords |
| **IAM SigV4** | App-to-AOS; AWS principals only |
| **SAML** | Enterprise SSO; map SAML attributes to FGAC roles |
| **OpenID Connect** | Modern SSO; OIDC providers like Auth0, Keycloak, Okta |
| **LDAP / Active Directory** | On-prem or hybrid AD setups |
| **Cognito** | AWS-native user pool with SAML/OIDC federation |
| **Anonymous** | Public read-only data; rare |

### Common pattern: Cognito + FGAC

1. Create Cognito user pool + identity pool
2. Configure AOS domain to use Cognito for OpenSearch Dashboards
3. Map Cognito groups to FGAC backend roles
4. Users sign in via Dashboards; Cognito hands off to FGAC for authorization

## Encryption

| Control | Default | Notes |
|---|---|---|
| **At-rest encryption** | ON for new domains | KMS-managed (AWS-managed key by default; can use customer-managed CMK) |
| **Node-to-node encryption** | ON when FGAC enabled | TLS between cluster nodes |
| **In-transit (HTTPS)** | TLS 1.2+ mandatory; TLS 1.3 supported | |
| **Custom HTTPS** | Optional ACM cert | For VPC clusters with custom domain |

**Customer-managed KMS** gives you key rotation control + audit. Use when compliance requires it.

## Audit logs

Two log types pushed to CloudWatch Logs:

| Log type | What |
|---|---|
| **Audit logs** | Authentication / authorization events, query logs (configurable) |
| **Slow logs** | Slow queries / indexing operations |
| **Index slow logs** | Slow indexing |
| **Search slow logs** | Slow searches |
| **Application logs** | Errors, warnings |

Audit log levels: `BASIC`, `EXTERNAL_ONLY` (no internal API calls), `READ_AND_WRITE` (verbose).

CloudWatch Logs charges apply (storage + ingestion). Use selective log enablement, not all-on.

## Compliance

Amazon OpenSearch Service is in scope for (verify current per-service status):

- HIPAA (with BAA)
- PCI DSS
- SOC 1 / 2 / 3
- ISO 27001 / 27017 / 27018
- FedRAMP Moderate (commercial regions) / High (GovCloud)
- IRAP, Cyber Essentials Plus, ENS High, SecNumCloud, MTCS, GxP

**Always verify the latest compliance status at `https://aws.amazon.com/compliance/services-in-scope/`** before attesting in a customer report.

## Network architecture patterns

### Pattern A: Private domain (production)

```
[App in VPC subnet] ─→ [VPC Interface Endpoint] ─→ [AOS domain in private subnet]
```

- AOS deployed with VPC endpoint
- App accesses via VPC private DNS
- Cross-AZ data transfer inside AOS is FREE

### Pattern B: Public domain + IAM (lighter footprint)

```
[App] ──signed-Sig-v4──→ [AOS public endpoint]
```

- AOS in public DNS
- IAM Sig v4 signed requests
- Apply IP allowlist via Domain Access Policy for additional defense

### Pattern C: Public domain + FGAC for humans

```
[Human user] ─→ [Cognito] ─→ [Dashboards] ─→ [AOS public]
```

- Cognito user pool + identity pool
- AOS configured for Cognito
- FGAC roles mapped to Cognito groups

## Security checklist for assessment reports

```
- [ ] Network: VPC vs Public clearly stated; rationale documented
- [ ] FGAC enabled; master user pattern documented
- [ ] Encryption at rest: AWS-managed or CMK chosen
- [ ] Node-to-node encryption: ON
- [ ] HTTPS: enforced; minimum TLS 1.2
- [ ] Audit logs: scope chosen, retention documented
- [ ] Slow logs: selective enablement (not all indexes)
- [ ] DLS / FLS / field masking: applied where multi-tenancy exists
- [ ] Backend role mapping: SAML/Cognito/OIDC group attribution documented
- [ ] Master user: NEVER an IAM principal in production app paths (use scoped role instead)
- [ ] Compliance: checked against latest aws.amazon.com/compliance/services-in-scope/
- [ ] Snapshots: appropriate destination + retention; no manual snapshots without S3 cost note
- [ ] No credentials, master usernames, or VPC endpoint URLs in the report
```

## Data privacy / sensitive data

- **PII** in indexed documents: use FLS or field masking. For HIPAA workloads, also consider tokenization at ingest.
- **Search logs** can leak sensitive query terms — disable search request logging when PII may appear in queries.
- **Slow logs** can leak query content — pair with restrictive CloudWatch IAM.
- **Snapshot encryption**: manual snapshots inherit S3 bucket encryption. Use SSE-KMS with CMK for compliance.

## Threat model headlines

1. **Public domain + open Domain Access Policy = data exposed.** Always pair public endpoints with IAM signing or FGAC + IP allowlist.
2. **FGAC misconfiguration** (e.g., IAM master with overly broad policy) gives unintended access.
3. **Pre-FGAC domains** can have IAM-only auth without document/field controls — risky for multi-tenant data.
4. **Snapshot bucket** in your account: if its bucket policy is too permissive, snapshots are exfiltrable.
5. **CloudWatch Logs** for audit/slow logs — restrict who can read them.
6. **Master user password** if internal user database — store in Secrets Manager, rotate regularly.

## What this skill MUST NOT do

- **Embed credentials, master usernames, VPC endpoint URLs, or KMS key ARNs in generated reports.** They propagate to chat logs and may end up in unapproved repos.
- **Recommend disabling FGAC.** Once enabled it cannot be disabled — the right answer is rebuild domain, not "turn off security".
- **Recommend `cluster.routing.allocation.disk.threshold_enabled: false`** as a fix for read-only clusters. The right answer is more storage / smaller shards / move data, NOT disabling watermarks.
- **Recommend public domains for production** without explicit IAM + FGAC + IP allowlist.
