# Access model detection: is the subscription workflow what governs this?

Three questions, in this order, before any grant or revoke. All three are cheap
and none of them writes.

1. **Does this account use the SageMaker Catalog?**
2. **Which project am I acting as?** Resolvable from your own identity. Not a
   question for the user.
3. **Is the thing the user named a published listing?** Because a subscription
   is over a listing, not over a table.

## 1. The platform probe

```bash
aws sts get-caller-identity
aws datazone list-domains --region <region> \
  --query 'items[].{id:id,name:name,status:status}'
```

| What you see | Conclusion |
|---|---|
| one or more domains | **SageMaker Catalog.** This skill applies. Work in that domain |
| several domains | resolve which one holds the listing before acting; do not guess |
| an empty list, and the call succeeded | there is genuinely no domain in this region. No subscription workflow here; see "What this skill does not handle" |
| `AccessDeniedException` | *this caller cannot see a domain.* **Not** an absence. Say which call was denied and what you tried next |

**A denial is only evidence if the call named a region.** The rows above assume
`--region` was supplied. A role may carry a region restriction, which an
`aws:RequestedRegion` condition makes common in an AWS Organization, so a call
that omits the region can be refused for reaching the wrong region rather than
for anything about the domain. If you are denied and you did not name a region,
add it and probe again before concluding; do not fall back to an unqualified
retry. Only a denial on a region-qualified call means what the table says.

**The vocabulary is the trap, not the API.** "Listing", "subscription",
"consumer project" and "grant" are AWS Marketplace, AWS Data Exchange, AWS RAM and
non-AWS data-exchange words too. Measured on unaided runs: an agent asked to
request access to a listing reported that its role lacked
`aws-marketplace:SearchListings`; another answered with a Marketplace Management
Portal click-path; another said "sales listings" and "consumer project" were not
AWS concepts and asked which platform was meant. In every case the account had a
DataZone domain one call away.

So: run the probe **first**, and if it returns a domain, the request is about that
domain. You MUST NOT report a permission for a different service as the blocker,
and you MUST NOT ask the user which product they meant when one call answers it.

## 2. Resolving "my project"

"My project", "our team's project" and "the project that owns this" are all
resolvable from the caller's identity in three calls. **Do not stop and ask.** A
stall here costs the user the whole task, and it is the most reproduced failure in
this family of skills.

```bash
DOMAIN=<domain-id>

# 1. who am I -- take the ROLE NAME out of the ARN, not the whole ARN
aws sts get-caller-identity --query Arn --output text

# 2. role name -> DataZone user profile id
PROFILE=$(aws datazone search-user-profiles --domain-identifier "$DOMAIN" \
  --user-type DATAZONE_IAM_USER --search-text "<role-name>" \
  --query 'items[0].id' --output text)

# 3. profile id -> the projects that principal belongs to
aws datazone list-projects --domain-identifier "$DOMAIN" \
  --user-identifier "$PROFILE" --query 'items[].{id:id,name:name}'
```

Two traps in that chain, both measured:

- **`get-user-profile` on your own role ARN is refused** (`Failed to validate IAM
  role`) and on the bare role name it is a not-found. `search-user-profiles` is the
  call that works.
- **Passing the role ARN straight to `list-projects --user-identifier` returns an
  empty list rather than an error**, which reads as "no projects". Pass the profile
  id.

If the principal belongs to exactly one project, use it and say which. If it
belongs to more than one, cross-check with
`list-project-memberships --project-identifier <p>` and pick the one whose role
fits the task: the project that **owns the listing** for a producer-side task,
the project that will **hold the access** for a consumer-side one. Name your
choice in the answer. Ask only if two candidates genuinely both fit.

## 3. Is it a published listing?

A subscription is over a **listing**. An asset sitting in a project's inventory
that has never been published has no listing, so there is nothing to subscribe to
and nothing to grant.

```bash
aws datazone search-listings --domain-identifier "$DOMAIN" \
  --search-text "<asset or table name>" \
  --query 'items[].assetListing.{listing:listingId,name:name,asset:entityId}'

aws datazone get-listing --domain-identifier "$DOMAIN" --identifier <listing-id> \
  --query '{status:status,revision:listingRevision,asset:item.assetListing.assetId}'
```

- `status: ACTIVE`: subscribable. Use the **listing id**, not the asset id, in
  every subscription call.
- `status: INACTIVE`: the listing was unpublished. It is still readable, so
  "does it resolve" is not the question; the status is. Consumers cannot subscribe
  to it.
- **No listing found**: the asset exists but is not published, or the name is a
  table rather than a catalog asset. Publishing it is
  `managing-data-catalog`'s job. Say that rather than trying to create access over
  something with no listing.

The search index lags a publish by seconds, so a listing published moments ago may
not appear in `search-listings` yet. Read it with `get-listing` if you have the id.

## The mechanism, in one paragraph

Access to a catalog asset is granted **only** through a subscription over a
published listing: the consuming project files a request and the producing project
approves it, or the producer files that request on the consumer's behalf and it
auto-approves. Everything else you might be tempted to edit (Lake Formation
permissions, S3 bucket policies, the Glue catalog's resource policy, the IAM
policies on a project's environment roles) is what the platform **writes** as
part of fulfilling a grant. It is the mechanism's output, not its input. Editing
it by hand produces access the catalog does not know about, which a later revoke
will not remove and which nothing in the subscription record explains.

## What this skill does not handle, and what to say instead

Name these rather than improvising over them.

| The situation | What to say |
|---|---|
| **No domain in this region.** The probe succeeded and returned nothing | There is no catalog subscription workflow here. Access to a Glue table in such an account is a Lake Formation or IAM decision, which is a different surface and a different skill. Say which probe told you this |
| **The asset has no listing** | It is not published. Publishing is `managing-data-catalog`; offer to point the user there rather than granting access some other way |
| **The table is governed outside the catalog**, such as a raw S3 prefix or a Lake Formation table with no catalog asset | Out of scope. Do not create a Lake Formation grant and describe it as sharing a data asset: it changes who can read the data without any record of who asked, who approved, or how to revoke it later |
| **Row or column-level restrictions** | Asset filters are a real mechanism and are not covered here. A filter refines a grant that already exists; there is no request or approval state machine for one. Say it is out of scope rather than approximating it with a narrower grant |
| **The user wants the dataset gone, not one team's access removed** | That is the ordered teardown in `managing-data-catalog`. Point there |

In every one of these, the answer has four parts and the order matters: what you
probed and what it returned, what does not exist here stated as a platform fact
rather than as your failure, the closest supported outcome offered concretely, and
what that alternative still does not cover.
