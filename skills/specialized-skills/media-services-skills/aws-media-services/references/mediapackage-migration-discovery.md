# Discovery Workflow

Enumerate all MediaPackage v1 Live channels and origin endpoints in the user's AWS account. Save results to `.mediapackage-migration/v1-resource-inventory.json`.

> **V1 SAFETY:** Only these commands are permitted for v1:
>
> - `aws mediapackage list-channels`
> - `aws mediapackage describe-channel`
> - `aws mediapackage list-origin-endpoints`
> - `aws mediapackage describe-origin-endpoint`
>
> NEVER use `create-*`, `update-*`, or `delete-*` on v1 resources.

---

## Contents

- [Step 1: Scope](#step-1-scope)
- [Step 2: Enumerate Channels](#step-2-enumerate-channels)
- [Step 3: Enumerate Origin Endpoints](#step-3-enumerate-origin-endpoints)
- [Step 4: Save Inventory](#step-4-save-inventory)
- [Step 5: Present Summary](#step-5-present-summary)
- [Step 6: Resource Selection](#step-6-resource-selection)
- [Step 7: Hand Off](#step-7-hand-off)

---

## Step 1: Scope

Use the target region(s) the user confirmed during onboarding. Optionally, if your environment can write files, create an `.mediapackage-migration/` working directory to hold the inventory and plan artifacts; otherwise keep them in conversation context.

**Record the region decision explicitly, including the regions you are NOT migrating.**
If the user has v1 resources in `us-west-2` and `us-east-1` and only wants
`us-west-2` migrated, the inventory must say that `us-east-1` was **deliberately
excluded** — not simply omit it. A plan that is silent about a region cannot be audited
or resumed: a later reader can't tell "left alone on purpose" from "never looked".

Do the same for channels you skip. If you exclude scratch or test channels because
they look disposable, name them and say why.

---

## Step 2: Enumerate Channels

For each target region:

```
aws mediapackage list-channels --region <region>
```

### Pagination

If the response contains `NextToken`, continue fetching:

```
aws mediapackage list-channels --region <region> --next-token <token>
```

Repeat until `NextToken` is absent. Aggregate all channels across pages.

### For Each Channel

Run:

```
aws mediapackage describe-channel --id <channel-id> --region <region>
```

Record: `id`, `arn`, `description`, `tags`, `hlsIngest.ingestEndpoints`.

---

## Step 3: Enumerate Origin Endpoints

For each discovered channel:

```
aws mediapackage list-origin-endpoints --channel-id <channel-id> --region <region>
```

Handle pagination the same way (check `NextToken`).

### For Each Origin Endpoint

Run:

```
aws mediapackage describe-origin-endpoint --id <endpoint-id> --region <region>
```

Record the full response. Classify the endpoint type based on which packaging field is present:

| Field Present | Endpoint Type |
|---|---|
| `hlsPackage` | HLS |
| `dashPackage` | DASH |
| `cmafPackage` | CMAF |
| `mssPackage` | MSS |

### Capture the access-control fields explicitly

v1 has no policy APIs — access control lives in three **endpoint fields**, and all
three need v2 replacements that are easy to miss because there is nothing named
"policy" to look for. Pull them out of the response and record them per endpoint
rather than leaving them buried in `fullConfig`:

| V1 field | Why it matters |
|---|---|
| `Whitelist` | IP allow-list. v2 has no endpoint field for this — it becomes an endpoint policy condition |
| `Authorization` | CDN auth (`CdnIdentifierSecret`, `SecretsRoleArn`). v2 needs a new secret key name, a role trust change, extra IAM permissions, and a CDN header rename |
| `Origination` | `DENY` has no v2 equivalent at all |

Also capture `ManifestName` (v1's endpoint-level manifest name) — v2's charset is
stricter, so names with `_` or `.` will need rewriting.

Report what you found: "3 endpoints use CDN authorization, 2 have IP allow-lists, 1 has
`Origination: DENY`". If none of them use any access control, say that explicitly too
— because a v2 endpoint with no policy is **not** publicly reachable, so even a
wide-open v1 endpoint needs a deliberate v2 policy decision.

---

## Step 4: Save Inventory

Write results to `.mediapackage-migration/v1-resource-inventory.json`:

```json
{
  "discoveredAt": "<ISO-timestamp>",
  "regions": ["us-east-1"],
  "regionsExcluded": [
    { "region": "us-west-2", "reason": "user scoped migration to us-east-1 only" }
  ],
  "channels": [
    {
      "id": "my-channel",
      "arn": "arn:aws:mediapackage:...",
      "region": "us-east-1",
      "included": true,
      "description": "...",
      "tags": {},
      "ingestEndpoints": [...],
      "originEndpoints": [
        {
          "id": "my-endpoint",
          "arn": "arn:aws:mediapackage:...",
          "type": "HLS",
          "manifestName": "index",
          "startoverWindowSeconds": 0,
          "timeDelaySeconds": 0,
          "origination": "ALLOW",
          "ipAllowList": [],
          "authorization": null,
          "url": "https://...",
          "fullConfig": { ... }
        }
      ]
    }
  ],
  "summary": {
    "totalChannels": 0,
    "totalEndpoints": 0,
    "endpointsByType": {
      "HLS": 0,
      "DASH": 0,
      "CMAF": 0,
      "MSS": 0
    },
    "channelsWithZeroEndpoints": [],
    "endpointsWithEncryption": 0,
    "endpointsWithCdnAuth": 0,
    "endpointsWithIpAllowList": 0,
    "endpointsWithOriginationDeny": 0
  }
}
```

Store the **full** `describe-origin-endpoint` response in `fullConfig` — this is needed later for endpoint configuration planning.
It includes access-control configuration (allow-lists, CDN authorization secret and
role ARNs, SPEKE role ARNs). If you write the inventory to disk, follow the handling
rules under "State and artifacts" in
`references/workflow-mediapackage-migration.md`: no source
control, restricted access, encrypted storage, delete when done.

---

## Step 5: Present Summary

Present the discovery results conversationally:

1. **Total channels** found across all regions
2. **Total origin endpoints** and breakdown by type (HLS, DASH, CMAF, MSS)
3. **Channels with zero endpoints** (potential orphans — ask if they should be included)
4. **Notable patterns** — look for naming conventions, common tags, environment indicators (prod/staging/dev), content type patterns (sports, news, etc.)
5. **Encryption** — note how many endpoints use encryption

Example:
> I found **12 channels** with **28 origin endpoints** in us-east-1:
>
> - 15 HLS endpoints
> - 8 DASH endpoints
> - 3 CMAF endpoints
> - 2 MSS endpoints
>
> I noticed several channels have "prod-" prefixes and "sports" tags — this might help with channel group planning.
>
> 1 channel ("test-channel") has zero endpoints.

---

## Step 6: Resource Selection

After presenting the summary, ask the user whether they want to migrate everything or a subset:

> Would you like to migrate **all** of these resources, or would you like to **select a subset**?

### If "all"

Mark all channels as included. Proceed to Step 7. Update `.mediapackage-migration/v1-resource-inventory.json` — set `included: true` on every channel.

### If "subset"

Present the channel list and let the user pick:

> Here are your channels. Tell me which ones to include (by name, number, or pattern):
>
> 1. example-sports-football (3 endpoints: HLS, DASH, CMAF)
> 2. example-sports-basketball (2 endpoints: HLS, DASH)
> 3. staging-test-1 (1 endpoint: HLS)
> ...
>
> You can say things like:
>
> - "Include 1, 2, and 5"
> - "Include all prod-* channels"
> - "Exclude staging channels"
> - "Only the ones tagged Environment=production"

After selection, confirm:

> You've selected **8 of 12 channels** (22 of 28 endpoints) for migration. The excluded channels will not be touched. Does this look right?

Update `.mediapackage-migration/v1-resource-inventory.json` — add an `included: true/false` field to each channel. Only included channels proceed to channel group planning.

---

## Step 7: Hand Off

Tell the user: "Discovery is complete. Ready to plan channel groups? You can say 'plan channel groups' to continue."
