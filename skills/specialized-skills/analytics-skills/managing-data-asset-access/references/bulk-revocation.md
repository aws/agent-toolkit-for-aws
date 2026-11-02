# Bulk revocation: one collective wait, never one per subscription

Removing access for several consumers at once is the common real request,
whether offboarding a team or retiring a dataset, and it is where the cost is.

- You MUST NOT revoke, wait, revoke, wait. Issue **every** revocation first,
  then run **one** wait covering all of them.
- You MUST print a plan naming every subscription you will revoke, its listing,
  and who loses access, and then **stop and wait for an explicit yes** before the
  first revocation. This is the one confirmation in this skill's destructive
  paths: a request naming the listings has not shown the user which
  subscriptions and consumers it resolves to. Ask once, with the plan, and not
  again at the wait.
- A request that already names **every** subscription id and the project that
  loses access is the yes, given with the list. Still resolve the plan and
  compare: if the real set is not exactly the named one (one more, one fewer, or
  another project), show the plan and stop, as if nothing had been confirmed.
- After the yes, revoke **exactly** the confirmed ids. If the set of
  subscriptions has changed since the plan, show the new plan and ask again.
- **Poll in SHORT calls that return a verdict, and repeat the call.** A single
  tool call that blocks for more than about a minute can exceed the agent
  runtime's per-call read timeout and lose the whole task. Poll for tens of
  seconds, print a verdict, and run the block again if it is not done. Do not
  raise the sleep to avoid re-running it.
- **A failed call is not a zero.** Folding a refusal into a count
  (`2>/dev/null || echo 0`) turns any error into "no grants remain". There are
  three outcomes (settled, not settled, and unknown) and unknown MUST NOT be
  reported as settled.
- Report per subscription: revoked and settled, revoked and still settling, or
  failed. A partial run the user can resume is a good answer; "done" is not,
  unless it is true.

## Poll by subscription id, not by listing

A revocation settles per subscription. Polling the listing tells you whether
*anything* still points at it, which is a different question and answers "no"
too early when several consumers are settling at different speeds.

`auditing-and-revoking.md` carries the status vocabulary, and one part of it
matters more here than anywhere else: a settled grant reads `COMPLETED`.
`GRANTED` never arrives, so a loop waiting for it runs until its timeout against
a state that does not occur.

## What a timeout must say

If the wait does not converge, report the **still-pending subscription ids**.
A timeout that says "could not confirm" without naming what is outstanding
leaves the user unable to resume, and is indistinguishable from a tool failure.

Warehouse-backed assets settle more slowly than lake-backed ones. Allow several
minutes before calling it a failure, and say which kind you were waiting on.
