# Publication lifecycle: publish, unpublish, retire

**SageMaker Catalog only.** The Glue Data Catalog has no listing, no data
product and no subscription concept; see `references/platform-detection.md`.

The two halves of this chapter are not equally hard. Publishing is a call three
models get right unaided; retiring is the sequence none of them ever got right.
The weight is on retirement deliberately.

## Publishing: short, because the trap is the report, not the call

An asset in a project's inventory is **not in the catalog** until it is
published. A data source run adds it to the inventory; if the source has
`publishOnImport: false`, consumers still cannot see it.

```bash
aws datazone create-listing-change-set --domain-identifier <domain> \
  --entity-identifier <asset-id> --entity-type ASSET --action PUBLISH
```

A data product publishes through the same call with `--entity-type DATA_PRODUCT`.

**Do not report what the change set returned.** Three things about a fresh
listing are misleading, all measured:

| What you might read | Why it is wrong |
|---|---|
| the `listingRevision` from `CreateListingChangeSet` | already stale: the listing was searchable at the next revision seconds later |
| `createdAt` from `SearchListings` | not the listing's timestamp. On one publish it was eleven hours out |
| that the call returned at all | the search index lags by seconds, so an immediate search can find nothing |

So the publish is not finished until you have read it back:

```bash
aws datazone get-listing --domain-identifier <domain> --identifier <listing-id> \
  --query '{status:status,revision:listingRevision,asset:item.assetListing.assetId}'
```

Report the `status` and the id from `GetListing`. You MUST NOT tell a user an
asset "is already published and discoverable" without having read a listing with
`status: ACTIVE` in this session. That exact claim was made about an asset with
zero listings in the domain, and a user who trusts it sends another team to
subscribe to something that does not exist.

An unpublish leaves the listing **readable at `status: INACTIVE`** rather than
removing it, so "is it still published" is a question about the status, not
about whether the object resolves.

### A failed publish is not retryable unchanged

If a publish fails, retrying the same call fails identically: the attempt is tied
to the asset's current revision and the service hands back the earlier failed
attempt. Give the asset a new revision first, then publish again.

## Retirement: the ordering, and both ways it goes wrong

This is the sequence. It is not optional and it is not reorderable:

```text
0. print the plan and STOP for an explicit yes, if anyone is subscribed
   (unless the request already named exactly that list: then compare, and go)
1. revoke every subscription to the listing
2. WAIT for the grants to actually disappear
3. unpublish the listing
4. delete the listing
5. delete the asset
```

**Step 0 is the one confirmation in this sequence, and it is mandatory.**
Deleting an asset that has live subscribers removes access other teams are
using, so the plan goes in front of the user before anything is revoked: every
subscription id, the project that loses access through each, and the listing and
asset that will be deleted. Then stop and wait for an explicit yes in a later
message. A request that already says "delete it even though they are
subscribed" does not replace this, because the user has not yet seen who is on
the list. If the asset has **no** live subscriber, there is nothing to confirm:
go straight to step 3.

**An advance yes.** A request that already names **every** subscription to
revoke (by id), the project that loses access, and the asset is the yes, given
with the list, so do not stop to ask it again. It does not skip the check: run
step 0 anyway and compare. If the real subscribers are not exactly the ones named
(one more, one fewer, or held by a different project), the user confirmed a
different list: show the real plan and stop, as if nothing had been confirmed.

Two opposite failures are both common, and half of them need the procedure
rather than a warning:

- **Stopping in the wrong place.** Asking a vague "are you sure?" before you
  have the plan, so the user answers without knowing who loses access; or
  asking **again** after the yes, at the settlement wait or before the unpublish.
  One stop, at step 0, with the plan. After the yes, run steps 1 to 5 through,
  then report what you revoked, whose access went, and what you deleted.
- **Deleting first.** `DeleteAsset` is **permitted** while the listing is
  published and a grant is live. Nothing protects the ordering. What survives is
  a listing at `status: ACTIVE` whose entity no longer resolves, visible to
  consumers and pointing at nothing.

### Step 2 is where it actually breaks

