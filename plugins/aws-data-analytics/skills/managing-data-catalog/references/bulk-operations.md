# Bulk operations: one script, one collective wait

Documenting or tagging a whole database is the common real request, and a
per-asset conversational loop is where the cost is.

- You MUST NOT loop one asset at a time through separate tool calls.
- You MUST generate **one script** that performs every change, and print a plan
  naming every asset and the exact value before it runs.
- Where the platform is asynchronous, wait for everything **collectively** rather
  than per asset, but keep each invocation short. A tool call that blocks for
  more than about a minute can exceed the agent runtime's per-call timeout and
  lose the whole task; poll for tens of seconds, return a verdict, and run the
  poll again if it is not done.
- The script MUST snapshot every record it touches to a local file first, and
  report per asset: changed, unchanged, or failed, so a partial run is
  resumable rather than a mystery.

## Why the snapshot is not optional

The two canonical read-modify-write blocks in `describing-assets.md` exist
because both platforms' write APIs **replace** rather than merge. In bulk that
multiplies: one wrong shape applied across a database loses a field on every
asset at once, and the catalog has revisions but no rollback. The snapshot is
what turns that from a data-loss incident into a re-run.

`glue:UpdateTable` is the sharpest case. It takes a complete `TableInput`, and
dropping `Parameters` takes `metadata_location` with it, which does not lose
metadata but breaks an Iceberg table. Applied to nine tables in a loop, that is
nine broken tables.

## Reporting a partial run

Three outcomes per asset, never two: changed, unchanged, failed. Folding a
failure into "unchanged" is what makes a partial run unresumable, because the
user cannot tell what still needs doing from what was already correct.

Say which assets you acted on by name. A count alone ("updated 9 assets") cannot
be checked and cannot be resumed.
