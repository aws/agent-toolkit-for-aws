# Compatibility check: classify traces

Classify traces **for each item** in `<artifacts>/classifications.json`. Triage the traces from
compatibility-check.md step 3 by their `run()` docstring (what the trace checks), then read the
plausible ones in full; a trace you mark `direct` must be read in full.

## Contents

1. [Relevance levels](#relevance-levels)
2. [Matching values](#matching-values)
3. [Assumption items](#assumption-items)
4. [Rules](#rules)
5. [File format](#file-format)

## Relevance levels

| Relevance | When |
|---|---|
| `direct` | All three conditions below hold. |
| `partial` | The trace calls the operation, but only as setup or teardown, with different settings, through another operation, or asserting something else. |
| `irrelevant` | The operation is incidental and nothing asserted concerns the item. |

**Be strict.** `direct` is a claim you must defend from the trace source alone. If you are
unsure about any of the three conditions below, mark it `partial`: a wrong `direct` tells a user
the app works when it may not; a wrong `partial` only costs a WILL NOT WORK that the report
explains. A different topic is not a reason for `partial`: a trace about an edge case of the call
still covers the plain call. What makes a trace `partial` is a different feature, mode, setting or
service, or an assertion that does not check the call.

`direct` iff:

| | Condition | How to decide |
|---|---|---|
| (a) | The item's operation is the trace's **subject** | The subject is what the trace's manifest `group`, id and `run()` docstring name. If they name a feature, mode or operation the item does not use (an index, a condition expression, a transaction, a dry run, a presigned URL, an asynchronous invocation), it is `partial`, even when an assertion also checks the item's operation or the trace fails while performing it. A variation of the plain call is not a different feature: a trace about value types, sizes or precision, unusual keys or characters, concurrent or repeated calls, or which part of the response or stored result it checks (metadata, headers, counts) still makes the call the app makes, so the operation is its subject when an assertion checks the call's response or effect (the item read back, the object's bytes), and (b) and (c) decide the rest. This holds only for a variation the app's own code can produce (its values, keys and call pattern can take that form); a variation it cannot produce (two attribute names that differ only in case when the app's names are fixed, binary values where it writes strings) says nothing about the app's calls, passing or failing, so that trace is `partial`. A generic group (`state`, `e2e_workflows`) names nothing; decide by the id and docstring, and in such a multi-step trace every call whose response an assertion checks is a subject, not only the last step, including a read that checks an earlier call's effect (a read after a delete that asserts nothing comes back is a read of a missing item). Otherwise the operation is the subject when they name it or an assertion checks its response, effect or error, not when it is called only to set up or tear down something else. When an item setting changes how the service behaves (a wait time, missing-data handling, a schedule expression, a filter policy), an assertion must check that behavior or its effect, not only the create/put response or the setting echoed back. |
| (b) | The trace uses the item's **settings with the app's values** | One call of the operation passes every item setting that has a literal value, with a value that behaves the same (see *Matching values*). A `"<dynamic>"` setting matches only a value of the kind the code can produce (same expression functions, same enum), not the key alone. Extra settings in the trace do not matter unless one selects a mode or type that changes the response or effect the item relies on (a dry run, an asynchronous invocation): a parameter the app omits has its AWS default, so such a trace is `partial`. A stronger guarantee than the app's (a strongly consistent read for a default read) still covers it. |
| (c) | **No foreign service** that the assertions depend on | Every service the trace asserts on is one the app uses. A service used only to set up or clean up a dependency (an IAM role, a KMS key) does not count. |

## Matching values

Compare what changes behavior, not the names inside it:

- Different forms differ: `cron(...)` vs `rate(...)`, `COMPLIANCE` vs `GOVERNANCE`, a filter
  policy using `prefix` vs one using `numeric`.
- Enum and string values must be equal, not just the same parameter: `notBreaching` is not
  covered by a trace that sends only `ignore` or `breaching`.
- A number counts only when the trace is in the same regime as the app's value: on the same side
  of any boundary the app relies on, and for a limit or batch size, at least the app's value.
- Names, ARNs, ids and payload values inside a value do not matter: an event pattern on `source`
  matches a trace with any source value; a policy document matches on effect, principal type
  (service, account, role) and condition keys, not on ARNs or names. Whether a principal is in
  the same account or another one does matter: a same-account principal does not cover a
  cross-account one.
- A parameter the trace omits equals its documented AWS default (no `DeliveryStreamType` means
  `DirectPut`).
- A setting may reach the resource through a different call than the app's: attributes set with
  a separate update call on the same resource (a subscription's `FilterPolicy` set after
  `Subscribe`) cover an app that sets them on create, when the trace asserts the behavior they
  produce.
- Client options that only change how a request is addressed or routed (S3 path-style versus
  virtual-hosted addressing, a FIPS or dual-stack endpoint) are not settings and do not need to
  match. A trace whose subject is one of those styles (its group, id or docstring names it) is
  about the style, not the operation, so it is `partial` under (a).

## Assumption items

An `assumption` item has no operation. A trace is `direct` for it only when the dependency is
the trace's **subject** and an assertion checks it: an identity-policy denial asserted for an
identity-policy assumption (a resource-policy denial does not count), region-dependent behavior
of the service asserted for a region from the environment, a cross-account trust asserted for a
cross-account principal. A resource whose definition is not in the repo (a policy document, a
state machine, a function's code) has nothing to compare, so no trace is direct for an
assumption about what it does, and a trace whose subject is a particular definition of it is not
direct for the calls that use it either.

## Rules

- **One call, several cases.** When one call can take more than one path the service treats
  differently (create or update), the item is covered when each path has a direct trace, even if
  no single trace exercises both.
- **Several direct traces.** Record every direct trace. The item is verified when one passes and
  none fails; a timeout or missing report entry on another one is listed as a note. Any failing
  direct trace makes it FAILING_TRACE (UNSUPPORTED_OP when the result is `not_implemented` on the
  item's operation).
- **Credit.** A trace may be classified for any item whose operation it calls (any trace for an
  `assumption` item).
- **Sub-scenarios are direct.** A trace for a distinct case the app can hit (long poll on an empty
  queue vs. with a message) is direct for the item of that case ([references/compatibility-find-usage.md](references/compatibility-find-usage.md) records one
  item per case).
- **Items without settings** (a plain round trip): direct means the trace asserts the operation's
  response or effect in a happy path the app also takes.
- **Error items** (`handled_errors`): direct only when the trace provokes that error **from the
  item's operation** and asserts it. The same error from a sibling operation is `partial`, and
  so is a happy-path trace.
- **Rejection traces** that first assert a successful call (a positive control) are direct for a
  happy-path item only if (a)–(c) hold for that control.
- Never drop, downgrade or swap a direct trace because of its score-report result.

## File format

The file is an object `{"schema": "aws-emulator.classifications/v1", "classifications":
[<entries>]}`, not a bare list. Each entry uses only these fields (any other, such as `trace`,
makes the entry invalid):

| Field | Required | Meaning |
|---|---|---|
| `item` | yes | The `id` of the item in `usage.json`. |
| `key` | yes | The trace key as listed in the corpus manifest (not `trace`). |
| `relevance` | yes | `direct`, `partial` or `irrelevant`. |
| `reason` | yes | One line: why this relevance. |
| `assert_quote` | for `direct` | One assertion line of the trace; `null` otherwise. |

`assert_quote`: one assertion line copied verbatim from the trace file (an `assert ...` line,
`raise AssertionError(...)`, the `raise` line of an `if ...: raise` check,
`with pytest.raises(...)`, `self.assert*(...)`, `expect(...)` or `fail(...)`). The call under test
(`resp = ddb.get_item(...)`) is not an assertion. Compatibility-check.md step 5 re-checks
every `direct` entry (the quote, the operations, handled errors, enum settings) and downgrades
the ones that fail.

```json
{"schema": "aws-emulator.classifications/v1",
 "classifications": [
   {"item": "sqs-long-poll", "key": "sqs/long-poll-returns-message",
    "relevance": "direct",
    "assert_quote": "assert len(msgs) == 1, msgs",
    "reason": "ReceiveMessage with WaitTimeSeconds=20 asserts the delivered message"},
   {"item": "sqs-long-poll", "key": "sqs/purge-queue-empties",
    "relevance": "partial", "assert_quote": null,
    "reason": "ReceiveMessage only checks the purge result"}]}
```