`RevokeSubscription` returns `REVOKED` **immediately** while the grant is still
being torn down in the background. In that window `DeleteListing` is refused, and
its refusal names every blocker:

```text
ConflictException: ... deletion prevented by containedSubscriptionGrant <id>,
subscriptionGrant <id>, subscription <id>
```

Three traps in the wait itself:

- **Wait for the grant to disappear, not for a status.** A grant that is still
  listed blocks `DeleteListing` whatever it reads, and straight after the revoke
  it still reads `COMPLETED`, the same status as a live grant. Poll for a status
  and you stop too early on `COMPLETED`, or never stop on `GRANTED`, which does
  not occur. (Checking that a consumer has lost *access* is a different question
  with a different answer; `managing-data-asset-access` covers it.)
- Poll **by subscription id**. The listing-level view goes stale.
- A grant being torn down reads `PENDING` then `IN_PROGRESS`, the same two
  statuses fulfilment passes through. The status alone does not tell you which
  direction it is moving; the subscription's own status does.

Allow tens of seconds for a lake-backed grant and several minutes for a
warehouse-backed one. Do the revokes for every subscription **first**, then poll
for all of them together, never one wait per subscription.

**Poll in SHORT calls, and repeat the call. Never sleep for minutes inside one.**
A single tool call that blocks for more than about a minute can exceed the agent
runtime's per-call read timeout: measured, a blocking wait killed the tool
connection after ~107 seconds and the whole task was lost with no answer. So each
invocation below polls for about forty seconds and then **returns a verdict**. If
it says `NOT SETTLED`, run the same block again, as many times as it takes. Do
not raise the sleep or the loop count to avoid re-running it; that is the thing
that breaks.

Step 0, the plan. Read-only. Scope it to **this asset's listing**: filtering by
project instead (`--approver-project-id`) returns the subscriptions to every
asset the project publishes, and revoking those cuts consumers off from data
nobody asked you to retire.

```bash
DOMAIN=<domain>; ASSET=<asset-id>

LISTING_ID=$(aws datazone get-asset --domain-identifier "$DOMAIN" --identifier "$ASSET" \
  --query 'listing.listingId' --output text)
echo "listing: $LISTING_ID"     # None = never published: nothing to revoke, skip to step 3
aws datazone list-subscriptions --domain-identifier "$DOMAIN" \
  --subscribed-listing-id "$LISTING_ID" --status APPROVED \
  --query 'items[].[id,subscribedPrincipal.project.name,subscribedPrincipal.project.id]' \
  --output text | tee /tmp/teardown-plan.txt
```

If the plan is empty, go to step 3. If the request named the subscriptions
(an advance yes), write the ids it named, one per line, and check each plan line
carries the project it named:

```bash
printf '%s\n' <subscription-id> <subscription-id> > /tmp/teardown-confirmed.txt
```

Otherwise show the user every line of the plan, say that the listing and the
asset will then be deleted, and **stop**. Proceed only on an explicit yes in
their next message, and then record what they said yes to:

```bash
cut -f1 /tmp/teardown-plan.txt > /tmp/teardown-confirmed.txt
```

Step 1, once, after the yes. Revoke exactly what was confirmed. If the
subscribers are not the confirmed list, whether they changed since the plan or
the user named a different set, the yes was for a different list:

```bash
DOMAIN=<domain>; LISTING_ID=<listing-id from step 0>

NOW=$(aws datazone list-subscriptions --domain-identifier "$DOMAIN" \
  --subscribed-listing-id "$LISTING_ID" --status APPROVED \
  --query 'items[].id' --output text | tr '\t' '\n' | sort)
PLANNED=$(grep . /tmp/teardown-confirmed.txt | sort)
if [ "$NOW" != "$PLANNED" ]; then
  echo "CHANGED: the subscribers are not the ones confirmed -- show the new plan, ask again"
else
  for s in $PLANNED; do
    aws datazone revoke-subscription --domain-identifier "$DOMAIN" --identifier "$s" \
      --query '{id:id,status:status}'
  done
  echo "$PLANNED" > /tmp/revoked-subscriptions.txt
fi
```

