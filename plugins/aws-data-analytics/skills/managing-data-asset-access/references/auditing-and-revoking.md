# Auditing and revoking access

The removal is easy. **Proving it happened is the hard part, and it is the whole
point of this chapter.** Revoking returns success while the access is still being
torn down in the background, so an agent that trusts the response tells the user
access is gone when it is not, which is a security misstatement, not a cosmetic
one.

## Who currently has access

Two calls, and the second one is the answer. **Do not change anything while
answering this question**: an audit that revokes and regrants to "check" has
removed and recreated real access.

```bash
DOMAIN=<domain-id>; LISTING=<listing-id>

# 1. the decisions on this listing. The listing filter is fine HERE, because this
#    question is about subscriptions that are still live -- and ONLY here. Read the
#    warning under this block before you reuse this call for anything else.
aws datazone list-subscriptions --domain-identifier "$DOMAIN" \
  --subscribed-listing-id "$LISTING" --status APPROVED \
  --query 'items[].{sub:id,principal:subscribedPrincipal,retain:retainPermissions}'

# 2. the access itself, per subscription. Capture the subscription id from step 1
#    and keep it: after a revoke it is the ONLY way back to the grant.
aws datazone list-subscription-grants --domain-identifier "$DOMAIN" \
  --subscription-id <subscription-id> \
  --query 'items[].{grant:id,status:status,assets:assets[].{id:assetId,status:status,target:targetName}}'
```

> **Do not carry step 1 forward into a wait loop.** `ListSubscriptions` filtered
> by `--subscribed-listing-id` **stops returning a subscription once it is
> `REVOKED`**, so the same call that answers "who has access" reports success
> after a revoke by having nothing left to look at. Adding `--status REVOKED` to
> find it again works around the trap without noticing it, and tells you only
> that the decision was recorded. **Whenever the question is "has the access
> actually gone", key everything on the subscription id and read the grant.** The
> full treatment is in "The trap: never poll by listing" below; it is repeated
> here because this is the block an agent copies first.

Report from the **grant**. A subscription reading `APPROVED` whose grant is
`PENDING` or absent is a decision that has not taken effect: that project cannot
query the data yet, and saying it has access is wrong. Name the principal, the
grant status, and, if you can see it, where the access landed
(`assets[].targetName`).

## The two status enums, which are not the same enum

This is the trap that makes the wait fail even when the agent does wait. A grant
carries **two** statuses at two levels and they use different vocabularies:

| Level | `--query` path | Values |
|---|---|---|
| the grant, overall | `items[].status` | `PENDING`, `IN_PROGRESS`, **`COMPLETED`**, `GRANT_FAILED`, `REVOKE_FAILED`, `GRANT_AND_REVOKE_FAILED`, `INACCESSIBLE` |
| per asset in the grant | `items[].assets[].status` | `GRANT_PENDING`, `GRANT_IN_PROGRESS`, **`GRANTED`**, `REVOKE_PENDING`, `REVOKE_IN_PROGRESS`, **`REVOKED`**, `GRANT_FAILED`, `REVOKE_FAILED` |

Two consequences, and both have been got wrong:

- **`COMPLETED` is the grant's terminal status. `GRANTED` is not a value the
  grant's own status ever takes**, so polling `items[].status` for `GRANTED` waits
  for a state that never arrives. `GRANTED` lives one level down, per asset.
- **The overall status does not tell you which direction the grant is moving.**
  `PENDING` then `IN_PROGRESS` is what fulfilment looks like *and* what teardown
  looks like. The per-asset status does disambiguate, `GRANT_*` against
  `REVOKE_*`, and so does the subscription's own status.

## Revoking

```bash
aws datazone revoke-subscription --domain-identifier "$DOMAIN" \
  --identifier <subscription-id> --query '{id:id,status:status}'
```

**Capture the subscription id before you revoke.** This is not tidiness; it is
the only way the confirmation below works. See the trap two sections down.

`RevokeSubscription` takes `--retain-permissions`. Passing it deliberately leaves
the underlying permissions in place, so the catalog's grant goes away and the
access does not. You MUST NOT pass it when the user asked you to remove access.
When auditing someone else's past revoke, read `retainPermissions` back off the
subscription: `true` there means the access may still be live even though the
subscription reads `REVOKED`.

To withdraw one's own request that has not been decided yet, use
`CancelSubscription` on the subscription rather than `RevokeSubscription`; see
`references/requesting-access.md`.

## Confirming a removal: the procedure

No model in the baseline for this skill could produce this procedure unaided, on
any run. Follow it as written.

1. **Poll the grants by subscription id**, using the id you captured before the
   revoke. **Capture it before revoking, not after**, because after the revoke the
   listing-filtered lookup no longer returns the subscription, so an id you did not
   keep has to be recovered with `--status REVOKED`, and a wait loop built on the
   listing filter never notices it lost its subject.
