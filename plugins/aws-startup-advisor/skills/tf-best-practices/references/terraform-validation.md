# Terraform Validation Protocol (shared)

> Canonical definition of the `fmt → init → validate → policy → fix-and-retry → offline-fallback`
> protocol for any phase that emits a `terraform/` directory. This document is **descriptive
> and caller-driven**: it specifies the mechanics and the report shape, but the **caller** (a
> migration skill's Generate phase) owns execution, the fix-and-retry edits, the user prompt,
> and any run-state decisions.

## Ownership boundary (important)

This protocol is part of the read-only `tf-best-practices` unit. Neither this document nor the
policy checker it invokes may:

- edit `.tf` files — the **caller** applies fixes (Stage D is a description of what the caller
  does, not an action this unit performs),
- read/write run-state (e.g. a phase-status file) — that is interpreter/caller territory,
- decide phase completion or prompt the user — caller policy.

The protocol's only durable output is `validation-report.json`. Where the caller writes it,
whether validation failure blocks the phase, and how the terminal status maps to run-state are
**all caller decisions**. The pseudocode below uses "the caller advances / stops" deliberately —
this unit never advances a state machine.

## When to use

Any step that writes a `terraform/` directory and wants to check it for format, HCL-level, and
policy defects while degrading gracefully when the provider registry is unreachable.

## Protocol

Working directory: the `terraform/` directory under test. All commands run non-interactively
(`-input=false -no-color` where supported). `$TERRAFORM_DIR` is the caller-supplied path.

### Stage A — Format

1. `terraform fmt -recursive` (auto-apply — a caller action).
2. `terraform fmt -recursive -check`. If non-zero, enter the Fix-and-Retry loop targeting fmt
   failures. On success, advance to Stage B.

### Stage B — Initialize (no backend)

1. `terraform init -backend=false -input=false -no-color`, capturing stderr.
2. On non-zero exit, run the **Offline Detection** algorithm below on the captured stderr.
   - If classified network-unavailable: set `validation_status = "passed_degraded_offline"`,
     emit warning, SKIP Stage C, **proceed to Stage F (policy still runs)**, then Stage E. Do
     NOT enter the retry loop.
   - Otherwise: enter the Fix-and-Retry loop targeting init failures.
3. On success, advance to Stage C.

### Stage C — Validate

1. `terraform validate -json`, capturing stdout.
2. On non-zero exit, parse `.diagnostics[]` and enter the Fix-and-Retry loop targeting validate
   failures.
3. On success, set `validation_status = "passed"` and advance to Stage F (Stage D remains
   available for policy retries).

### Stage D — Fix-and-Retry Loop (caller-executed)

Attempt budget: **3 attempts per batch**. Hardcoded.

Per attempt:

1. Read the failing command's error output:
   - fmt: the diff shown by `fmt -recursive -check` (list of files that would change).
   - init: the stderr captured from `terraform init`.
   - validate: the JSON diagnostics array from `terraform validate -json`.
   - policy: the `violations[]` from the policy checker's `--json` verdict (or `POLICY_FAIL`
     stderr lines).
2. **Group errors by file path.** For each file, open it once, apply all targeted edits for that
   file, close. Never rewrite a file wholesale; only edit the lines/blocks reported. (These
   edits are performed by the **caller** — this unit does not touch `.tf`.)
3. Re-run only the failing command (fmt -check, init, validate, or the policy checker).
4. If it passes, exit the loop and return to the calling stage's success path.
5. If the same `(file, line, summary)` reappears on consecutive attempts, emit a "same error
   recurring" signal in the attempt log — warning only; continue.

On the 3rd consecutive failure in a batch, the caller prompts the user:

```
Terraform validation failed after 3 automated fix attempts.
Last error: <one-line summary>
[retry] attempt 3 more fixes
[skip]  proceed with warning (validation_status = skipped_user_continue)
[abort] stop
Choose [retry/skip/abort]:
```

User choices (caller applies its own run-state policy on each):

- **retry** — reset the per-batch counter to 0, grant 3 more attempts. Cumulative `attempts`
  is NOT reset.
- **skip** — set `validation_status = "skipped_user_continue"`, emit warning, proceed to
  Stage E. (Whether the caller then allows phase completion is a caller decision.)
- **abort** — set `validation_status = "skipped_user_abort"`, write `validation-report.json`
  with that status, and STOP. The caller MUST NOT record a completion signal (do not advance
  run-state). This unit does not touch run-state itself.

### Stage F — Policy validation (mandatory when `terraform/` exists)