Capture the ids **before** revoking, as this does: once a subscription is
revoked, the listing filter stops returning it, so a list taken afterwards is
empty and the wait below would have nothing to wait on.

Step 2, repeated until it prints `SETTLED`. One collective poll over every
subscription, bounded so the call always returns:

```bash
DOMAIN=<domain>
SUBS=$(cat /tmp/revoked-subscriptions.txt)

for i in 1 2 3 4; do
  LIVE=0; FAILED=""; STUCK=""
  for s in $SUBS; do
    # Capture stdout and the exit status SEPARATELY. A failed call must never be
    # counted as zero grants -- see the warning below.
    if out=$(aws datazone list-subscription-grants --domain-identifier "$DOMAIN" \
             --subscription-id "$s" \
             --query 'items[].[status,join(`,`,assets[].status)]' \
             --output text 2>/tmp/grants-err.txt); then
      LIVE=$((LIVE + $(echo "$out" | grep -c .)))   # one line per grant still listed
      # Any *_FAILED or INACCESSIBLE, at either level, is terminal: stop, do not wait.
      echo "$out" | grep -qE 'FAILED|INACCESSIBLE' && STUCK="$STUCK $s"
    else
      FAILED="$FAILED $s"
    fi
  done
  [ -n "$FAILED$STUCK" ] && break
  [ "$LIVE" -eq 0 ] && break
  sleep 10
done
if [ -n "$FAILED" ]; then
  echo "UNKNOWN: could not read grants for$FAILED -- NOT settled, do not proceed"
  cat /tmp/grants-err.txt
elif [ -n "$STUCK" ]; then
  echo "FAILED: a failed or INACCESSIBLE grant on$STUCK -- stop, report it, do not re-run"
elif [ "$LIVE" -eq 0 ]; then echo "SETTLED: no grants remain"
else echo "NOT SETTLED: $LIVE grant(s) still present -- run this block again"; fi
```

**`FAILED` is terminal.** A grant whose status (or an asset's) reads
`GRANT_FAILED`, `REVOKE_FAILED`, `GRANT_AND_REVOKE_FAILED` or `INACCESSIBLE` will
not clear by waiting, and `DeleteListing` stays refused while it is there. Stop,
name the subscription and the asset's `failureCause`, and do not delete.

**`UNKNOWN` is not `SETTLED`, and that is the point.** A call that fails (denied,
throttled, or made with credentials for another account) prints nothing on stdout,
so folding its error into the count (`2>/dev/null || echo 0`) turns *any* failure
into `SETTLED: no grants remain`. Measured: this block reported settlement while
every call in it was being refused, because the refusal went to stderr and the
substitution yielded zero. `UNKNOWN` is not the same answer as `SETTLED` and MUST NOT
be reported as one. The whole reason to wait is that deleting into a live grant
leaves a listing pointing at nothing. If you see `UNKNOWN`, read the error and fix
the cause; `references/troubleshooting.md` covers the case where it is your tool
surface rather than your permissions.

Steps 3 to 5, only once step 2 printed `SETTLED`. Do not ask again: the yes at
step 0 covered the whole sequence.

```bash
aws datazone create-listing-change-set --domain-identifier "$DOMAIN" \
  --entity-identifier <asset-id> --entity-type ASSET --action UNPUBLISH
aws datazone delete-listing --domain-identifier "$DOMAIN" --identifier <listing-id>
aws datazone delete-asset  --domain-identifier "$DOMAIN" --identifier <asset-id>
```

If `DeleteListing` is refused, read the blockers it named and clear them:
cancel a pending subscription, or delete a lingering grant, rather than
retrying the same call.

Deleting an asset is destructive and the data is not the thing being deleted, so
the user may not expect the blast radius: afterwards, say what was removed and
name every consumer that lost access. Beyond step 0, ask only if you would go
**beyond** the request: deleting a second asset, or removing a grant that
belongs to something else.

## Data products

A data product bundles listings under one name and publishes through the same
change set with `--entity-type DATA_PRODUCT`. Create it with
`CreateDataProduct`, revise with `CreateDataProductRevision`, then publish. The
retirement sequence above applies to the product's listing as well: revoke,
wait, unpublish, delete.