2. **Settled means the grant has vanished**, or is still present with
   `status: COMPLETED` and every `assets[].status` reading `REVOKED`. A grant that
   completed a *grant* also reads `COMPLETED`, which is why the per-asset value
   matters on a teardown.
3. **Allow seconds for a lake-backed asset and minutes for a warehouse-backed
   one.** Measured on comparable assets, the same teardown took roughly 50
   seconds against roughly 190. Do not conclude "stuck" from the lake-backed
   timescale.
4. **Then check the tells below**, because a settled grant is not by itself proof
   that nothing else is granting access.

```bash
DOMAIN=<domain-id>
SUBS="<subscription-id> <subscription-id> ..."     # every id you revoked

for i in 1 2 3 4; do
  LIVE=0; FAILED=""; STUCK=""
  for s in $SUBS; do
    # Capture stdout and the exit status SEPARATELY. A failed call must never be
    # counted as zero grants -- see the warning below.
    if out=$(aws datazone list-subscription-grants --domain-identifier "$DOMAIN" \
             --subscription-id "$s" \
             --query 'items[].[status,join(`,`,assets[].status)]' \
             --output text 2>/tmp/grants-err.txt); then
      # A grant still listed is settled when it reads COMPLETED and every one of its
      # assets reads REVOKED (step 2 above). Count only the lines that are not.
      live=$(echo "$out" | awk -F'\t' 'NF { live = ($1 != "COMPLETED"); n = split($2, a, ",")
             for (i = 1; i <= n; i++) if (a[i] != "REVOKED") live = 1
             if (live) print }' | grep -c .)
      LIVE=$((LIVE + live))
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
  echo "UNKNOWN: could not read grants for$FAILED -- NOT settled, do not report success"
  cat /tmp/grants-err.txt
elif [ -n "$STUCK" ]; then
  echo "FAILED: a failed or INACCESSIBLE grant on$STUCK -- stop waiting and report this"
elif [ "$LIVE" -eq 0 ]; then
  echo "SETTLED: no live grant remains (each one gone, or every asset REVOKED)"
else
  echo "NOT SETTLED: $LIVE grant(s) still present -- run this block again"
fi
```

**Poll in SHORT calls and re-run the block.** A single tool call that blocks for
more than about a minute can exceed the agent runtime's per-call read timeout and
lose the whole task. This block polls for about forty seconds and returns a
verdict; if it says `NOT SETTLED`, run it again, as many times as it takes. Do
not raise the sleep or the loop count to avoid re-running it; that is the thing
that breaks.

**Three outcomes, not two.** A call that fails (denied, throttled, or made with
credentials for a different account) prints nothing on stdout, so folding its
error into the count (`2>/dev/null || echo 0`) turns *any* failure into
`SETTLED: no grants remain`. `UNKNOWN` is not the same answer as `SETTLED` and
MUST NOT be reported as one. If you see it, read the error;
`references/troubleshooting.md` covers the case where the cause is your tool
surface rather than your permissions.

## The trap: never poll by listing

`ListSubscriptions` filtered by `--subscribed-listing-id` **stops returning a
subscription once it is `REVOKED`**. So a wait loop keyed on the listing loses its
subject, finds nothing, and concludes everything has settled, by having nothing
left to look at. It reports success at the exact moment it stopped being able to
observe the thing it was waiting for.

The same behaviour applies more widely, and it is the reason for principle 6 of
this skill:

| You do this | It answers | The truth |
|---|---|---|
| `list-subscriptions --subscribed-listing-id` after a revoke | the subscription is absent | it exists and reads `REVOKED`. Read it by id with `get-subscription` |
| `list-subscription-requests` filtered, after a reject | the request is absent | it exists and reads `REJECTED` |
| `list-subscriptions` or `list-subscription-requests` with no filter | `ValidationException: Missing required filters` | at least one of `subscribedListingId`, `owningProjectId` or `approverProjectId` is required |
| `list-subscription-grants --owning-project-id` | not sufficient on its own | grants filter by `subscriptionId`, `subscribedListingId` or `environmentId`. Walk them by subscription |

**An empty list means "not returned by this filter", never "removed".** To tell
one from the other, read the object by id.

Because of that, a project-wide audit has to sweep **both sides deliberately**:
requests and subscriptions by `--owning-project-id` **and** by
`--approver-project-id`. A sweep that filters one side reports a clean result it
never actually performed.

## What tells you the access is NOT gone

Check all four. The first two are about the teardown; the last two are about
access that the teardown was never going to reach.

1. **A grant still `PENDING` or `IN_PROGRESS` past the expected window.** Keep
   polling, and say in your answer that it is still in flight rather than
   reporting completion.
2. **Any failed or `INACCESSIBLE` status**, at either level: `GRANT_FAILED`,
   `REVOKE_FAILED`, `GRANT_AND_REVOKE_FAILED` or `INACCESSIBLE`. This is a
   stop-and-report condition, not something to keep waiting on. Name the grant
   id and the `failureCause` on the asset.
