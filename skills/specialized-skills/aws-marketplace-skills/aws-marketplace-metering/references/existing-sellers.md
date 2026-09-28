## Multi-Product Architecture

> **Key Fact — Shared Infrastructure:** Multiple products MUST share a SINGLE events stack (`awsmp-events-stack`). Deploy ONE shared events stack + ONE main stack PER product (`awsmp-<productCode>-metering`). NEVER deploy separate events stacks per product.
>
> **Key Fact — Deduplication Scope:** For CA products, dedup is per (CustomerAWSAccountId + LicenseArn + dimension + hour). For legacy products, dedup is per (ProductCode + CustomerIdentifier + dimension + hour). Products sharing one Lambda will NOT interfere with each other. Each `BatchMeterUsage` call targets a single ProductCode.
>
> **Key Fact — Per-Product Routing:** When sharing a Lambda across products, route by ProductCode. Each product has its own dimensions — never mix dimensions across products in a single API call.

## Handling Existing Sellers (already deployed)

> ⚠️ **CRITICAL — CHECK BEFORE DEPLOY:** Before deploying ANY stack, you MUST first check for existing infrastructure. If an events stack already exists, DO NOT redeploy it — reuse its outputs:
>
> ```bash
> aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE --query "StackSummaries[?contains(StackName, 'awsmp-') || contains(StackName, 'aws-marketplace-events')]" --region us-east-1
> ```

### When direct deployment is allowed (visibility + existing-stack gate)

Direct deployment/stack mutation from this skill is allowed ONLY when BOTH hold:

1. **The CURRENT product is in `Limited` visibility.** Never deploy or mutate a stack for a `Published` product — for a Published product, provide the code for the seller's own pipeline/change-management instead. Because the **main stack is product-specific** (`awsmp-<productCode>-metering`), this check is on the CURRENT product's visibility ONLY — a different product's visibility is irrelevant to this product's main stack. Verify via the Catalog API before deploying.
2. **There is no existing stack for this scope** — or, if there is, deploy ONLY with the seller's EXPLICIT confirmation, and ONLY for the CURRENT product's main stack. Do NOT silently redeploy/mutate an existing stack.

⚠️ **The events stack is SHARED across all of a seller's products.** It may already be serving OTHER products — including `Published` ones with live production traffic. Mutating or redeploying it can break metering for those products. Therefore:

- Treat the events stack as **do-not-touch if it already exists**: reuse its outputs (below), never redeploy it, even when the current product is `Limited`. A `Limited` current product does NOT authorize changing shared infrastructure that other (possibly `Published`) products depend on.
- Only the FIRST product ever onboarded creates the events stack (when none exists). Any subsequent onboarding reuses it.
- Do not gate the events stack on the current product's visibility — its safety depends on whether OTHER products are already served by it, which a per-product visibility check cannot see; the safe default is to never mutate an existing shared events stack without explicit, informed seller confirmation of the blast radius.

The **main stack** deployment gate checks only the CURRENT product's visibility (`Limited`) because the main stack is dedicated to that product; a fresh main stack for a `Limited` product with no existing per-product stack is the normal direct-deploy path.

### Existing events stack detected
If `awsmp-events-stack` (or any legacy differently-named events stack a seller deployed earlier, e.g. one matching `aws-marketplace-events`) exists in us-east-1:

- **Do NOT redeploy it** — reuse it (it is SHARED and may serve other, possibly `Published`, products; redeploying risks their production traffic)
- Read its outputs: `aws cloudformation describe-stacks --stack-name <name> --query "Stacks[0].Outputs"`
- Use the `SubscribersTableName` output for the main stack

### Existing main stack detected
If `awsmp-<productCode>-metering` stack exists (this is the CURRENT product's own stack):

- **Do NOT redeploy the full stack** — modify/extend only, and only with the seller's confirmation
- **To add or rename a pricing dimension:** update the AWS Marketplace listing (AMMP) — that's it. The metering pipeline is **not** configured with a dimension list, so there is **nothing to change in the stack or the Lambdas** and **no redeploy** for a dimension change. Once the seller's writer starts emitting usage rows for the new dimension, the pipeline aggregates and submits them, and `BatchMeterUsage` accepts them as soon as the catalog defines the dimension (until then it fails with a request-level `InvalidUsageDimensionException`, which is isolated + alarmed).
  > This is a change from earlier versions, which baked a `DIMENSIONS` env var into the Meter Lambda and required an env-var update per dimension change. That coupling has been removed — dimension validity is server-authoritative.

### Partial stack (events deployed, main missing)

- ⚠️ The events stack ALREADY EXISTS — DO NOT deploy it again
- Run: `aws cloudformation describe-stacks --stack-name awsmp-events-stack --region us-east-1 --query "Stacks[0].Outputs"` to get SubscribersTableName
- Deploy ONLY the main stack using the existing SubscribersTableName
- If you redeploy events, you will create a DUPLICATE and break the integration

### Adding a new capability to an EXISTING stack (adapt — do NOT impose the packaged shape)

When a seller already has a working stack, the capabilities this skill adds are **layered onto their ACTUAL resources**, never assumed to already match the packaged files. First understand the seller's real subscribers table, register Lambda/API, and metering path (see "Handling Existing Sellers" above), then:

- **Buyer PII / registration data (in-region `customer-profile` table).** The seller's existing register handler may ALREADY store registration data — in its own table, a column, or on the subscriber row. Do NOT assume the packaged `register.py` / `CUSTOMER_PROFILE_TABLE` shape is present, and do NOT drop the seller's existing handler in verbatim (the reference `register.py` fails loud if `CUSTOMER_PROFILE_TABLE` is unset — that guard is for a NEW skill-generated stack only).
  - If the seller's subscribers table **already holds buyer PII** (e.g. a `registrationData` attribute) and they want it moved in-region, this is a **data migration + code cutover**, not a drop-in: provision the new per-Region profile table, dual-write or backfill existing rows, then stop writing PII to the subscribers row. Make each step explicit; never silently drop the existing PII attribute or assume the table is already PII-free.
  - If the seller is happy with their current arrangement, respect it and only explain the data-residency tradeoff (keeping buyer PII out of the shared us-east-1 table).

- **Expedited deprovisioning flush (sparse index + flush rule + deprovision-work queue + cleanup Lambda).** These are additive — the sparse GSI is an online index (no data migration). But add them against the seller's ACTUAL subscribers-table name and their existing discoverer/submitter function names/roles (merge IAM + env vars, do not overwrite). If the seller's pipeline already finalizes deprovisioning some other way, reconcile with it rather than blindly layering the cleanup Lambda on top.

In all cases confirm the change set with the seller first, and apply the edits to the seller's OWN materialized files (code/stack parity) rather than the packaged assets.
