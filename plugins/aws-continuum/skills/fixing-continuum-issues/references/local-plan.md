# Local plan and decision records

The agent reads and edits the local JSON file itself. There is no plan tool or script. State the exact proposed local write and get consent before recording a decision or rule. Status-only requests never mutate decisions.

## Location and shape

Use `${CONTINUUM_PLUGIN_DATA:-$HOME/.continuum-plugin}/plans.json`, outside Git. Keep directory mode 0700 and file mode 0600 (`umask 077`). Existing installs use the same shape, so preserve unrelated plans and unknown fields rather than replacing the file wholesale.

```json
{
  "schemaVersion": 1,
  "plans": {
    "chosen-plan-id": {
      "planId": "chosen-plan-id",
      "createdAt": "actual-UTC",
      "updatedAt": "actual-UTC",
      "groups": {},
      "setupCompletions": [],
      "decisions": [],
      "houseRules": [],
      "testResults": [],
      "shadowPredictions": [],
      "outcomes": []
    }
  }
}
```

Use simple plan and group IDs matching `[A-Za-z0-9][A-Za-z0-9_.-]{0,127}`. Each group has `id`, root cause, affected boundary, observed issue IDs, path IDs, proposed invariant, regression and legitimate-use tests, review criteria, and implementation state. Preserve decisions append-only; never rewrite the past to match a new recommendation.

Each decision records `{groupId, fixGroupIds, pathIds, choice, decidedBy, rationale, recordedAt}` plus alternatives rejected, scope, and review condition when known. Choice is `accepted`, `change-requested`, `changed`, `declined`, or `reverted`. An accepted or changed choice needs the actual affected path IDs. Reconsideration appends a `reverted` choice; it does not erase earlier acceptance. A change request requires further discussion before editing. Record actual user intent, not agent speculation.

Each house rule records a non-secret rule, its reason, affected groups/paths, provenance, and actual recorded UTC time. The tracked `.continuum/house-rules.md` is separate: propose that edit and its protection mechanism explicitly. Private deployment facts stay in the ignored deployment profile.

Setup completion records environment ID, `configured` or `reused`, repository count, effective quota, citation, and developer quota-increase statement if applicable. It has no patch-delivery prerequisite. Test records bind exact base/candidate commit or source hash, commands, exit codes, output paths/hashes, and negative/positive coverage. Predictions are shadow-only, with `authority: "none-shadow-only"`; they never authorize merging. Outcomes are observed facts, not projected closure.

## Safety and editing

Never store secrets, credentials, private keys, passwords, cookies, bearer strings, JWTs, AWS access keys, GitHub tokens, Slack tokens, or raw service fields that might contain them. Do not copy raw findings or logs into plans. Record only non-secret facts and evidence references. Do not use credential-like field names such as `accessToken`, `apiKey`, or `authorization`; a non-secret policy may be named `tokenPolicy` but must contain no token. If uncertain, omit the value and ask the developer.

Read and validate existing JSON before editing: the root must be an object with `schemaVersion: 1` and an object `plans`; each existing plan must be an object. Preserve unknown fields. A missing file may be initialized only for an approved write, not when merely reading status. Corrupt input is a blocker: preserve it and ask for recovery, never reset it. Serialize writers: do not edit while another agent or legacy plan-store writer is active. If `plans.lock` exists, stop rather than steal the lock; coordinate through the owner. Do not assert the former script's lock, secret-pattern rejection, or schema enforcement still exists. Those are now instruction-level safeguards.

For one approved writer, retain the original bytes and SHA-256 (or the explicit absence of the file). Re-read immediately before editing, write a same-directory private temporary file, parse it back, and verify that unrelated plans, unknown fields and prior histories remain intact. Immediately before atomic rename, compare the current file bytes/hash and existence to the original baseline; if changed, remove only your own temporary file and stop without overwriting. Check `plans.lock` again. Read back after rename. This detects an observed intervening edit, but is not a lock or atomic compare-and-swap: a writer racing the final check can still win. If exclusive coordination cannot be established, stop. Never blindly overwrite an externally edited file. Read the final file and show the recorded decision and rule. Keep each plan under 512 KiB, each collection under 1000 records, at most 1000 groups, at most 24 plans, and the complete store under 16 MiB; start a new plan rather than truncate history.