3. **A surviving artefact of fulfilment.** For a warehouse-backed asset,
   fulfilment is a **view in the producer's own database** whose name carries the
   grant id verbatim, `grant_<schema>_<table>_<grantId>`; a view that outlives its
   subscription is access that outlived its revoke. On the lake path the
   equivalent tell is a resource link still present in the consuming project's
   database. Look for it by name.
4. **Access granted outside the catalog.** A Lake Formation permission or an IAM
   policy written by hand is not removed by a revoke, because the catalog does not
   know it exists. `list-permissions` must be asked for the **exact table**, because a
   database-scoped or wildcard query does not return a table-scoped grant:

   ```bash
   aws lakeformation list-permissions \
     --resource '{"Table":{"DatabaseName":"<db>","Name":"<table>"}}' \
     --query 'PrincipalResourcePermissions[].{principal:Principal.DataLakePrincipalIdentifier,perms:Permissions}'
   ```

   A permission naming a principal the platform did not create is out-of-band
   access. Report it; do not remove it silently, because you do not know what it
   was for.

Then say what you checked, not just what you concluded. "The grant is gone, the
resource link is gone, and Lake Formation shows no out-of-band permission on that
table" is an answer a user can act on. "Access has been revoked" is the sentence
that was wrong on every unaided run.

## Bulk revoke

Revoking for several consumers, or across several listings, is one operation with
one wait, never a revoke-and-wait per subscription. Measured on this task, the
sequential shape cost **2.1× the model cycles and 2.4× the input tokens** of the
collective one for an identical end state.

1. **Resolve and print the target set first**, naming every listing and every
   subscription you will revoke and who loses access. Then **stop and wait for an
   explicit yes**: revoking more than one subscription is this skill's one
   confirmation checkpoint (`references/bulk-revocation.md`). If the request
   already named every subscription id and the project, that is the yes: write
   those ids as the confirmed set instead, and do not ask.
2. **After the yes, revoke exactly the confirmed set**, capturing the ids in a
   file rather than in your head. If the real set differs from it, stop and show
   the plan.
3. **Run the wait block above once, over all of them.**
4. **Report per subscription**, and confirm what was *not* touched.

```bash
DOMAIN=<domain-id>; PROJECT=<your-project-id>

# Step 1 -- the plan. Print it, show it to the user, and STOP until they say yes.
for L in <listing-id> <listing-id> <listing-id>; do
  aws datazone list-subscriptions --domain-identifier "$DOMAIN" \
    --subscribed-listing-id "$L" --status APPROVED \
    --query 'items[].[id,subscribedListing.name,subscribedPrincipal.project.name]' --output text
done | tee /tmp/revoke-plan.txt

# Step 2 -- after the yes: revoke them all, then wait ONCE with the block above.
# Only if the subscriptions are still the ones confirmed; otherwise re-plan and ask.
for L in <listing-id> <listing-id> <listing-id>; do
  aws datazone list-subscriptions --domain-identifier "$DOMAIN" \
    --subscribed-listing-id "$L" --status APPROVED --query 'items[].id' --output text
done | tr '\t' '\n' | grep . | sort > /tmp/revoke-now.txt
cut -f1 /tmp/revoke-plan.txt | sort > /tmp/revoke-ids.txt
# An advance yes (the request named the ids): confirm those instead of the plan's.
# printf '%s\n' <subscription-id> <subscription-id> | sort > /tmp/revoke-ids.txt
if ! cmp -s /tmp/revoke-now.txt /tmp/revoke-ids.txt; then
  echo "CHANGED: the subscriptions are not the ones confirmed -- show the new plan, ask again"
else
  for s in $(cat /tmp/revoke-ids.txt); do
    aws datazone revoke-subscription --domain-identifier "$DOMAIN" --identifier "$s" \
      --query '{id:id,status:status}'
  done
fi
```

**Scope is the thing to get right, and it is on two axes.** Revoke exactly the
listings named and exactly the principals named. Two failures to avoid:

- **Sweeping the project.** "Revoke their access to these three listings" is not
  "revoke every subscription in my project". Resolve the named listings, list the
  subscriptions on each, and leave every other subscription alone. If you cannot
  resolve which listings were meant, act on the ones that clearly qualify and
  report the borderline ones. Do not widen.
- **Unpublishing instead.** Revoking access is **not** unpublishing the listing.
  Unpublishing is broader, hits every consumer at once, removes the asset from
  discovery, and is harder to undo. If the user asked to remove one project's
  access, the listing must still read `ACTIVE` afterwards.

## Reporting

Say, in this order: what you revoked, whose access went, that the grants settled
and how you know, and what you deliberately did not touch. If anything is still
in flight or failed, say that instead of averaging it into a success.
