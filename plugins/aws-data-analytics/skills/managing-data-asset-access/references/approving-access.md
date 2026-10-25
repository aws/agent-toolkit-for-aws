# Approving access, and sharing a listing directly

The producer side. Three things here fail for three different reasons, so read the
section you need rather than the whole chapter:

| The task | The measured failure |
|---|---|
| Approve or reject a request | The decision is made correctly and **recorded nowhere** |
| Confirm the requester really has access | Reported from the request's `ACCEPTED`, while the grant was still pending |
| Share a listing with a project that has not asked | Reaching for `CreateSubscriptionGrant`, being refused, and stopping |

## Review the queue

```bash
DOMAIN=<domain-id>; PROJECT=<your-project-id>

aws datazone list-subscription-requests --domain-identifier "$DOMAIN" \
  --approver-project-id "$PROJECT" --status PENDING \
  --query 'items[].{req:id,reason:requestReason,who:subscribedPrincipals[0],listing:subscribedListings[0].name,created:createdAt}'
```

`--approver-project-id` (or `--owning-project-id`, or `--subscribed-listing-id`)
is **required**: an unfiltered call is refused with
`ValidationException: Missing required filters`. As the approving project you
generally want `--approver-project-id`.

Present the queue with the requester, the listing and the **reason they gave**.
A request whose reason is empty or meaningless is worth flagging to the user
before they decide, not silently approving.

You MUST NOT decide a request the user has not decided. Surface the queue, then
execute the decision they state. Approving is a human access-control decision;
your job is to carry it out correctly and prove it took effect.

## Decide, with a comment. The comment is not optional

```bash
aws datazone accept-subscription-request --domain-identifier "$DOMAIN" \
  --identifier <request-id> \
  --decision-comment "Approved for <stated business purpose>, requested by <who>" \
  --query '{id:id,status:status,comment:decisionComment}'

aws datazone reject-subscription-request --domain-identifier "$DOMAIN" \
  --identifier <request-id> \
  --decision-comment "Rejected: <the reason the user gave>" \
  --query '{id:id,status:status,comment:decisionComment}'
```

**This is the single most-failed thing on the producer side.** The API does not
require `--decision-comment`, so it is trivially omitted, and the result is an
audit trail that records that production data was shared and nothing about why or
on whose authority. Six of nine unaided baseline runs approved the request
correctly and left it empty.

- You MUST pass `--decision-comment` on every accept and every reject.
- Write the user's actual reasoning into it, not "Approved." A comment that says
  nothing is only marginally better than none.
- Read it back in the same call (`--query` above) and report it.

Two behaviours to know:

- **A decided request drops out of the filtered list calls.** After an accept, the
  request is no longer returned by `list-subscription-requests --status PENDING`,
  and after a reject it is not returned by the listing- or project-filtered calls
  at all. That is not deletion. Read it by id with
  `get-subscription-request-details` to confirm the status and the comment.
- **Rejecting frees the pair immediately.** Only one subscription request may
  exist per (principal, listing) pair, which is what
  `ConflictException: SubscriptionRequest already exists ...` reports, and a reject
  releases it, so the consumer can refile straight away with a better
  justification. Say so when you reject something for a fixable reason.

## Approving is not access. Verify the grant

Accepting the request returns `status: ACCEPTED` and creates a **subscription**.
Fulfilment then happens on its own, with no further call, but not instantly.
Measured on a lake-backed asset, the grant reached `COMPLETED` around **50
seconds** after the approval; a warehouse-backed asset takes minutes. That window
is comfortably wide enough for an agent to approve, look once, and report success
over a grant that does not exist yet.

So the job is not finished at `ACCEPTED`:

```bash
# 1. find the subscription the approval created
SUB=$(aws datazone list-subscriptions --domain-identifier "$DOMAIN" \
  --subscription-request-identifier <request-id> \
  --query 'items[0].id' --output text)

# 2. poll the grant. Re-run this until it prints LIVE; do NOT sleep for minutes
#    inside one call -- see references/auditing-and-revoking.md on the timeout.
for i in 1 2 3 4 5; do
  OUT=$(aws datazone list-subscription-grants --domain-identifier "$DOMAIN" \
    --subscription-id "$SUB" \
    --query 'items[].[status,join(`,`,assets[].status)]' --output text)
  echo "$OUT" | grep -q 'COMPLETED' && break
  echo "$OUT" | grep -qE 'FAILED|INACCESSIBLE' && break
  sleep 10
done
echo "$OUT"
```

- `COMPLETED` at the grant level with `GRANTED` per asset is live access. Report
  that, and say which asset and target it landed on.
- `PENDING` or `IN_PROGRESS` means **not yet**. Say "approved; the grant is still
  provisioning" and keep polling, not "the requester now has access".
