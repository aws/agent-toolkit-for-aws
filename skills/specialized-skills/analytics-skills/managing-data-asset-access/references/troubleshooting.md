# Troubleshooting

Six errors and one non-error. Each row is something an unaided agent has
misdiagnosed, and the diagnosis matters more than the fix: a wrong one here turns
into a proposed permissions change or a report that the API cannot do something it
can.

## The errors

| What you see | What it actually means | What to do |
|---|---|---|
| `ValidationException: Missing required filters. At least one of subscribedListingId, owningProjectId/... or approverProjectId is required` | `ListSubscriptions` and `ListSubscriptionRequests` refuse an unfiltered query. Not a permissions problem | Filter. As the approving project use `--approver-project-id`; as the requesting project `--owning-project-id`; for one listing `--subscribed-listing-id`. For a full audit sweep **both** project sides, because one filter answers half the question |
| `ConflictException: SubscriptionRequest already exists for subscribed principal <project> Listing <listing>` | Only one request may exist per (principal, listing) pair. Your first attempt worked, or somebody else's did | Read the existing request rather than retrying. Rejecting it frees the pair immediately, so a refiling is possible straight afterwards |
| `ValidationException: Principal id <project> does not have an active subscription for asset listing <listing>` | You called `CreateSubscriptionGrant`, which **fulfils an existing subscription** and cannot create access from nothing | The direct share is a producer-filed `CreateSubscriptionRequest` naming the consumer project. See `references/approving-access.md`. Do not look for a `Share` operation; there is none |
| `AccessDeniedException: User is not permitted to perform operation` on a subscription operation | Usually **DataZone's project authorisation layer** rather than IAM: the caller's project role, not its policy. Distinguish them before saying anything: if the same principal can perform neighbouring subscription operations in the same domain, its IAM policy carries `datazone:*` for this family and the refusal is DataZone's, so no policy edit reaches it | Report the refusal, name the operation, and name who can perform it. **Do not propose an IAM policy, draft a statement, or suggest joining another project** unless you have positively established the action is absent from the caller's policies. See `references/access-safety.md` §5 |
| `Error: subscriptionTargetIdentifier must be non-empty` | `CreateSubscriptionGrant` models that parameter as optional and requires it in practice | You are on the wrong call. See the row above |
| `ValidationException: Subscribed principal type USER is not supported for the listing of type GlueTableAssetType` | A lake-backed listing does not accept a `user` principal | Use a `project` principal, which is what you almost always wanted; see `references/access-safety.md` §6 |

## The non-error, and it is the expensive one

**An empty list is not a removal.** A revoked subscription, a rejected request and
a revoked request all stop being returned by the filtered list calls. Nothing
errors; the object simply is not in the response.

| You concluded | Because | Actually |
|---|---|---|
| "the subscription is gone, so the revoke settled" | `list-subscriptions --subscribed-listing-id` returned nothing | it exists and reads `REVOKED`. The grant may still be live |
| "there are no requests" | an unfiltered-looking call returned an empty `items` | you filtered one side only, or the request was already decided |
| "nobody has access" | a list call was refused and its error discarded | you measured nothing |

Read the object **by id** (`get-subscription`, `get-subscription-grant`,
`get-subscription-request-details`) before concluding anything is gone.

## When the same call succeeds one way and fails another

If you can reach AWS more than one way (an MCP server tool and a shell running the
CLI), **those surfaces authenticate separately and may be different principals, or
different accounts.** A call that is refused on one and succeeds on the other is
not a permissions fact about the account.

Before reporting any denial:

```bash
aws sts get-caller-identity        # on the surface that failed
```

Then retry the call on the other surface. If the two identities differ, say so
rather than reporting a permissions problem. This has produced confident answers
about the wrong account, including a settlement poll that printed a clean result
while every call inside it was being refused.

Related, and the reason the wait blocks in this skill are written the way they are:
a call whose failure is discarded (`2>/dev/null || echo 0`) returns a *number*, and
that number is zero, and zero means settled. Never let a refusal become a count.

## When a wait never finishes

| Symptom | Cause | What to do |
|---|---|---|
| the grant sits at `PENDING` / `IN_PROGRESS` past a minute or two | a warehouse-backed asset. Measured at roughly 190 seconds against 50 for a lake-backed one | keep polling in short calls, and say it is still in flight rather than reporting completion |
| you are polling for `GRANTED` on the grant and it never arrives | wrong enum level. The grant's own status reads `COMPLETED`; `GRANTED` is a per-asset value | poll `items[].status` for `COMPLETED`, and read `items[].assets[].status` for direction |
| `REVOKE_FAILED` or `GRANT_FAILED` | a real terminal failure | stop waiting. Report the grant id and the asset's `failureCause` |
| the whole task dies with no answer after a long tool call | a single call that blocks for more than about a minute can exceed the agent runtime's per-call read timeout | never sleep for minutes inside one call. Poll for tens of seconds, print a verdict, and re-run the block |
| the subscription you were polling has vanished from your list | you filtered by listing. See the non-error section above | capture the subscription id **before** revoking, and poll by that id |

## Two things that are working as intended

- **An unpublished listing still reads.** `GetListing` keeps answering with
  `status: INACTIVE`; it does not start failing. So "is it still published" is a
  question about the status, not about whether the object resolves.
- **A freshly published listing may not be searchable yet.** The index lags by
  seconds. Read it by id with `get-listing` rather than concluding the publish
  failed.
