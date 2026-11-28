# DataZone API fallback

Use these calls when the usage tables aren't reachable or don't carry the category. They return current state only. For what changed, when, or what was deleted, say that only the usage tables have it.

Pass the domain's Region with `--region`. The AWS CLI follows `nextToken` for you on every list call below. In boto3, use the client's paginator (`get_paginator("<operation>")`).

## Rules that decide whether the answer is right

- **Page everything.** A single page of a domain-wide list is not the domain.
- **Key counts by listing id, not name.** Two listings can share a name. Carry the name only for display, and when tied listings share a name, tell them apart by owning project.
- **Status filters are not optional.** `ListSubscriptions` returns only APPROVED subscriptions unless you pass `--status`. `ListSubscriptionRequests` returns only PENDING requests unless you pass `--status`. Without the right status, accepted or rejected requests are invisible and a busy domain looks like it has none.
- **Both list calls need a scope filter.** Without one of `--subscribed-listing-id`, `--owning-project-id`, `--approver-project-id` or an owning principal, they fail with `Missing required filters`. Scope by listing or by the producer project (`--approver-project-id`).
- **Don't use grants as a proxy.** `ListSubscriptionGrants` returns grants only for consumers that have an environment. A consumer project without one has approved subscriptions and no grants.
- **Don't answer a request question with subscriptions, or the reverse.** "Most subscribed" counts APPROVED subscriptions. "Most requested" counts requests created in the window, in any status.
- **Compare timestamps as UTC.** The CLI prints ISO 8601 timestamps with an offset; parse them before comparing with a cutoff.

## Projects

```bash
aws datazone list-projects --domain-identifier <DOMAIN_ID> --region <REGION> \
  --query "items[].{id:id,name:name,status:projectStatus,createdAt:createdAt,domainUnitId:domainUnitId}"
```

- Active projects: count `projectStatus == ACTIVE`. Older projects can come back with no `projectStatus`; count them separately and tell the user, rather than assuming a status.
- Created in the last N days: ACTIVE projects whose `createdAt` is at or after the cutoff.

## Published listings

A `SearchListings` item has no top-level `id` or `name`: read them from `assetListing`. The asset type in `entityType` can carry a namespace prefix (for example `amazon.datazone.GlueTableAssetType`), so match on a substring.

```bash
aws datazone search-listings --domain-identifier <DOMAIN_ID> --region <REGION> \
  --query "items[?assetListing && contains(assetListing.entityType || '', 'GlueTable')].assetListing.{listingId:listingId,name:name,owningProjectId:owningProjectId}"
```

## Most-subscribed listings (current subscriptions)

For each listing, count its APPROVED subscriptions. Report REVOKED separately only if asked; never add it to the count.

```bash
aws datazone list-subscriptions --domain-identifier <DOMAIN_ID> --region <REGION> \
  --subscribed-listing-id <LISTING_ID> --status APPROVED --query "length(items)"
```

## Most-requested listings in a window (subscription requests)

Query each producer project as approver, once per status, keep requests created in the window, and count each listing a request names. Deduplicate by request `id`, because a request can match more than one query. One call:

```bash
aws datazone list-subscription-requests --domain-identifier <DOMAIN_ID> --region <REGION> \
  --approver-project-id <PRODUCER_PROJECT_ID> --status ACCEPTED \
  --query "items[].{id:id,createdAt:createdAt,listings:subscribedListings[].{id:id,name:name}}"
```

The full loop is easier in boto3:

```python
import datetime
import boto3

dz = boto3.client("datazone", region_name=REGION)

def items(operation, **params):
    """Every item of a DataZone list call in this domain."""
    for page in dz.get_paginator(operation).paginate(domainIdentifier=DOMAIN_ID, **params):
        yield from page.get("items", [])

since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=DAYS)  # 7, 14 or 30
listings = [i["assetListing"] for i in items("search_listings") if "assetListing" in i]
glue = {l["listingId"]: l for l in listings if "GlueTable" in (l.get("entityType") or "")}
producers = {l["owningProjectId"] for l in glue.values() if l.get("owningProjectId")}

seen, counts = set(), {}  # listingId -> (name, requests created in the window)
for approver in producers:
    for status in ("PENDING", "ACCEPTED", "REJECTED"):
        for req in items("list_subscription_requests", approverProjectId=approver, status=status):
            if req["id"] in seen or req["createdAt"] < since:
                continue
            seen.add(req["id"])
            for sl in req.get("subscribedListings", []):
                if sl.get("id") in glue:
                    name, n = counts.get(sl["id"], (sl.get("name"), 0))
                    counts[sl["id"]] = (name, n + 1)
```

If no producer project is known, loop `approverProjectId` over every project from `list_projects`. boto3 returns `createdAt` as a timezone-aware `datetime`, so it compares directly with `since`.

## Other categories

- **Members, environments, connections and notebooks are listed per project.** For a domain-wide answer, list the projects first and query each one:
  - `aws datazone list-project-memberships --domain-identifier <DOMAIN_ID> --project-identifier <PROJECT_ID>`
  - `aws datazone list-environments --domain-identifier <DOMAIN_ID> --project-identifier <PROJECT_ID>`
  - `aws datazone list-connections --domain-identifier <DOMAIN_ID> --project-identifier <PROJECT_ID>`
  - `aws datazone list-notebooks --domain-identifier <DOMAIN_ID> --owning-project-identifier <PROJECT_ID>`
- **Domain units are a tree.** Get the root with `aws datazone get-domain --identifier <DOMAIN_ID> --query rootDomainUnitId`, then walk `aws datazone list-domain-units-for-parent --domain-identifier <DOMAIN_ID> --parent-domain-unit-identifier <UNIT_ID>` for each level, or you count only one level. Some older domains return no `rootDomainUnitId`; there is no tree to walk for them.
- **Project profiles and blueprints** are domain-wide, but each list answers a different question:
  - `aws datazone list-project-profiles --domain-identifier <DOMAIN_ID>` can leave out profiles that the PROJECT_PROFILE rows include, so say which source you used.
  - The blueprints enabled in the domain (what ENVIRONMENT_BLUEPRINT rows hold) come from `aws datazone list-environment-blueprint-configurations --domain-identifier <DOMAIN_ID>`.
  - `aws datazone list-environment-blueprints --domain-identifier <DOMAIN_ID>` returns only custom blueprints; add `--managed` for the AWS-managed catalogue.
- **User profiles:** `aws datazone search-user-profiles --domain-identifier <DOMAIN_ID> --user-type DATAZONE_USER` returns the domain's user profiles. Report counts unless the user asks about specific people.
