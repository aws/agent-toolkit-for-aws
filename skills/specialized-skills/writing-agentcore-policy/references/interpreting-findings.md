# Interpreting `validate` output and service findings

How to read the `validate` command's JSON and the service's policy `status` / `statusReasons`, and
what to tell the developer. A local result is never service acceptance, and neither proves live
authorization.

## Contents

- [Result shape](#result-shape)
- [Stages](#stages)
- [local_errors and claim_findings](#local_errors-and-claim_findings)
- [effect_adapter](#effect_adapter)
- [submission](#submission)
- [coverage.not_checked](#coveragenot_checked)
- [Service statusReasons](#service-statusreasons)
- [Revising without broadening access](#revising-without-broadening-access)
- [Repair rules](#repair-rules)
- [Reporting rules](#reporting-rules)

## Result shape

```json
{
  "status": "passed | rejected | incomplete",
  "dialect": "cedar | dogwood",
  "stages": {"syntax": {...}, "schema": {...}, "api_limits": {...}},
  "local_errors": [{"rule": "...", "message": "..."}],
  "claim_findings": [{"rule": "...", "message": "..."}],
  "effect_adapter": {"authored_effect": "...", "parsed_as": "..."} ,
  "submission": {"definition_key": "cedar | policy", "validation_mode": "FAIL_ON_ANY_FINDINGS | IGNORE_ALL_FINDINGS"},
  "coverage": {"not_checked": ["..."]},
  "checker": {"cedarpy": "...", "dogwood": "..."}
}
```

`effect_adapter` is `null` for ordinary statements.

## Stages

Explain the stages separately; do not blend them into one verdict.

| Stage | Meaning | Statuses |
| --- | --- | --- |
| `syntax` | the statement parses | `passed`, `rejected`, `skipped`, `unavailable` |
| `schema` | actions, resource and context fields exist and are correctly typed against the generated Cedar schema | same |
| `api_limits` | service limits the CLI can check offline (statement length, name rules) | same |

- `skipped` / `unavailable` are limits, not passes. Dogwood stages are `skipped` when the
  Dogwood CLI is not found on the host that runs the scripts (check; do not assume either way) and
  `unavailable` when it is installed but unusable (unsupported version, timeout, bad output).
  Relay the diagnostic's install hint once; the service still validates the statement on
  submission. Without a prepared context only syntax can be checked.
- A `schema` pass is only as good as the context: read the coverage gaps in the context for the
  actions the statement names. A gap limits conditions on that field only, never the whole target.
- Overall `status`:
  - `rejected`: at least one stage or rule definitively failed. Fix and re-run.
  - `passed`: every executed stage passed and nothing in the statement's class is unchecked.
  - `incomplete`: nothing failed but part of the statement could not be checked. This is **not** a
    pass. Say what was not checked.
- Local semantic analysis (satisfiability / "overly permissive" / conflicts with sibling policies)
  is not performed. The service runs its own analysis under `FAIL_ON_ANY_FINDINGS`.

## local_errors and claim_findings

Read both lists in full. Each entry has a `rule` and a `message`.

- A Set operation (`.contains`, `.containsAny`, `.containsAll`) on a String tag is **rejected**.
- An unguarded `getTag` (no `hasTag` on the same key) and an unanchored `like "*value*"` are
  **findings to resolve**, not style notes. The service rejects an unguarded tag or optional-field
  read at create ("unable to guarantee safety of access …"), and the `schema` stage reports the
  same error, so the guard is mandatory. An unanchored match grants more than the value named
  (`developer` matches `*dev*`); keep it only when the rule means a substring match.
- Numeric type mismatches are rejected by name in both directions: bare operators on a
  `decimal` field, decimal methods on a `Long` field. Use the `compare_with` hint from
  `describe` -> `context_types`.
- Guardrail rejections by name: a `$`-path rooted at `context`; a Cedar array projection in a
  content argument (`guardrail_array_projection`); a category the provider does not accept
  (`guardrail_category`; the message lists the accepted ones); per-category indexing on
  `SensitiveInformation` (`guardrail_sensitive_index`); a guardrail under `action in` / a target
  group / an unconstrained `action` (`scope_action_in`, `scope_guardrail_any_action`); `context.output` under an authorization effect. (CreatePolicy accepts a
  guardrail over an action list, but at runtime only the first listed action is screened and the
  others are always denied: write one policy per action.)
- A text field that the schema dropped (for example a `oneOf` field) is still reachable by a
  `$`-path on an inference, HTTP or Runtime target; on an MCP target the rule is non-translatable
  (`agentcore-targets-and-effects.md`, Guardrail scope).
- `temporal_event_resource`: an event predicate lacks `eventResource: resource`. Add it to every
  predicate the message lists; the service rejects the policy without it.

## effect_adapter

This skill writes `suppressOutput` on inference, HTTP and Runtime targets, and never the redaction
or interruption effects (`interruptOutput`, `redactOutput`, `redactInput`;
`agentcore-targets-and-effects.md`, Guardrail scope). If `effect_adapter` names one of those three,
do not submit it; route the rule non-translatable. For a statement the developer brought from
elsewhere, the rules below apply.

Dogwood parses only `permit` / `forbid`. Statements using these effects are parsed after the
keyword is rewritten, and the result carries `effect_adapter: {authored_effect, parsed_as}`.

- Overall status for these is at most `incomplete`, never `passed`.
- Say "parse-and-type-checked, with these items not checked", then list the
  `coverage.not_checked` entries: output-phase rules (at least one guardrail, no temporal clause,
  guardrails-only conditions), `context.isOutput` direction semantics, and for the three streaming
  effects account-level enablement.
- Never describe such a policy as checked or validated.

## submission

- `definition_key` selects how the write is shaped: `cedar` for plain Cedar, `policy` for the
  Dogwood dialect. Carry it into `api create_policy` / `update_policy` unchanged.
- `validation_mode` is the mode the write must use. A guardrail statement (`BedrockGuardrails::`,
  `when guardrails`) produces service findings even when correct, so it needs
  `IGNORE_ALL_FINDINGS`; everything else uses `FAIL_ON_ANY_FINDINGS`. `IGNORE_ALL_FINDINGS`
  suppresses findings on that statement only; it authorizes nothing and is not a reason to add or
  loosen a permit. The two vocabularies differ from the policy's `enforcement_mode`:
  - policy `enforcement_mode`: `ACTIVE` or `LOG_ONLY` (set on the policy);
  - Gateway engine mode: `ENFORCE` or `LOG_ONLY` (set on the Gateway's engine association, a
    separate setting this skill never changes). An `ACTIVE` policy is not evidence the Gateway
    enforces it; check the association (`api get_gateway`).
- For a temporal candidate, remind the developer that temporal policies need the
  `x-amzn-bedrock-agentcore-policy-session-id` header (`agentcore-service-rules.md`).

## coverage.not_checked

Relay every entry as unverified; do not turn it into a pass. Always-present items name checks only
the service performs: engine-wide schema size and merge, store selection by enforcement mode and
effect, live target validation, drift against sibling policies, and account entitlements (temporal
dialect, streaming effects). For a guardrail statement submitted with `IGNORE_ALL_FINDINGS` it
also notes that the service skips its own analysis. Statement-specific items (output phase,
`context.isOutput`, temporal semantics) appear alongside. For a temporal statement, count
semantics, windows, self-matching, the 3-operator limit and the session header are not verified
locally: say which parts are only parse- and type-checked.

## Service statusReasons

After `api create_policy` / `update_policy` the terminal `status` is `ACTIVE`, `CREATE_FAILED`,
`UPDATE_FAILED` or similar, with `statusReasons` as the service's findings. Read them verbatim;
report them with the policy name, and keep them separate from local results. Some validation
errors are returned synchronously (`validation` error), others only as an asynchronous failure
after a 202, so always read the final status. A failed provisioning can leave a `CREATE_FAILED`
policy in the engine; list it and include it in approved cleanup.

Common messages (abridged; the exact text can change), and their usual cause:

| Message (abridged) | Usual cause | Fix |
| --- | --- | --- |
| `Overly Permissive` | type-only permit with exact action/resource and no condition | review with the developer; narrow honestly or accept; do not add a meaningless condition |
| `comparison requires numeric operands on both sides` | decimal/string compared with `<`..`>=` inside `temporal` | integer fields; minor units |
| undeclared event field; message lists declared fields | temporal predicate names a field the event does not declare | use a listed field; correlate on `input.*` |
| `references 'context.output' but the policy has an authorization effect` | outbound guardrail under `permit` / `forbid` | screen the response with a separate `suppressOutput` policy (inference, HTTP and Runtime targets) |
| `Per-category indexing is not supported for SensitiveInformation` | `["CATEGORY"]` on SensitiveInformation | `count()` / `maxConfidenceScore()` |
| `argument ... has type Set<record> ... declares argument type string` | array named as bare field path (CREATE_FAILED after 202) | use a `$`-path |
| `request missing field(s) required for guardrail evaluation` or `a guardrail policy could not be evaluated - missing an attribute` (at request time) | the guardrail has no input to screen for this request: an omitted optional field, or one guardrail policy for several actions (only the first listed action is screened) | guard optional fields with `has` (see `agentcore-service-rules.md`); write one guardrail policy per action |
| CREATE_FAILED on an unknown action in an action list (for example `GET:/v1/models`) | the list names an action the Gateway does not have | take the actions from `prepare` / `describe` |
| `unable to guarantee safety of access to optional attribute` / `… to tag` | optional field or tag read without `has` / `hasTag` | add the guard on the same field or key |
| `A forbid policy that invokes a guardrail must specify the actions it applies to` / `invalid action ID "CallTool"` | guardrail under a bare `action` or a group | one policy per named action |
| `temporal predicates do not constrain the matched event to the current request's resource` | `eventResource: resource` missing | add it to every predicate |
| `A policy scoped with action in cannot contain temporal conditions` | temporal policy over a list or group | one policy per action (`action ==`) |
| `SensitiveInformation guardrail requires an aggregation method call` | whitespace or a line break before `.maxConfidenceScore()` (or another aggregation), or no aggregation | write the method directly after `SensitiveInformation(...)` |
| `encountered invalid principal type "AgentCore::UnauthenticatedUser"` | `UnauthenticatedUser` in the policy scope | remove it: on a `NONE` or `AUTHENTICATE_ONLY` Gateway every caller is unauthenticated, so a bare `principal` covers them; other Gateways reject such callers before the engine, so the rule is non-translatable there |
| `Expected exactly one policy statement in the input` | two statements in one policy | one draft per statement |
| `Output context is not supported in Cedar policies`, or local error `cedar_output_context` | `context.output` in a plain (non-temporal) Cedar policy | read output only on `::response` events |
| `depth … exceeds the maximum allowed depth of 64` | a very long `\|\|` or `&&` chain | split the policy, or use a set with `.contains` |
| missing action / entity | wrong target prefix, group used with `==`, placeholder ARN | re-copy names from `describe`; real Gateway ARN |

## Revising without broadening access

- Explain each diagnostic in plain words, keep the intended access matrix unchanged, and rerun
  `validate` after every revision. Re-check every affected statement, not only the last one.
- Never fix a finding by turning a condition off, widening the principal or action scope,
  adding a catch-all permit, or removing a `hasTag` / `has` guard.
- If a finding cannot be resolved honestly (the schema cannot express the intent), say so and
  describe the nearest expressible policy and its limits (`dogwood-language.md`, §8).
- If revising changes the exact statement, name, engine, mode or impact, any previously shown
  write preview is void: preview again and get a fresh approval.

## Repair rules

How to fix rejected drafts, one statement or a whole document (`document-authoring.md`):

- Fix all failing drafts together: read the errors of every rejected draft in the `validate
  --all-drafts` result first, make all the fixes in one response, store them (same `--name`, same
  rule text and IdP claims), and validate once again. For a document, stop after the round limit
  (3 by default); keep a draft that still fails, with its errors, and report it (never remove it,
  and never move it to non-translatable).
- Read each validator error literally and fix its stated cause. Common causes and the remedies in
  `dogwood-language.md`: an unknown `context.input.<field>` or action name (use only names present
  in the action schema, `<target>___<tool>`); a decimal compared with `>`/`<`/`>=`/`<=` (use the
  decimal METHODS `.greaterThanOrEqual(decimal("..."))` etc.; inside `temporal` a decimal cannot be
  ordered at all); `||` or `!=` used inside `when temporal` (not allowed — split into two rules, or
  rewrite `!=` as `!(x == y)`); a temporal operator missing its bounded `within <n>s|m|h|d` window;
  a guardrail category not in `guardrail_providers.categories`, or a wrong guardrail call shape (two
  `set<string>` args: `["CATEGORY"]` then `[context.input.<field>]`, then compare a score with a
  decimal method); a temporal predicate correlating with `context.principal`/`context.resource`
  ("has no context field `principal`" — use the reserved event field the event schema declares,
  bound to the bare scope entity: `eventPrincipal: principal` / `eventResource: resource`); a
  missing `eventResource: resource`; a malformed scope triple or missing terminating `;`.
- For a guardrail call, match the condition style to the provider. ContentFilter/PromptAttack over
  a named field use the bracket projection `["CATEGORY"].confidenceScore.<op>(decimal("X"))`;
  SensitiveInformation ALWAYS uses the aggregate `.maxConfidenceScore().<op>(decimal("X"))` —
  never bare/indexed `["CAT"].confidenceScore` (the service rejects it). There is no default
  inspect path: never invent a field such as `[context.input.message]` to make a policy compile.
  If the rule names no field the schema declares, the rule is non-translatable, not a repair
  case. A guardrail under a bare `action` or an action group is rejected; fix
  `scope_guardrail_any_action` or `scope_action_in` by writing one policy per action whose input
  declares the inspected field, never by dropping the guardrail.
- A stale event-schema name is a common cause, because the reserved event fields and event kinds
  have been renamed before. When the error is ``predicate ... mentions field `X`, which is not
  declared on that event``, it lists the declared fields — replace `X` with the right one from
  that list (e.g. a policy written against the old `__cedar_principal` / `__cedar_resource` must
  use the current `eventPrincipal` / `eventResource`). When it is ``no event kind `X` derived for
  action ...``, use a kind the event schema declares (`request`, `response`, `error`; the old name
  for `response` was `resolution`). Never repair either error by inventing a context field or by
  dropping the correlation. If a diagnostic suggests `callerPrincipal` / `callerResource` (the
  upstream Dogwood defaults), it is a checker version mismatch: do not rewrite the policy; report
  it.
- `since` is an atomic temporal operator — do NOT split it into `formerly` + `unless`. If the
  failing policy uses `when temporal { formerly within W X } unless temporal { !Y since within W X }`,
  this is wrong (the `unless` double-negates and inverts the effect). The correct form is a
  single `when temporal { !Y since within W X }` clause. If the validator error points to a
  malformed `since` expression, keep it as one `since` predicate and fix the syntax; do not
  decompose it into separate clauses.
- Preserve the meaning of the natural language policy. Do not silently drop a condition to make
  the error go away; re-express it correctly. If a condition truly cannot be expressed in Dogwood,
  keep the draft failing and say so; do not ship a weaker policy as if it were the rule.
- A principal-identity attribute is available if it is declared in the action schema (read it as
  `principal.<attr>`) or listed in the rule's IdP claims (read it as a String-typed principal
  tag, guarded: `principal.hasTag("scope") && principal.getTag("scope") like "*role:nurse*"`). Do
  NOT invent an attribute or claim that is in neither place, and do NOT "fix" an
  unknown-attribute error by dropping a condition that a listed IdP claim can express.

## Reporting rules

- Never call a policy "validated" when `status` is `incomplete`, a stage is `skipped` /
  `unavailable`, `effect_adapter` is set, or `coverage.not_checked` lists items; use "passed
  local checks X, Y; not checked: Z".
- Never invent a validator result. Without the output of `validate`, say it was not run.
- A local pass is not service acceptance; service acceptance is not proof of live enforcement.
  Do not claim enforcement was observed unless the developer exercised it.
