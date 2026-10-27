# Requesting access to somebody else's dataset

The consumer side. Deliberately short: the call is small and unaided agents get it
right when they get as far as making it. The two things that go wrong are before
and after the call: resolving what "my project" means, and naming the right
principal.

## Before the call

1. **Resolve your own project** from your identity, per
   `references/access-model-detection.md`. Do not ask the user which project they
   meant when three calls answer it.
2. **Resolve the listing id.** `search-listings` by name; a subscription is over a
   listing id, never an asset id or a table name.
3. **Check you do not already have it.** One request may exist per (principal,
   listing) pair, so a second attempt is refused with
   `ConflictException: SubscriptionRequest already exists for subscribed principal
   <project> Listing <listing>`. If that fires, the earlier request already exists, so
   read it rather than filing another.

## The call

```bash
DOMAIN=<domain-id>

aws datazone create-subscription-request --domain-identifier "$DOMAIN" \
  --subscribed-listings '[{"identifier":"<listing-id>"}]' \
  --subscribed-principals '[{"project":{"identifier":"<your-project-id>"}}]' \
  --request-reason "<the business purpose the user gave, in their words>" \
  --query '{id:id,status:status,reason:requestReason,principal:subscribedPrincipals[0]}'
```

**The principal is a project, not you.** Access is held by a project so that it
survives people joining and leaving, and so the audit record names a team rather
than an individual. `--subscribed-principals` also accepts `user`, `group` and
`iam` shapes, and using one of those when the user said "my project" produces
access for a principal nobody asked about. On a lake-backed (Glue table) listing a
`user` principal is refused outright:
`ValidationException: Subscribed principal type USER is not supported for the
listing of type GlueTableAssetType`.

**`--request-reason` is required by the API and its content is not.** Whitespace is
accepted and read back verbatim. So the field being present proves nothing; write
the actual business purpose, because for a producer deciding on this request it is
the only information they have about why you want the data. If the user gave you a
reason, use their words. If they did not, ask for one. This is the one input worth
a question, and it is cheap.

## Then read the status back and say what it means

```bash
aws datazone get-subscription-request-details --domain-identifier "$DOMAIN" \
  --identifier <request-id> \
  --query '{status:status,reason:requestReason,comment:decisionComment}'
```

| Status | What to tell the user |
|---|---|
| `PENDING` | Filed. It is waiting on the owning project to decide. **No access yet** |
| `ACCEPTED` **immediately, with no `PENDING` at all** | It auto-approved, because the identity you filed as is an approver of the *owning* project. There was no review step and no decision comment. Say so, because the user may have believed they were raising something for someone else to sign off. See the auto-approval section of `references/approving-access.md` |
| `REJECTED` | Read the `decisionComment` and report the reason. Rejecting frees the (principal, listing) pair, so a better-justified request can be filed straight away |

**A `PENDING` request is not access, and neither is an `ACCEPTED` one.** Access
exists when the subscription grant reads `COMPLETED`. If the request auto-approved,
poll the grant before telling anyone they can query the data;
`references/auditing-and-revoking.md` has the enums and the wait.

## Tracking and cancelling

```bash
# your project's own requests -- one of the filters is REQUIRED
aws datazone list-subscription-requests --domain-identifier "$DOMAIN" \
  --owning-project-id <your-project-id> --status PENDING \
  --query 'items[].{req:id,listing:subscribedListings[0].name,reason:requestReason}'

# withdraw a subscription you hold
aws datazone cancel-subscription --domain-identifier "$DOMAIN" \
  --identifier <subscription-id> --query '{id:id,status:status}'

# revise the reason on a request still pending
aws datazone update-subscription-request --domain-identifier "$DOMAIN" \
  --identifier <request-id> --request-reason "<better reason>"
```

`CancelSubscription` acts on the **subscription**, and it is the consumer-side
withdrawal of access the consumer holds. Removing somebody *else's* access is
`RevokeSubscription`, in `references/auditing-and-revoking.md`.

Cancelling and revoking are both asynchronous: the call returns before the
underlying access is torn down. If the user needs to know the access is actually
gone, not merely that the record says so, use the wait procedure in that chapter
rather than the call's own response.

## What you cannot do from the consumer side

- **You cannot approve your own request.** `AcceptSubscriptionRequest` from the
  requesting principal is refused by DataZone's project authorisation layer
  (`AccessDeniedException: User is not permitted to perform operation`) unless that
  principal is an approver of the owning project, in which case it never went to
  `PENDING` in the first place.
- **You cannot create the grant yourself.** `CreateSubscriptionGrant` only fulfils
  a subscription that already exists, and it is refused to a principal that is not
  authorised for the target environment.
- **A refusal on either is not an IAM problem.** Do not propose a policy change:
  the action is already in the managed policy, and the decision is DataZone's.
  Report the refusal and say who can act: the owning project's approvers.