- `GRANT_FAILED` or `INACCESSIBLE` is a real outcome, and it will not change by
  waiting. Report it with the asset's `failureCause` rather than describing the
  approval as a success.

`GRANTED` is a per-asset value and is never what the grant's own `status` reads;
the two enums are set out in `references/auditing-and-revoking.md`. Polling the
grant's own status for `GRANTED` waits forever.

## The auto-approval surprise: when there is no review step at all

**Ask this before promising anyone a review.** If the identity filing the request
is an **approver of the OWNING project**, the project that publishes the listing,
then `CreateSubscriptionRequest` is auto-approved *on creation*. It returns
`status: ACCEPTED`, there is **no `PENDING` state at any point**, so there is
nothing for anyone to review and no decision comment recorded anywhere.
Fulfilment then follows by itself, in roughly ten seconds on a lake-backed asset,
so by the time the caller went looking for an approval step the access is already
live.

**The condition is about the owning project only.** Membership of the
*subscribing* project is irrelevant: a principal that is an approver of the
publishing project auto-approves even when it is not a member of the requesting
project at all. Getting this wrong in the other direction, by telling a user that
auto-approval requires ownership of **both** projects, is the specific error
every failing unaided run made, and it matters because it leads to the wrong
remedy.

To get a genuine review step:

- Have the request filed by a principal that is **not** an approver of the owning
  project, typically somebody in the consuming project. Then it sits at `PENDING`
  until `AcceptSubscriptionRequest` or `RejectSubscriptionRequest`, and the
  `decisionComment` recorded there is the audit checkpoint.
- Giving up your own approver role on the publishing project would also work, and
  is usually the wrong trade. Offer it as a fact, not as a recommendation.

Whenever a user's request implies a review that will not happen ("file a request
so the data owners can approve it", "raise it for sign-off"), say so **before**
acting, because filing it is the grant. This is one of the few genuine
confirmation checkpoints in this skill.

## Share a listing directly, with no request from the consumer

The user asks for "give the analytics team access without them having to ask".

**There is no `Share` operation in the API, and `CreateSubscriptionGrant` is not
one.** The share is a **subscription request that you file on the consumer's
behalf**, and it is one call:

```bash
aws datazone create-subscription-request --domain-identifier "$DOMAIN" \
  --subscribed-listings '[{"identifier":"<listing-id>"}]' \
  --subscribed-principals '[{"project":{"identifier":"<consumer-project-id>"}}]' \
  --request-reason "Shared with <project> for <stated purpose>, at the owner's request" \
  --query '{id:id,status:status}'
```

Because you are an approver of the owning project, this returns
`status: ACCEPTED` immediately (the section above), and fulfilment follows with no
further call: the grant reads `COMPLETED` in about ten seconds on a lake-backed
asset. Then verify it exactly as you would verify an approval, and confirm the
table actually appeared in the consumer's database if you can see it.

**Do not reach for `CreateSubscriptionGrant`.** It is the *fulfilment* call for a
subscription that already exists, and used as a share it fails twice over:

- `ValidationException: Principal id <project> does not have an active
  subscription for asset listing <listing>`, because there is nothing to fulfil.
- `AccessDeniedException: User is not permitted to perform operation` when called
  by a producer-project role. That refusal comes from **DataZone's own project
  authorisation layer, not from IAM**: the action is already present in the
  attached managed policy. So it MUST NOT be answered by proposing an IAM policy
  change, and it cannot be fixed by editing one. Reading the API's input shape and
  concluding it is the direct-grant path is the plausible wrong answer here, and
  it is what five of nine unaided baseline runs did before giving up.

### Which principal, and the shapes that are refused

`--subscribed-principals` accepts `project`, `user`, `group` and `iam` shapes.
Use **`project`** unless the user explicitly asked for something else:

- A `user` principal is **refused on a lake-backed (Glue table) listing**:
  `ValidationException: Subscribed principal type USER is not supported for the
  listing of type GlueTableAssetType`.
- Naming your own identity, or an `iam` principal, when the user asked for a
  team's project produces access for a principal nobody asked about. That is
  over-granting, and it is the failure this skill's safety chapter is mostly
  about.
- One listing and one principal per call. Read the resulting subscription back and
  confirm which principal it actually carries.

### The governance gap a direct share leaves, and what to say about it

A share creates access with **no consumer-side request at any point**. So:

- the `requestReason` was written by *you*, not by anyone who wanted the data;
- the `decisionComment` is **empty**, because nothing was decided;
- nothing in the record shows that the consumer asked or that anyone reviewed it.

Write a reason that would satisfy an auditor reading it a year later: who asked
for this, on whose behalf, and for what. And say in your answer that the share
bypassed the review step, so the reason you wrote is the only audit trail that
exists. Do not present a share as equivalent to an approved request.