1. Run the read-only policy checker:

   ```bash
   python3 "<tf-best-practices>/scripts/validate-terraform-policy.py" "$TERRAFORM_DIR" --json "$VERDICT_PATH"
   ```

2. On non-zero exit, parse the verdict's `violations[]` (each carries `file`, `line`, `rule`,
   `fix_hint`) and enter Stage D Fix-and-Retry targeting policy violations.
3. On success (`POLICY_OK`), advance to Stage E.
4. If Stage C was skipped due to offline fallback, **still run Stage F** — the policy check is
   static and needs no provider init.

Record the policy outcome in `validation-report.json` `policy_status` (see schema). A policy
failure MUST be visible in the report — it must never be masked by a `passed_degraded_offline`
top-level status.

### Stage E — Emit validation-report.json

Write `validation-report.json` (path chosen by the caller, e.g. `$MIGRATION_DIR/`) per the
schema below.

## Offline Detection

```
FUNCTION isNetworkUnavailable(init_stderr)
  INPUT: init_stderr (string, captured stderr of `terraform init`)
  OUTPUT: boolean

  patterns ← ["lookup", "dial tcp", "connection refused", "timeout", "no such host"]

  IF init_stderr IS NULL OR trim(init_stderr) = "" THEN
    RETURN false   // empty stderr → treat as non-network failure (let retry loop handle)
  END IF

  haystack ← toLowerCase(init_stderr)

  FOR EACH p IN patterns DO              // first-match-wins
    IF contains(haystack, toLowerCase(p)) THEN
      RETURN true
    END IF
  END FOR

  RETURN false
END FUNCTION
```

**Rules**:

- **Source stream**: stderr of `terraform init` only.
- **Case sensitivity**: case-insensitive.
- **Match semantics**: first-match-wins; full-stderr scan.
- **Empty stderr**: treat as non-network failure so the retry loop runs (prevents silent
  offline-fallback when terraform fails for an unrelated reason with no stderr).

## Report Schema (v2)

v2 adds `policy_status` so the policy verdict is durably recorded independently of the
fmt/init/validate outcome. A policy failure is visible even when the top-level `status` is
`passed_degraded_offline`.

```json
{
  "$schema": "validation-report/v2",
  "status": "passed | passed_degraded_offline | skipped_user_continue | skipped_user_abort | policy_failed",
  "policy_status": "POLICY_OK | POLICY_FAIL | not_run",
  "attempts": 0,
  "errors_found": [
    {
      "file": "string (relative to terraform/)",
      "line": "integer (1-based, 0 if unknown)",
      "severity": "error | warning",
      "summary": "string (≤200 chars)"
    }
  ],
  "errors_fixed": [
    {
      "file": "string",
      "line": "integer",
      "severity": "error | warning",
      "summary": "string",
      "attempt": "integer (1-indexed)"
    }
  ],
  "policy_violations": [
    {
      "rule": "string (e.g. alb_http_redirect)",
      "file": "string",
      "line": "integer",
      "severity": "error | warning",
      "summary": "string",
      "fix_hint": "string"
    }
  ],
  "offline_fallback_used": false,
  "timestamp": "ISO 8601 UTC",
  "terraform_version": "string (empty if unavailable)"
}
```

**Field rules**:

- `status`: one of the enum values; equals the terminal `validation_status`. `policy_failed`
  is used when the fmt/init/validate stages passed (or offline-skipped) but policy did not and
  the user did not `skip`/`abort`.
- `policy_status`: `POLICY_OK` / `POLICY_FAIL` from Stage F, or `not_run` if Stage F did not
  execute (e.g. no `terraform/` produced). MUST reflect the last policy run — never inferred
  from `status`.
- `policy_violations`: the verdict's `violations[]` when `policy_status == POLICY_FAIL`
  (deduped); empty otherwise.
- `attempts`: total fix-and-retry attempts across all batches (never resets on `retry`).
- `errors_found` / `errors_fixed`: fmt/init/validate diagnostics, deduped by
  `(file, line, summary)`.
- `offline_fallback_used`: `true` iff `status == "passed_degraded_offline"`.
- `terraform_version`: from `terraform version -json`; empty string if unavailable (never crash).

**Example** (validate passed first try; policy caught an HTTP-forward ALB, caller fixed it):

```json
{
  "$schema": "validation-report/v2",
  "status": "passed",
  "policy_status": "POLICY_OK",
  "attempts": 1,
  "errors_found": [],
  "errors_fixed": [],
  "policy_violations": [],
  "offline_fallback_used": false,
  "timestamp": "2026-07-15T15:37:04Z",
  "terraform_version": "1.9.5"
}
```
