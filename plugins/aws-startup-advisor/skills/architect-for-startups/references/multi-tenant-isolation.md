# Multi-Tenant Isolation on AWS

Tenant isolation is the architectural decision a SaaS startup is least able to reverse and most likely to get wrong under time pressure. Getting it wrong produces either a cross-tenant data leak, which is an existential incident for a company selling to businesses, or a per-tenant cost floor that makes the unit economics never work.

The mistake is treating it as one decision. It is a decision **per layer**, and the layers can differ.

## Choose a model per layer, not per application

| Model      | What it means                                    | Isolation                                | Cost per tenant             | Where it fits                                                               |
| ---------- | ------------------------------------------------ | ---------------------------------------- | --------------------------- | --------------------------------------------------------------------------- |
| **Silo**   | Dedicated resource per tenant                    | Strongest, enforced by resource boundary | Highest, floors multiply    | Regulated or contractual isolation, or one customer large enough to fund it |
| **Pool**   | Shared resource, logical separation              | Weakest, depends on your correctness     | Lowest, marginal per tenant | Default for most tenants, especially self-serve                             |
| **Bridge** | Shared infrastructure, dedicated slice inside it | Middle, enforced by partition            | Low to medium               | Pooled compute with per-tenant schema or table                              |

Pick per layer. A common and correct shape: pooled compute, bridge-model database (schema or partition key per tenant), siloed only for the customer whose contract requires it.

**The trap.** Going full silo because it is easier to reason about, then discovering the fixed floors multiply by tenant count. Each dedicated Aurora Serverless v2 cluster carries a floor around 0.5 ACU whether or not the tenant is active. Each OpenSearch Serverless collection carries a substantial monthly minimum. Ten silo tenants on floored services is a large bill for near-zero usage. Verify current minimums with the `aws-billing-and-cost-management` skill in `aws-core` before committing to a silo model, since these change.

**The other trap.** Going full pool and enforcing isolation with a `WHERE tenant_id = ?` clause in application code. That makes every future query a potential cross-tenant leak, and the blast radius of one missing predicate is every customer.

## Enforce isolation below the application, not inside it

If a developer can write a query that returns another tenant's rows, isolation is a code-review problem forever. Push enforcement into a layer that fails closed.

**Dynamic session policies.** Have the request path assume a role with a scoped-down session policy carrying the tenant identifier, so the credentials themselves cannot reach another tenant's data. The `aws-iam` skill in `aws-core` covers `AssumeRole` and policy authoring mechanics; what matters here is the pattern:

- Derive the tenant identifier from a verified token claim, never from a request header, path parameter, or body field that a client controls.
- Scope with IAM policy conditions on the resource path (leading keys for DynamoDB, key prefixes for S3), so authorization is evaluated by IAM rather than by your code.
- Cache assumed credentials per tenant for the session lifetime. Assuming a role on every request adds latency and hits API limits.

**Database-layer enforcement.** For Postgres, row-level security with a session variable set from the verified tenant context means a forgotten predicate returns zero rows instead of another tenant's data. That is the correct failure direction. For DynamoDB, put the tenant identifier in the partition key and use IAM leading-key conditions.

**Test the negative case.** An isolation test that only asserts a tenant sees their own data proves nothing. Assert that tenant A's credentials, used against tenant B's identifier, are **denied**. That test is the isolation guarantee. Without it you have an intention.

## Data partitioning by store

- **DynamoDB.** Tenant identifier as partition key, or as the leading component of a composite key. Enables IAM leading-key conditions, which is the main reason to prefer it. Watch for a hot partition when one tenant is far larger than the rest.
- **Postgres or Aurora.** Schema per tenant (bridge) reads cleanly and backs up per tenant, but connection and migration overhead grows with tenant count, and thousands of schemas becomes an operations problem. Shared tables with row-level security scale further with less per-tenant overhead. Pick based on expected tenant count and whether per-tenant restore is a requirement.
- **S3.** Prefix per tenant with IAM conditions on the prefix. Bucket per tenant hits account bucket limits and is rarely worth it.
- **Search and vector stores.** Check the per-collection or per-index floor before choosing silo. This is the layer where silo cost most often surprises teams.

## Noisy neighbors

Pooled compute means one tenant's load degrades everyone. Before it happens:

- Rate-limit per tenant, not just globally. A global limit lets one tenant consume the whole budget.
- Keep a bulkhead so one tenant's backlog cannot exhaust shared capacity: separate queues or partitioned concurrency for heavy asynchronous work.
- Know which tenant caused a spike. Emit the tenant identifier as a dimension on your metrics, or attribution after the fact is guesswork.

## Per-tenant cost attribution

"Which customers are unprofitable" is unanswerable later if you do not instrument it now, and it is the question that decides pricing.

- Tag siloed resources with the tenant identifier for cost allocation.
- Pooled resources cannot be split by tags. Attribute with a usage proxy you already emit (requests, storage bytes, compute milliseconds, tokens) and apportion the shared bill against it.
- Emit that proxy from day one. Retrofitting per-tenant usage data across a pooled fleet is painful and often approximate.

## When a large customer demands dedicated infrastructure

This is the startup's problem, not the customer's: a prospect big enough to change the
runway has asked for something the architecture does not do yet, and the deal is
waiting on the answer. It arrives as a sales requirement rather than a technical one,
usually mid-deal, so the answer should already exist before it is asked.

- If the contract requires physical isolation, silo that tenant only. Do not migrate the whole platform to silo for one customer.
- A separate AWS account per siloed tenant gives the hardest boundary and the cleanest cost attribution, at the price of account management. See `Skill("aws-core:aws-iam")` for cross-account patterns.
- Keep one deployment pipeline across both models. Two divergent architectures is the outcome that actually hurts, because every future change ships twice.
- Price it against the real floor, including the fixed monthly minimums that exist at zero usage.

## Upstream skills to defer to

Do not restate the mechanics these own. Invoke them directly, and spend the reasoning on the tenancy decision. The `aws-core:` skills ship in the separate `aws-core` plugin. If it is not installed, tell the user, recommend installing it, and continue with the steps that do not depend on it. Do not reproduce its content from memory.

- **`Skill("aws-core:aws-iam")`**: IAM roles, `AssumeRole`, session policies, and policy conditions.
- **`Skill("aws-core:aws-database")`**: DynamoDB key design, Aurora and Postgres specifics.
- **`Skill("aws-core:aws-compute")`**: Compute capacity and scaling.
- **`Skill("aws-core:aws-serverless")`**: Per-function concurrency and partitioning.
- **`Skill("aws-core:aws-messaging-and-streaming")`**: Queue isolation and per-tenant bulkheads.
- **`Skill("aws-core:aws-observability")`**: Metric dimensions and per-tenant attribution.
- **`Skill("aws-core:aws-billing-and-cost-management")`**: Cost floors, minimums, and allocation tags.

## Anti-patterns

- Isolation enforced only by an application-layer predicate, with no IAM or database boundary behind it.
- Tenant identity taken from a client-controlled header, path, or body field rather than a verified token claim.
- Isolation tests that assert only the positive case and never that cross-tenant access is denied.
- Choosing silo for every tenant without adding up the fixed floors at zero usage.
- One tenancy model imposed on every layer because it is simpler to describe.
- Adding the tenant dimension to metrics after the first noisy-neighbor incident.
- A second architecture forked for one large customer, then maintained in parallel forever.
