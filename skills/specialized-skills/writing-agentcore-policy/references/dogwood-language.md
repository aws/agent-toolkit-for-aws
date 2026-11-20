# DOGWOOD_SUMMARY — Translating Natural Language into Dogwood Policies

This document tells you everything needed to translate a single natural-language
authorization policy into an executable **Dogwood** formula, anchored in a provided
schema. Every syntax example below has been validated against the Dogwood compiler.

Dogwood governs the actions of AI agents (financial assistants, medical office
managers, travel agents, insurance adjusters, appointment managers, codebase
managers, and so on). A Dogwood policy is a Cedar-style `permit`/`forbid` rule that
can additionally reason about **event history** (temporal expressions) and about
**computed safety values** (information providers, of which Bedrock Guardrails are
the supported instances).

> **Names in this skill.** The examples use AgentCore production names: a tool action
> is `AgentCore::Action::"<target>___<tool>"` (here the example target is `Tools`, so
> `AgentCore::Action::"Tools___Transfer"`), and every policy names the Gateway as
> `resource == AgentCore::Gateway::"<gateway-arn>"`. Replace `<gateway-arn>` and the
> names with the values `prepare` and `describe` report. This file covers the language;
> the service rules (limits, names, principal types, claims, what the service rejects at
> create) and the skill's checks are in `agentcore-service-rules.md` and
> `interpreting-findings.md`; where the two differ, the service rules win.

## Contents

- [1. The mental model](#1-the-mental-model)
  - [What you are given, and what you produce](#what-you-are-given-and-what-you-produce)
- [2. The action schema (your anchor)](#2-the-action-schema-your-anchor)
  - [Reading the `context` record: `input` / `output` / `system`](#reading-the-context-record-input--output--system)
- [3. Policy anatomy](#3-policy-anatomy)
  - [Effect and decision semantics](#effect-and-decision-semantics)
  - [The scope triple](#the-scope-triple)
  - [Condition clauses](#condition-clauses)
- [4. The Cedar condition-expression language](#4-the-cedar-condition-expression-language)
  - [Operators](#operators)
  - [Types and how you compare them](#types-and-how-you-compare-them)
  - [Methods](#methods)
  - [Principal attributes and identity (IdP) claims](#principal-attributes-and-identity-idp-claims)
  - [Time-based policies (datetime / duration)](#time-based-policies-datetime--duration)
- [5. Temporal expressions (event history)](#5-temporal-expressions-event-history)
  - [Predicates — describing a past event](#predicates--describing-a-past-event)
  - [The three past operators (all bounded, past-only)](#the-three-past-operators-all-bounded-past-only)
  - [Connectives, binders, aggregations](#connectives-binders-aggregations)
  - [Scope requirements for a temporal policy](#scope-requirements-for-a-temporal-policy)
  - [Worked temporal examples (validated)](#worked-temporal-examples-validated)
- [6. Bedrock Guardrails (information providers)](#6-bedrock-guardrails-information-providers)
  - [Invocation shape](#invocation-shape)
  - [A guardrail policy names exactly one action](#a-guardrail-policy-names-exactly-one-action)
  - [Scope qualifiers in a guardrail rule are NOT Cedar conditions and are NOT schema-validated](#scope-qualifiers-in-a-guardrail-rule-are-not-cedar-conditions-and-are-not-schema-validated)
  - [Category vocabularies](#category-vocabularies)
  - [Effect: block vs. allow](#effect-block-vs-allow)
  - [Threshold mapping](#threshold-mapping)
  - [Output methods (aggregations over categories)](#output-methods-aggregations-over-categories)
  - [Worked guardrail examples (validated)](#worked-guardrail-examples-validated)
  - [NOT translatable: cross-category gating and counting distinct types](#not-translatable-cross-category-gating-and-counting-distinct-types)
- [7. Putting it together — a translation recipe](#7-putting-it-together--a-translation-recipe)
- [8. Logic Dogwood CANNOT express](#8-logic-dogwood-cannot-express)
- [9. Quick syntax reference](#9-quick-syntax-reference)

---

## 1. The mental model

Dogwood is a superset of [Cedar](https://www.cedarpolicy.com/). You write `permit`
and `forbid` rules over a `(principal, action, resource)` scope with `when`/`unless`
conditions, and an authorizer answers **Allow** or **Deny** under **default-deny,
deny-overrides** semantics (a request is allowed only if some `permit` matches and no
`forbid` matches). On top of Cedar, Dogwood adds three monitoring mechanisms:

1. **Cedar core** — ordinary point-in-time conditions on the current request
   (`context.input.amount > 1000`, string patterns, entity checks, datetime windows).
2. **Temporal engine** — history-aware conditions inside `when temporal { … }`:
   "happened / did not happen in the last N units", counts, and sums over past events.
3. **Bedrock Guardrails** — content-safety checks (content filtering, prompt-attack
   detection, PII detection) invoked as **information providers**: ordinary Cedar
   calls of the form `BedrockGuardrails::Xxx(...)` whose result you compare against a
   threshold.

All three compile down to Cedar under the hood, so they combine freely inside one
rule with `&&`, `||`, `!`, and across multiple `when`/`unless` clauses.

### What you are given, and what you produce

A policy is anchored in three **schemas** (where the skill gets them: `SKILL.md`, Steps 1–2 and "Required files"):

- the **action schema** (a Cedar `.cedarschema`) — the entity types and actions (the
  agent's tools) and each action's `context.input`/`output`/`system` fields;
- the **event schema** — the event _kinds_ (`request`, `response`, `error`, …) and
  the reserved event-field names (`eventPrincipal`, `eventResource`, …) that temporal
  predicates use (see §5);
- the **provider schema** — the Bedrock Guardrails declarations (see §6).

A **Dogwood policy** is anchored in these schemas — every
action, entity type, `context.input.<field>`, event kind, reserved event field, and
guardrail category you name must exist in the corresponding schema.

> **The provided schemas are the source of truth — not the examples in this
> document.** Every example here is illustrative and was written against _particular_
> schemas; action names, entity types, field paths, event kinds, and reserved
> event-field names are **schema-defined and change over time** (the reserved names
> were themselves renamed once). When an example disagrees with the schemas you are
> given, **the schemas win** — copy the _shape_ of an example (which operator, which
> clause, which construct), never its literal identifiers. Always confirm a name
> against the relevant schema (action / event / provider) rather than assuming it
> exists because it appears here.

---

## 2. The action schema (your anchor)

Every policy authorizes against an **action schema** — a standard Cedar
`.cedarschema`. **The schema is provided to you (upstream); you do not write or
generate it.** Your job is to _read_ it and anchor your policy in it: find the exact
action names, entity types, and `context` field paths, and reference only those.
Dogwood adds **no** schema syntax; the schema is Cedar verbatim, and it follows a
fixed layout for the `context` record (described below) that tells you where a tool's
arguments and results live.

A representative schema (financial assistant), of the kind you will be given:

```text
namespace AgentCore {
  entity OAuthUser = { id: String } tags String;
  entity IamEntity = { id: String };
  entity UnauthenticatedUser;
  entity Gateway;
  type SystemContext = { now: datetime };

  type TransferInput  = { stock: String, amount: Long, memo: String };
  type TransferOutput = { proceeds: decimal };
  type RefundInput    = { reason: String, amount: Long };

  action Mcp appliesTo {
    principal: [OAuthUser, IamEntity, UnauthenticatedUser], resource: [Gateway],
    context: { isOutput: Bool, sessionId: String, system: SystemContext }
  };
  // CallTool groups every tool action; it declares no input of its own.
  action CallTool in [Mcp] appliesTo {
    principal: [OAuthUser, IamEntity, UnauthenticatedUser], resource: [Gateway],
    context: { isOutput: Bool, sessionId: String, system: SystemContext }
  };
  // The target group: one per Gateway target, holding the target's tools.
  action "Tools" in [Mcp] appliesTo {
    principal: [OAuthUser, IamEntity, UnauthenticatedUser], resource: [Gateway],
    context: { isOutput: Bool, sessionId: String, system: SystemContext }
  };
  action "Tools___Transfer" in [CallTool, "Tools"] appliesTo {
    principal: [OAuthUser, IamEntity, UnauthenticatedUser], resource: [Gateway],
    context: { input: TransferInput, output?: TransferOutput,
               isOutput: Bool, sessionId: String, system: SystemContext }
  };
  action "Tools___Refund" in [CallTool, "Tools"] appliesTo {
    principal: [OAuthUser, IamEntity, UnauthenticatedUser], resource: [Gateway],
    context: { input: RefundInput, isOutput: Bool, sessionId: String, system: SystemContext }
  };
}
```

In a policy, write the plain `AgentCore::Action::"Tools___Transfer"` form (how the
generated schema names actions and record types: see `agentcore-service-rules.md`, Scope).

Reading it:

- **`namespace AgentCore { … }`** — actions live under an implicit `Action` entity
  type, so the `Transfer` tool of the `Tools` target is written
  **`AgentCore::Action::"Tools___Transfer"`** in a policy. Always use the
  fully-qualified `Namespace::Action::"<target>___<tool>"` form.
- **`entity` declarations** (`OAuthUser`, `Gateway`, …) are the principal and
  resource types. They may carry attributes (`= { id: String }`) and `tags String`.
- **`type` declarations** are reusable record types the actions reference for their
  `input` / `output` records.
- **`action "<Id>" appliesTo { principal, resource, context }`** — one per tool.
  Actions may sit in a hierarchy with `in [...]` (e.g. `Tools___Transfer in [CallTool, "Tools"]`;
  `"Tools"` is the target group).

### Reading the `context` record: `input` / `output` / `system`

The provided schema lays out each action's `context` in a fixed shape. A policy reads
request data through `context`:

- **`context.input.<field>`** — the tool's arguments (e.g. `context.input.amount`).
- **`context.output.<field>`** — the tool's result; usually optional (`output?`),
  present only after the action resolves.
- **`context.system.now`** — a `datetime`, the current time (for time-of-day and
  date-window policies).
- **`context.sessionId`** — the session correlation the event schema `pin`s. You never
  write it in a policy, but it must be **declared on every action a temporal policy
  scopes to**, or that policy will not validate (see §5, "Scope requirements").

The exact shape of `context.input` is determined by the scoped action. Reference
only fields that exist in that action's input record — an unknown field is a hard
validation error:

```
attribute `input.nonexistent` in context for AgentCore::Action::"Tools___Transfer" not found
```

> **Validate field existence before translating — it gates translatability.** For
> **every field a rule references**, confirm it resolves to either a declared
> `context.input.<field>` (or other declared attribute) in the action schema **or** a
> named IdP claim (see §4). A match must be **unambiguous** — only surface
> reformatting of the _same_ word counts: exact match, case differences, or
> underscore/camelCase/abbreviation variants of one another ("input message" ↔
> `input_message` ↔ `inputMessage`; "user id" → a `uid` field; "requirement" → `req`).
> **Different words are NOT a match** even when related in meaning — "comment" vs
> `content`, "message" vs `information`, "justification" vs `reason`. If nothing in
> the schema or the IdP list matches under that strict test, the rule is
> **non-translatable** — do not invent a field, and do not substitute a merely
> synonymous one. This holds even for a bare **existence / empty
> check** ("field is present", "is empty", "is not set", a `has` guard): the referenced
> field must exist first, so do not skip this validation just because the rule only
> tests presence rather than a value.

---

## 3. Policy anatomy

A `.dw` file is a sequence of policy rules, each terminated by `;`. Comments are
`//` to end of line (no block comments). Each rule has five parts, in order:

1. Zero or more **annotations** — `@id("…")` (metadata only; never affects matching).
2. An **effect** — exactly `permit` or `forbid`.
3. A parenthesized **scope** triple — `( principal, action, resource )`.
4. Zero or more **condition clauses** — `when { … }` / `unless { … }`.
5. A terminating **semicolon** `;`.

```text
@id("sell_small_only")
permit (
    principal,
    action == AgentCore::Action::"Tools___Transfer",
    resource == AgentCore::Gateway::"<gateway-arn>"
)
when { context.input.amount <= 50 };
```

AgentCore takes **one rule per policy**: a `.dw` file here can hold several rules, but
each rule is stored, validated and submitted as its own policy (its own draft).

### Effect and decision semantics

- A request is **allowed** iff at least one `permit` matches **and** no `forbid`
  matches. Otherwise **deny** (default-deny).
- `forbid` always wins, so **source order does not matter**. To express "allow X but
  block the dangerous subset", write a broad `permit` and a narrow `forbid`:

```text
permit ( principal, action == AgentCore::Action::"Tools___Transfer", resource == AgentCore::Gateway::"<gateway-arn>" );

forbid ( principal, action == AgentCore::Action::"Tools___Transfer", resource == AgentCore::Gateway::"<gateway-arn>" )
when { context.input.stock == "AMZN" };
```

These are two policies. When the destination engine already has a permit that covers
the callers of `Tools___Transfer`, write only the `forbid`: do not add a second, broad
permit.

### The scope triple

Three slots, always `principal, action, resource`, each either **bare**
(unconstrained) or given one constraint:

| Form                      | Applies to          | Meaning                |
| ------------------------- | ------------------- | ---------------------- |
| bare (`principal`)        | all                 | matches anything       |
| `== Ns::Type::"id"`       | principal, resource | exact entity           |
| `== Ns::Action::"id"`     | action              | exact action           |
| `in Ns::Type::"grp"`      | principal, resource | hierarchy membership   |
| `in [Ns::Action::"a", …]` | action              | any of these actions   |
| `is Ns::Type`             | principal, resource | entity-type test       |
| `is Ns::Type in Ns::Grp`  | principal, resource | type test + membership |

Examples:

```text
permit ( principal is AgentCore::OAuthUser,
         action == AgentCore::Action::"Tools___Transfer",
         resource == AgentCore::Gateway::"<gateway-arn>" );

permit ( principal,
         action in [AgentCore::Action::"Tools___Transfer", AgentCore::Action::"Tools___Refund"],
         resource == AgentCore::Gateway::"<gateway-arn>" );
```

Rejected in a scope: `action is Type` (not allowed on the action slot), the colon
form `principal : Type` (use `is`), `=` (use `==`), and any operator other than
`==` / `in` / `is`.

In AgentCore the **resource slot is never bare**: every policy names the Gateway with
`resource == AgentCore::Gateway::"<gateway-arn>"` (a service rule).

> **Entity names vs. types.** Entity _types_ (`OAuthUser`, `Gateway`) come from the
> schema; specific _instance names_ (the quoted id, e.g. `"alice"`) come only from
> the NL policy text, never the schema. For "user alice", write
> `principal == AgentCore::OAuthUser::"alice"`. The id of an `OAuthUser` is the
> token's `sub` claim (not the user name), and the id of an `IamEntity` is the caller's
> ARN; when the NL names a user by name, say that the policy assumes this name is the
> id.

### Condition clauses

A rule may carry any number of `when` / `unless` clauses; they are **conjoined**:
the rule fires iff every `when` body is true and no `unless` body is true.
`unless { B }` is exactly `when { !B }`. Stack them instead of one giant `&&`:

```text
permit ( principal, action == AgentCore::Action::"Tools___Transfer", resource == AgentCore::Gateway::"<gateway-arn>" )
when   { context.input.amount <= 1000 }
unless { context.input.stock == "BLOCKED" };
```

Three clause flavors:

- `when { E }` / `unless { E }` — ordinary Cedar (also hosts provider calls).
- `when temporal { φ }` / `unless temporal { φ }` — history-aware (Section 5).
- `when guardrails { E }` — the clause for guardrail checks. Its body is ordinary Cedar
  (`when { E }` behaves the same), but it is the form the AgentCore documentation uses for
  guardrail policies: **write every clause that calls `BedrockGuardrails::` as
  `when guardrails { … }`**, including one that also has plain conditions.

---

## 4. The Cedar condition-expression language

Everything inside `when { … }` / `unless { … }` is a Cedar expression. Precedence,
loosest to tightest: `if/then/else` → `||` → `&&` → relational → `+`/`-` → `*` →
unary `!`/`-` → member access → primary. All binary chains associate left.

### Operators

- **Logical:** `&&`, `||`, `!` (short-circuit). Parenthesize to override
  precedence: `(a || b) && !c`.
- **Comparison:** `<`, `<=`, `>`, `>=`, `==`, `!=`, and `in` (hierarchy membership).
- **Arithmetic:** `+`, `-`, `*` on `Long` only. **`/` and `%` are NOT supported**
  (`` `/` is not a supported operator ``).
- **`if C then A else B`** — an expression; both branches must have the same type.
- **`e has attr`** — tests whether an optional attribute is present (guard before
  reading it, exploiting `&&` short-circuit): `context has output && context.output.approved`.
  The guard is **mandatory**: a policy that reads an optional field without it is
  rejected at create ("unable to guarantee safety of access to optional attribute").
  With the guard, an absent field makes the guarded clause false, so write it to match
  the intent: `context.input has f && …` lets a call without `f` through,
  `!(context.input has f) || …` catches it.
- **Member access `e.attr` / `e["key"]`** — read a record field. `e["key"]` is a general
  Cedar accessor equivalent to `e.attr`; the key must be a **string literal** (no dynamic
  or positional indexing), e.g. `context.output.categories["VIOLENCE"]`. (This same `["key"]`
  form is what projects a guardrail category in §6.)
- **`s like "pat"`** — string wildcard match; `*` matches any run of chars.
- **`e is Type`** / **`e is Type in group`** — entity-type test in a condition.

### Types and how you compare them

| Type     | Literal / constructor              | Comparison                                                               |
| -------- | ---------------------------------- | ------------------------------------------------------------------------ |
| Bool     | `true` / `false`                   | `== true`, `== false`                                                    |
| Long     | `42`, `-1`                         | full ordered set `< <= > >= == !=`                                       |
| String   | `"…"`                              | `==`, `!=`, `like` (no ordering)                                         |
| Decimal  | `decimal("0.5")`                   | **equality only** with `==`/`!=`; for ordering use the **methods** below |
| Datetime | `datetime("2025-01-01T00:00:00Z")` | full ordered set                                                         |
| Duration | `duration("1h30m")`                | full ordered set                                                         |
| IP       | `ip("10.0.0.0/24")`                | via methods                                                              |
| Set      | `["a","b"]`                        | `.contains`, `.containsAll`, `.containsAny`, `.isEmpty`                  |
| Record   | `{ k: v }`                         | field access `.k` or `["k"]`                                             |
| Entity   | `Ns::Type::"id"`                   | `==`, `in`, `is`                                                         |

> **Decimal ordering is a common trap.** `context.x.severityScore > decimal("0.5")`
> is a type error (`expected datetime, or duration, or Long but saw decimal`). Use
> the decimal methods instead.

### Methods

Zero-arg: `.isEmpty()`, `.isIpv4()`, `.isIpv6()`, `.isLoopback()`, `.isMulticast()`,
`.toDate()`, `.toTime()`, `.toMilliseconds()`, `.toSeconds()`, `.toMinutes()`,
`.toHours()`, `.toDays()`.

One-arg: `.contains(x)`, `.containsAll(s)`, `.containsAny(s)`, `.getTag(k)`,
`.hasTag(k)`, `.isInRange(cidr)`, `.offset(d)`, `.durationSince(t)`, and the decimal
comparison methods **`.lessThan(d)`, `.lessThanOrEqual(d)`, `.greaterThan(d)`,
`.greaterThanOrEqual(d)`**.

### Principal attributes and identity (IdP) claims

Cedar **supports checking principal attributes** — `username`, `id`, `scope`,
`client_id`, `token_use`, and the like. A principal attribute is **accessible**
(and a rule that references it is therefore **translatable**) if it appears in
**either** of two places:

1. **The action schema** — an attribute declared on the principal entity type
   (e.g. `entity OAuthUser = { id: String }`), read directly as `principal.<attr>`
   and typed as the schema declares.
2. **The user IdP information list** — identity-token claims supplied alongside
   the request. Every IdP claim is a **`String`**, carried as a **tag** on the
   principal under its exact claim name (e.g. `custom:department`, `cognito:groups`);
   read it with `principal.getTag("<claim>")` (the guard
   `principal.hasTag("<claim>") &&` first is **mandatory**: an unguarded `getTag` is
   rejected at create). Because these are strings, use `==`/`!=` for
   exact matches and **`has` / `like`** for presence and **substring** matches. A
   list claim arrives as its JSON text (`["a","b"]`), and `.contains` on a tag is a
   type error; `getTags()` does not exist.

Do **not** invent an attribute or claim that is in neither place. But do **not**
route a rule out of scope merely because the attribute is absent from the schema —
if it is a named IdP claim, it is translatable. Examples:

```text
// Schema attribute (principal.id declared on OAuthUser; its value is the token's `sub`)
permit ( principal is AgentCore::OAuthUser, action == AgentCore::Action::"Tools___Transfer", resource == AgentCore::Gateway::"<gateway-arn>" )
when { principal.id == "alice" };

// IdP claim as a tag — exact match
permit ( principal, action == AgentCore::Action::"Tools___Transfer", resource == AgentCore::Gateway::"<gateway-arn>" )
when { principal.hasTag("username") && principal.getTag("username") == "allowed" };

// IdP claim as a tag — substring match with `like`
// NL: "user has \"role:basic\" in its scope"  (translatable when `scope` is an IdP claim)
permit ( principal, action == AgentCore::Action::"Tools___Transfer", resource == AgentCore::Gateway::"<gateway-arn>" )
when { principal.hasTag("scope") && principal.getTag("scope") like "*role:basic*" };
```

### Time-based policies (datetime / duration)

The schema must expose a datetime (conventionally `context.system.now`). These shapes:

**Time-of-day only (no date):** extract the clock component with `.toTime()` and
compare against `duration` bounds. Never invent a date.

```text
// Allow refunds only during business hours 9am–3pm UTC
permit ( principal, action == AgentCore::Action::"Tools___Refund", resource == AgentCore::Gateway::"<gateway-arn>" )
when { context.system.now.toTime() >= duration("9h")
    && context.system.now.toTime() <= duration("15h") };
```

**Absolute date/time window:** compare `context.system.now` against `datetime(...)`:

```text
permit ( principal, action == AgentCore::Action::"Tools___Refund", resource == AgentCore::Gateway::"<gateway-arn>" )
when { context.system.now >= datetime("2025-02-02T19:00:00Z")
    && context.system.now <  datetime("2025-03-02T19:00:00Z") };
```

**Relative windows** use `.offset(duration(...))`, e.g. "inactive ≥ 365 days":
`context.last_login_event.offset(duration("365d")) <= context.system.now`.

> **A datetime rule is Cedar, not temporal — and the temporal limits below do
> NOT apply to it.** The 24h `max_window` cap, the past-only restriction, and the
> "no week/month/year unit" rule in §5/§8 govern **`temporal { … }` predicates over
> the event trace only**. A Cedar condition on the _current request's own_ datetime
> fields (or on `context.system.now`) has **no window cap and no past-only
> restriction** — however large the span, and whether the date is past or future.
> The discriminator is **what the rule reads, not how the NL sounds**: route to
> temporal only when the decision depends on **what happened in prior requests**
> (the event trace); a rule comparing datetime fields **carried by the current
> request**, or comparing them to `context.system.now`, is **Cedar**. So "365
> days", "12 months", "2 years", "90-day forward window" are all translatable
> Cedar — do **not** route such a rule out for mentioning the future or a horizon
> longer than a day. The contrast is exact and compiler-verified:
> `context.input.end_date.durationSince(context.input.start_date) < duration("730d")`
> **validates**, while the same horizon as a temporal window
> (`formerly within 365d …`) is **rejected** by the `max_window` cap.

These shapes need a field that `describe` types as `datetime` (or `context.system.now`).
A date that the schema types as `String` cannot be compared as a date: Cedar has no `<` /
`>` on strings, and `datetime(...)` takes only a string literal. This happens on **Lambda
targets with an inline tool schema**, which drop `format: date-time` (the field becomes
`String`), and on any tool that declares a date as a plain string. For such a field, a rule
that orders or measures dates ("before", "after", "within 30 days", "older than") is
**non-translatable** (reason: "the date field is a plain string in this schema"). Equality
with a date value matches only the exact text the client sends (`…T00:00:00Z` is not
`…T00:00:00.000Z` or `…+00:00`): write it only when the developer confirms that exact
format, otherwise route the rule non-translatable. Never emulate a date range with `like`.

The four in-scope Cedar datetime shapes (each compiler-verified):

```text
// 1. Time-of-day window on the clock — "between 8AM and 6PM"
when { context.system.now.toTime() >= duration("8h") && context.system.now.toTime() <= duration("18h") }

// 2. Absolute calendar cutoff — "on or after January 1, 2025"
when { context.system.now >= datetime("2025-01-01T00:00:00Z") }

// 3. Now-relative offset, INCLUDING future dates — "at most 90 days in the future"
when { context.input.end_date <= context.system.now.offset(duration("90d")) }
// equivalently: context.input.end_date.durationSince(context.system.now) <= duration("90d")

// 4. Cross-field span between two request dates, no clock at all — "spanning more than 12 months"
when { context.input.end_date.durationSince(context.input.start_date).toDays() > 365 }
// and plain field ordering: context.input.start_date <= context.input.end_date
```

**A field whose NAME mentions a time unit is a plain request field, not a temporal
window — and the comparison operand is chosen by the field's DECLARED TYPE, not by
the unit in its name.** NL like "lookback periods cannot exceed 24 months", "time
ranges not exceeding 48 hours", "lookback period is less than 7 days" is a
single-request field comparison; the 24h `max_window` cap and the "only
`s`/`m`/`h`/`d`" rule constrain **temporal windows** and `duration("…")` **literals**,
so neither applies — do not route these out for naming months or hours. Read the
field's type out of the action schema rather than pattern-matching its name: a field
declared `Long` compares to a **bare integer**, a field declared `duration` compares
to a **`duration("…")` literal** — and on a `duration`-typed field the literal's unit
is free (no 24h ceiling; that ceiling is a _temporal-window_ rule):

```text
// Field declared `Long` (e.g. lookback_months) — compare to a BARE INTEGER
when { context.input has lookback_months && context.input.lookback_months > 24 }        // PASS
when { context.input has lookback_months && context.input.lookback_months > duration("24h") }  // FAIL: expected Long but saw duration

// Field declared `duration` (e.g. time_range_hours) — compare to a DURATION LITERAL
when { context.input has time_range_hours && context.input.time_range_hours > duration("48h") }  // PASS
when { context.input has time_range_hours && context.input.time_range_hours > 48 }      // FAIL: expected duration but saw Long
```

Note a field named `time_range_hours` may be declared `duration` **despite** the
`_hours` suffix, so the `_hours`/`_months`/`_days` suffix predicts neither the type
nor the literal's unit — only the schema declaration does.

> **Four datetime shapes are NOT expressible — route them `non_translatable`, even
> though a plain date comparison is in scope.** The rescue above is for comparisons on
> a `datetime`/`duration` value (a request field or `context.system.now`). It does
> **not** rescue a rule that needs a calendar concept Dogwood has no operator for:
>
> 1. **Day-of-week / weekend / weekday.** "on weekends", "Saturday and Sunday", "only
>    on business days" — there is no weekday extraction; `.toTime()` yields the
>    time-of-day clock only, `.toDate()` a bare date, neither a day-of-week.
> 2. **Named holidays or a calendar blackout window.** "U.S. holidays", "German public
>    holidays", "when the Federal Reserve is closed", "the year-end period (Dec 26 –
>    Jan 2)" as a _recurring_ rule — these need an external holiday calendar. (A single
>    fixed date range compiled as `datetime(...)` bounds is fine; a rule that means
>    "every year's holidays" is not.)
> 3. **A wall-clock window pinned to a NAMED timezone.** "4:00 PM PST", "after 8:00 PM
>    Eastern Time", "market hours 9:30 AM–4:00 PM EST" — `.toTime()` compares against a
>    UTC clock and has no timezone conversion, and named US zones carry a
>    seasonal DST offset that cannot be represented. A **UTC** (or offset-free)
>    numeric time-of-day window (e.g. the `9h`–`15h` example above) **is**
>    translatable; only a named-timezone one is not.
> 4. **A named clock window with NO explicit numeric bounds in that condition.**
>    "during business hours", "after business hours", "after hours", "evening hours",
>    "nighttime" — when the NL gives no concrete clock bounds for the window _in the
>    same condition_, you would have to invent the hours, so it is out. This is out
>    **only** when the bounds are absent: if the same condition spells them out
>    ("business hours (9 AM to 5 PM)", "before 8:00 AM or after 5:00 PM"), the window
>    is translatable via `.toTime()` (still subject to shape 3 — a named timezone on
>    those bounds is a separate disqualifier).
>
> The discriminator stays the same — _what the rule reads_ — but a rule that reads a
> **weekday, a holiday calendar, a timezone-local clock, or a named clock window with
> no numeric bounds** reads something the value does not carry (or does not state), so
> it is out of scope regardless of being a "current-request" condition.

---

## 5. Temporal expressions (event history)

Use `when temporal { … }` when the decision depends on **what happened before** —
"in the last N units", counts of past events, cumulative sums. The body is a
past-only fragment of Metric First-Order Temporal Logic. It evaluates at the current
decision point against all prior events and yields a boolean.

### Predicates — describing a past event

```text
Namespace::Action::"ActionId"::kind{ field: pattern, … }
```

- The **`::kind`** suffix is **mandatory**. The decision event is `request` (the
  invocation). The history-only kinds are `response` (the result, carrying `output.*`
  fields) and `error` (emitted when the gateway/target call fails, carrying the
  failing call's `input.*`). A history-only event updates what temporal predicates
  can see but produces no verdict.
  In AgentCore, **every evaluated call records a `request` event**, also a call that a
  policy **denies**; a denied call, or one whose tool result has `isError`, also records
  an **`error`** event; only a call whose tool returns without an error records a
  `response` event (this says nothing about the result's content: a verification that
  returns `verified: false` is still a `response`), and
  whether `response` events are recorded also depends on the Gateway's enforcement mode
  (see `agentcore-service-rules.md`). So "was denied",
  "failed", "returned an error" are `::error`; a `::request` condition also matches a
  prerequisite that was denied or failed, and only `::response` shows that it completed.
  > **These event kinds and the reserved field names below (`eventPrincipal`,
  > `eventResource`, …) come from the event schema, which can change.** They are the
  > most likely part of this document to drift (the reserved names were themselves
  > renamed once). Treat the current event schema as authoritative and use the names
  > it declares; the examples here follow one specific event schema and illustrate the
  > _pattern_, not a fixed vocabulary. If a predicate names a field the event schema
  > does not declare, it will fail to compile — check the schema, not this page.
- **Fields the event schema `pin`s are ambient — never write them in a policy.** An
  event schema may declare a field with `pin`, e.g. the deployed schema's
  `pin sessionId: String = context.sessionId` on all three kinds. A `pin` silently adds
  that correlation to **every** predicate, so history is scoped per-session without any
  policy saying so. Write only the correlations the NL actually states and stay silent on
  pinned fields: naming one is a redundant no-op while it agrees, and a **hard error** if
  the schema later drops it (``predicate … mentions field `sessionId`, which is not declared
on that event``). Two consequences: a policy is deliberately _under-specified_ relative to its
  NL (an uncorrelated rate limit reads as "global" but is enforced per session), and a
  genuinely cross-session rule ("system-wide", "across all users") is **inexpressible**
  under a universal pin — flag it rather than approximating it. A `pin` also constrains
  the _scope_ — see "Scope requirements" below.
- Field patterns are `field_path : term`:
  - **Request correlation** — `input.user: context.input.user` forces the past event's
    field to equal the _current_ request's field (the workhorse for "the _same_ user").
    This is written **explicitly** in the policy, and is the opposite case from a
    schema `pin`, which applies the same kind of binding ambiently (see the bullet
    above). Throughout this document "pin"/"pinned" refers **only** to the event
    schema's `pin` keyword.
  - **Scope correlation** — `eventPrincipal: principal` and
    `eventResource: resource` correlate on the request's principal/resource entities.
    Use the bare scope entities `principal`/`resource` (Cedar's request variables), **not**
    `context.principal`/`context.resource` — there is no `context.principal` alias (that
    would name a field literally called `principal` in the context record). A trailing
    attribute reads that entity's attribute (`eventPrincipal: principal.dept`).
    **`eventResource: resource` is required in every event predicate** in AgentCore
    (`::request`, `::response` and `::error` alike, even a bare predicate:
    `…::request{ eventResource: resource }`; a service rule). Write it yourself in
    every predicate. `eventPrincipal: principal` stays optional: add it only
    when the NL ties the past event to the same caller.
  - **Value binding** — a bare name `input.amount: a` captures the value for later use.
  - **Literal** — a string (`input.stock: "AMZN"`), boolean (`output.result: true`),
    integer (`input.amount: 0`), decimal (`output.score: decimal("0.5")`), entity reference
    (`eventPrincipal: AgentCore::OAuthUser::"alice"`), or array (`input.tags: ["a","b"]`).
  - **Wildcard** — `input.amount: _` (or `*`) matches anything, binds nothing.

### The three past operators (all bounded, past-only)

Every operator carries a mandatory `within <interval>` window. Time units: `s`
(seconds), `m` (minutes), `h` (hours), `d` (days). No week/month/year.

**The window is also capped by the event schema, at 24h by default.** An event schema
may raise or lower the cap with a `max_window = <interval>` directive at the top of the
file; **absent that directive the cap is 24h**, and the deployed event schema
(`assets/agentcore.dwschema`) does not set one. So **24h is the longest usable window** (`24h`, `1d`, `1440m`, `86400s`
all pass) and a longer one is rejected even though `d` is a legal unit:
``temporal window `7d` exceeds the maximum allowed window `24h` set by the event schema's
`max_window` ``. If the NL asks for a longer horizon ("in the last 7 days", "this month"),
it is **not expressible** — flag it rather than silently shortening the window.

- **`formerly within W <atom>`** — held at _some_ point in the window ("did X ever
  happen in the last W?"). The most common operator.
- **`previous within W <atom>`** — held at the _immediately preceding_ event.
- **`<left> since within W <right>`** — `left` held continuously ever since `right`
  happened. The **"open session" idiom** uses a negated left:
  `!Logout{...} since within 24h Login{...}` = "no logout since the last login".

**`since` is a single atomic operator — never split it into `formerly` + `unless`.**
`A since within W B` means "B occurred within W **and** A has held at every point since
B"; it is **ordered**, with B as the anchor. The negated form `!Y since within W X` means
"X occurred within W and Y has **not** occurred at any point since X". When the NL says
"… since/after \<event\>, … has not happened" — e.g. "escalated within 24h and no approval
has been submitted since the escalation" — translate the **whole** condition as one
`since` predicate in a single `when temporal { … }` clause. Do **not** rewrite it as
`when temporal { formerly within W X } unless temporal { !Y since within W X }`: wrapping
the already-negated `since` in an `unless` double-negates it and **inverts the effect**,
so the rule fires on the "Y _did_ happen since" case — the exact opposite of the NL.
**Both forms compile**, so the validator will not catch this. Choose the operator by
whether **ordering** matters: `formerly within W E` = "E happened at least once in the
window" (order-free); `previous within W E` = "the immediately preceding event was E";
`since within W E` = "E is the anchor and the other condition holds continuously after
it" (order-sensitive). If the rule cares about what happened _after_ some anchor event,
it needs `since`, not `formerly`.

**"X is in progress" idiom** — "no new X while an earlier X (for the same order, repository,
…) is still running / has not yet completed / is in flight", "no concurrent X". A call
records `::request` when it is evaluated, `::response` only when it succeeds, and `::error`
when it fails or a policy denies it; a failed or denied X never records `::response`. So
`!X::response since within W X::request` alone treats a failed X as still running and
denies every later X in the session until W ends. Use the **split form**: one `since` for
"no response since the request" and one for "no error since the request", joined by `&&`,
with the same pins on all three event predicates. When X is the current action, wrap it in
`previous` (otherwise the current call's own `::request` makes it always true):

```text
forbid ( principal, action == AgentCore::Action::"Tools___run_scan", resource == AgentCore::Gateway::"<gateway-arn>" )
when temporal {
    previous within 30m (
        (!AgentCore::Action::"Tools___run_scan"::response{ input.repo: context.input.repo, eventResource: resource }
            since within 30m AgentCore::Action::"Tools___run_scan"::request{ input.repo: context.input.repo, eventResource: resource })
        && (!AgentCore::Action::"Tools___run_scan"::error{ input.repo: context.input.repo, eventResource: resource }
            since within 30m AgentCore::Action::"Tools___run_scan"::request{ input.repo: context.input.repo, eventResource: resource })
    )
};
```

When X is another action than the current one, drop `previous` and keep the two `since`.
Parenthesize each `since`. Do **not** write `(!X::response && !X::error) since …`: the
language accepts it, but the service does not (see `agentcore-service-rules.md`). The split form uses all 3 temporal operators of the policy (2 without
`previous`), so a rule that needs one more temporal condition cannot be expressed. Add
`eventPrincipal: principal` to all three predicates only when the NL ties the earlier X to the
same caller ("the same user already has …"). "X has not **succeeded** since it was requested"
(a failure counts as not succeeded) is a different rule: write `!X::response since within W
X::request` there.

The body of `formerly`/`previous` is an _atom_, so a conjunction **must be parenthesized
to fall inside the window**: `formerly within 1h (A && B)`. Omitting the parentheses is
**not** a syntax error — `formerly within 1h A && B` compiles — but `&&` binds _outside_
the operator, so only `A` is searched over the window while `B` is evaluated at the
current timepoint. Always parenthesize.

AgentCore accepts **at most 3 temporal operators per policy** (a service rule); `formerly`,
`previous`, `since`, `count` and `sum` all count (a `count` over a `formerly` body is two).
A rule that needs more is non-translatable as one policy.

### Connectives, binders, aggregations

- **Only `&&` and `!`** — there is **no `||`** _inside_ a `temporal { … }` block. For
  "A or B" you have two options: write two separate rules, or lift each disjunct into its
  own `temporal { … }` block and OR them with Cedar `||` in a bare `when` —
  `when { temporal { … A … } || temporal { … B … } }` (see §8).
- **Every conjunct inside `temporal { … }` must vary with the timepoint.** A plain Cedar
  condition is rejected there: `formerly within 1h A && context.input.doc == "x"` fails
  with ``this `when`/`unless` conjunct does not vary with the current timepoint; it
monitors nothing``. To combine a history condition with a property of the current
  request, keep the Cedar part in a **bare** `when { … }` — either
  `when { context.input.doc == "x" && temporal { formerly within 1h A } }` or a separate
  `when { … }` clause alongside the `when temporal { … }` clause. Both validate.
- **`exists (x: T). φ`** — the sole quantifier; `x` must be range-restricted by a
  positive atom in `φ` (a predicate field, a `tp`, or an `==` binding).
- **`tp(t)`** — binds the current timepoint; used inside aggregations to range over
  distinct timepoints.
- **`count for (g: T), …. where φ`** and **`sum v for (g: T), …. where φ`** — the
  only two aggregations (no min/max/avg). **`sum` sums `Long` (integer) values only,
  so whether a `sum` is allowed is decided by the summed field's declared type in the
  action schema:** look the field up — a `context.input.<field>` typed `Long` is
  summable, but one typed `decimal` is NOT, and a `sum` over a `decimal` field is
  **non-translatable** (the service rejects it; see `agentcore-service-rules.md`). In the §2 schema
  above, `TransferInput.amount` is `Long` (summable) while `TransferOutput.proceeds` is
  `decimal` (a `sum` over it is non-translatable). This is a schema-type check, not an
  NL-wording judgment. An aggregate may appear **only** as an
  immediate comparison operand: `(agg) == n`, `(agg) > 2`. It may **not** feed
  arithmetic (`(agg) + 1 == n` → ``unexpected token `+`, expected comparison operator``)
  or stand alone as a boolean (`unexpected end of input, expected comparison operator`).
  Wrapping it in parentheses is _optional_ — both `(agg) == n` and `agg == n` compile —
  but parenthesize anyway for readability. **Order matters, though:** the `== n`
  conjunct that _binds_ the variable must come **before** any conjunct that filters on
  it, so write `(agg) == n && n > 2`, never `n > 2 && (agg) == n` (the latter fails with
  ``variable `n` is used in a filter … that is not range-restricted by a preceding
conjunct``).

**The group type decides what gets counted — EVENTS or DISTINCT VALUES.** `count for
(t: Timepoint)` with a `tp(t)` binder counts **events** ("more than 5 transfers");
`count for (v: String)` grouped on a field binding counts **distinct values** of that
field ("transfers to more than 5 _different_ destination accounts"). Ten transfers to
one account is 10 events but 1 distinct value, so the two are not interchangeable. The
distinct-value form binds the field inside the event body and needs **no** `tp(t)`
binder and no second `(t: Timepoint)` group:

```dogwood
forbid ( principal, action == AgentCore::Action::"Tools___transfer_between_accounts", resource == AgentCore::Gateway::"<gateway-arn>" )
when temporal {
    exists (n: Long). (
        (count for (acct: String). where (
            formerly within 24h AgentCore::Action::"Tools___transfer_between_accounts"::request{
                eventResource: resource,
                input.destination_account_id: acct,
                eventPrincipal: principal
            }
        )) == n && n > 5
    )
};
```

Everything else is unchanged: the `where` body still needs its `formerly within W`
wrapper to scan history, and the binding `== n` conjunct still precedes the `n > K`
filter. This is a different thing from counting distinct **guardrail categories**
("more than 4 different types of PII"), which is _not_ expressible — see §6.

**Two aggregation gotchas — get these wrong and the policy is behaviorally dead
or off by one:**

1. **A rate/cumulative aggregation MUST wrap its `where` body in `formerly within
W (… && tp(t))`.** The wrapper is what scans history; a **bare** body — `where
(P::request{…} && tp(t))` with _no_ `formerly within` — counts/sums **only the
   current timepoint** and never accumulates, so the threshold never trips (the
   count is always ~1). Bare aggregation is legitimate **only** for a
   current-instant intent ("how many right now", "none concurrently" via `== 0`);
   for anything phrased "within the last W / more than N in total / per day", the
   `formerly within W` wrapper is mandatory.
2. **`formerly within` counts the CURRENT request.** It is evaluated at the
   current in-window timepoint, so the count/sum **includes the current action's
   own `::request`** event. Therefore _"already N prior X"_ means the current
   request is the **(N+1)th** → use **`n > N`** (`n >= N+1`), not `n >= N`. "Has already
   done **more than N**" uses the same threshold, `n > N`: do not add a second 1.
   **Default the aggregation to `::request`** (a rate/cumulative limit counts the
   _calls_: AgentCore records a `request` event for every evaluated call, including
   the current one, calls that a policy denied and calls whose tool failed; a
   `::response` count misses calls that failed or were denied).
   Use `::response` only
   when the NL is specifically about **completed / successful** actions or an
   **output value**; a `::response` count **excludes** the current action (it
   has not resolved at its own decision point), so _"N already completed"_ over
   `::response` uses `n >= N`. To count **denied or failed** calls ("after 3
   denied refunds", "after N failed logins"), count the history-only `::error`
   kind (see the event-kinds note above); it also excludes the current call.

Comparisons in temporal: `< <= > >= == !=`. The **ordered** comparisons (`< <= > >=`)
work only on `Long` inside `temporal { … }`: a `decimal` or `String` operand is rejected
(`comparison requires numeric operands on both sides`), and the decimal methods
cannot be used there (``unexpected token `.` ``). A `decimal` field can still be matched
by equality (`input.amount: decimal("10.0")`); outside `temporal`, order decimals with
the methods. `!=` **is** available on bound variables
(`a != 5`, `s != "AMZN"`, `p != principal`); `!(x == y)` is an equivalent spelling. What
is _not_ allowed is `!=` in **field-pattern** position — `input.doc: != "x"` is a parse
error, because a pattern takes a term, not a comparison; bind the field first
(`input.doc: d`) and compare `d` in the surrounding formula. An `==` with exactly one
unbound variable operand **binds** it — the mechanism behind `(agg) == n && n > 2`.

### Scope requirements for a temporal policy

Two constraints come from the **scope triple**, not from the body. Both report errors that
look unrelated to the scope, so check them first when a temporal policy is rejected.

**1. Every action the scope names must declare the fields the event schema `pin`s.** A
pin's right-hand side reads the _current request's_ context, so with the deployed
`pin sessionId: String = context.sessionId`, each scoped action needs
`sessionId: String` in its `context` — otherwise:
``action `Ns::X` has no context field `sessionId` for `context.sessionId` ``. The check
follows the scope: `action == X` requires it on `X`. The action named in the _predicate_ (the
historical event) does **not** need it, and non-temporal policies are unaffected. This is
a property of the schemas you are given, not something to fix in the policy — never write
the pinned field into the predicate.

**2. Scope a temporal policy to exactly one action, with `action ==`.** AgentCore
rejects `action in [...]` (a list) and `action in <group>` together with temporal
conditions, in both validation modes ("A policy scoped with `action in` cannot contain
temporal conditions"). A group also fails in the compiler:
``for policy `policy_0`, attribute `policy_0__temporal_0` in context for
Ns::Action::"<member>" not found``. For a rule over several actions, write one policy
per action. (Group and list scopes are fine for plain-Cedar policies; this restriction
is temporal-only.)

### Worked temporal examples (validated)

**Write-after-read** — "permit a Write only if this user read this document in the
last hour":

```text
permit ( principal, action == AgentCore::Action::"Tools___Write", resource == AgentCore::Gateway::"<gateway-arn>" )
when temporal {
    formerly within 1h AgentCore::Action::"Tools___Read"::request{
        eventResource: resource,
        input.user: context.input.user,
        input.document: context.input.document
    }
};
```

**Cumulative sum threshold** — "forbid a transfer if more than $1000 has been
transferred in the last 24 hours" (this works **only because the schema declares
`input.amount` as `Long`**; if that field were typed `decimal`, the sum would silently
drop its decimal values and the rule would be **non-translatable** — the summed field's
declared schema type decides, not the NL wording):

```text
forbid ( principal, action == AgentCore::Action::"Tools___Transfer", resource == AgentCore::Gateway::"<gateway-arn>" )
when temporal {
    exists (total: Long). (
        (sum a for (a: Long), (t: Timepoint). where (
            formerly within 24h (AgentCore::Action::"Tools___Transfer"::request{ eventResource: resource, input.amount: a } && tp(t))
        )) == total && total > 1000
    )
};
```

**Count threshold** — "flag if more than 2 logins to this server in the last hour":

```text
when temporal {
    exists (n: Long). (
        (count for (t: Timepoint). where (
            formerly within 1h (AgentCore::Action::"Tools___Login"::request{ eventResource: resource, input.user: _, input.server: context.input.server } && tp(t))
        )) == n && n > 2
    )
};
```

The `where` body **must** be wrapped in `formerly within W (… && tp(t))` — that
is what makes the count accumulate over the window. A **bare** body (no
`formerly within`) counts only the current timepoint and never accumulates, so a
rate/cumulative limit written that way is behaviorally **dead** (see the
aggregation caveat above). Because `formerly within` is evaluated at the current
in-window timepoint, the count **includes the current request**: "more than 2 in
the last hour" is `n > 2`, and the current login is the one that makes the count
reach 3.

**Self-cooldown ("no repeat of the same action within W") — use a `count`, NOT a
bare self-`formerly`.** A `forbid` on action X must **never** reference X's own
`::request` directly under `formerly within` — because `formerly within` includes
the current timepoint, the current request matches itself, so the rule fires on
**every** request including the very first (a broken cooldown). "Deny a share if
the same user has **already** shared within the past 5 minutes":

```text
forbid ( principal, action == AgentCore::Action::"Tools___share_records", resource == AgentCore::Gateway::"<gateway-arn>" )
when temporal {
    exists (n: Long). (
        (count for (t: Timepoint). where (
            formerly within 5m (AgentCore::Action::"Tools___share_records"::request{ eventResource: resource, eventPrincipal: principal } && tp(t))
        )) == n && n >= 2
    )
};
```

`n >= 2` = "at least one prior **plus** the current", so the first share (count 1)
is allowed and any repeat within 5m (count ≥ 2) is denied. If the NL instead says
the _immediately preceding_ action must not be the same ("consecutive /
back-to-back"), use **`previous`** — that operator checks strict adjacency and does
**not** self-match, so no count is needed. The event just before the current call is
the prior call's **outcome**: `::response` after a success, `::error` after a failure
or a policy denial (its `::request` is earlier). So "the immediately preceding action
was X" is two blocks:
`when { temporal { previous within W X::response{…} } || temporal { previous within W X::error{…} } }`
(only `::response` for "succeeded", only `::error` for "failed / denied"). Never write
`previous within W X::request{…}` alone: it matches only while X is still running.
Add it as a third block only when a still-running X must count too (3 temporal
operators, the limit). (The
`WRONG: when temporal { formerly within 5m …"share_records"::request{ … } }` form
denies the first share and is the most common cooldown bug.)

**"Unless recently approved" idiom** — pairs a `forbid ... when temporal` with an
`unless temporal` escape hatch (this is the canonical prompt example: block transfers
over $1000/24h **unless** admin_verification ran in the last 5 minutes):

```text
permit ( principal, action == AgentCore::Action::"Tools___Transfer", resource == AgentCore::Gateway::"<gateway-arn>" );

forbid ( principal, action == AgentCore::Action::"Tools___Transfer", resource == AgentCore::Gateway::"<gateway-arn>" )
when temporal {
    exists (total: Long). (
        (sum a for (a: Long), (t: Timepoint). where (
            formerly within 24h (AgentCore::Action::"Tools___Transfer"::request{ eventResource: resource, input.amount: a } && tp(t))
        )) == total && total > 1000
    )
}
unless temporal {
    formerly within 5m AgentCore::Action::"Tools___admin_verification"::request{ eventResource: resource, eventPrincipal: principal }
};
```

These are two policies; when an existing permit already covers the callers, write only
the `forbid`.

**Unlock after repeated denials** — "allow `request_supervisor` only after `refund`
was denied 3 times in the last hour". A denial is an `::error` event; an existing
permit covers the callers, so only the `forbid` is written:

```text
forbid ( principal, action == AgentCore::Action::"Tools___request_supervisor", resource == AgentCore::Gateway::"<gateway-arn>" )
unless temporal {
    exists (n: Long). (
        (count for (t: Timepoint). where (
            formerly within 1h (AgentCore::Action::"Tools___refund"::error{ eventResource: resource } && tp(t))
        )) == n && n >= 3
    )
};
```

**Disjunction of history conditions** — since `||` is not allowed _inside_ one
`temporal { … }` block, put each history claim in its own block and OR them with Cedar
`||` in a bare `when` ("permit if the user logged in OR was approved in the last hour"):

```text
permit ( principal, action == AgentCore::Action::"Tools___Transfer", resource == AgentCore::Gateway::"<gateway-arn>" )
when {
    temporal { formerly within 1h AgentCore::Action::"Tools___Login"::request{ eventResource: resource, input.user: context.input.user } }
    || temporal { formerly within 1h AgentCore::Action::"Tools___Approve"::request{ eventResource: resource, input.user: context.input.user } }
};
```

---

## 6. Bedrock Guardrails (information providers)

In Dogwood, Bedrock Guardrails are **information providers**: content-safety
computations invoked as ordinary Cedar calls. In AgentCore policies they go inside a
`when guardrails { … }` clause, the documented form (the body is ordinary Cedar, so
plain conditions may be combined with them). There are three,
declared in the provider schema:

| Provider                                  | Purpose                 | Output keyed by                                              |
| ----------------------------------------- | ----------------------- | ------------------------------------------------------------ |
| `BedrockGuardrails::ContentFilter`        | content moderation      | category → `{ confidenceScore: decimal }`                    |
| `BedrockGuardrails::PromptAttack`         | prompt-attack detection | category → `{ confidenceScore: decimal }`                    |
| `BedrockGuardrails::SensitiveInformation` | PII detection           | entity type → `{ confidenceScore: decimal, count: integer }` |

Default a guardrail-shaped rule to TRANSLATABLE **when its inspect field resolves to a schema-declared `context.input.<field>`** (see the field-resolution rule below). If a rule invokes a declared Bedrock Guardrails category/entity (content-safety, prompt-attack, PII) on such a field, it is translatable regardless of: whether the threshold is ">="/">"/"<="/"<" or absent (use the per-provider default) or stated as an exact value (still translatable — render an exact-value threshold as an ordering comparison, never `==`/`!=`); whether it is phrased as confidence, risk level, or severity level; whether it is a "permit … as long as < t" exception; or whether it combines two categories with plain AND/OR (`A && B`, `A || B` — both checked in the same request). Route it non-translatable for a genuine structural gap: an undeclared category/entity; a field reachable only through a list/set index (this skill does not use `$`-paths; see `agentcore-targets-and-effects.md`, Guardrail scope); **one category's result gating or triggering a check on a _different_ category** (a conditional dependency between providers — see "Cross-category gating" below); or **counting distinct detection types** ("more than N different types of PII"). **Route it non-translatable ALSO when it names no field to inspect, or names a field that resolves to no declared `context.input.<field>`** — a rule that says only "if X **is detected**", "found **in the input**", or "block **any/all request(s)** containing X", pointing at no field, is `non_translatable`. There is **no default whole-input inspect path**: the inspect field must resolve to a real schema field or the rule is out of scope.

### Invocation shape

Each provider takes **two `set<string>` arguments** — `(categories, textToInspect)` —
and returns a record keyed by category. You project into a category, then compare:

```text
BedrockGuardrails::ContentFilter(["MISCONDUCT"], [context.input.reason])
    ["MISCONDUCT"].confidenceScore.greaterThan(decimal("0.2"))
```

- **Argument 1** is the set of categories/entity types to check: `["MISCONDUCT"]`.
- **Argument 2** is the field(s) to inspect, wrapped in a set:
  `[context.input.reason]`. Each field path must name a **scalar** text field: a field
  path to a list or set (for example a `Set<String>` or `Set<record>` field) is not
  accepted (a service rule). A string inside a nested record is a normal path
  (`[context.input.address.note]`). Text that is only inside a list or a set needs a JSONPath string (`"$.…"`),
  which this skill writes only on inference, HTTP and Runtime targets (see
  `agentcore-targets-and-effects.md`, Guardrail scope); on MCP targets the rule is non-translatable. A call whose paths resolve to
  nothing (for example an optional field that the request omits) **denies the
  request**.
- **Argument 2 must resolve to a schema-declared `context.input.<field>` — there is
  NO default whole-input inspect path.** Resolve the field the NL points at against
  the scoped action's `context.input`:
  - **Exact / reformatting match** — the NL field name equals a declared field up to
    case, underscore/camelCase, or a clear abbreviation ("incident description" →
    `context.input.incident_description`; "msg" → `context.input.message` _if the
    schema declares `message`_). This is the same strict, unambiguous matching used
    for every field (see §2) — **surface reformatting of the same word only, never a
    synonym** ("comment" does not match `content`, "justification" does not match
    `reason`).
  - **No match** — if the NL names no field at all ("if X **is detected**", "found
    **in the input**", "block **any/all request(s)** containing X"), or names a field
    that resolves to no declared `context.input.<field>` under that strict test, the
    rule is **`non_translatable`**. Do **not** fall back to a guessed field, and do **not**
    invent a `context.input.message` (or any other) path the schema does not declare.

  Inspect the matched field as argument 2:

  ```text
  // NL: "Block Refund requests if the incident_description field contains misconduct"
  //   (named field with an exact schema match → inspect that field)
  forbid ( principal, action == AgentCore::Action::"Tools___Refund", resource == AgentCore::Gateway::"<gateway-arn>" )
  when guardrails {
      BedrockGuardrails::ContentFilter(["MISCONDUCT"], [context.input.incident_description])
          ["MISCONDUCT"].confidenceScore.greaterThanOrEqual(decimal("0.2"))
  };
  ```

  The choice of _which field to inspect_ (argument 2) is independent of the
  _projection style_: for **SensitiveInformation** always use the aggregate
  `.maxConfidenceScore()` (see the SI rule below); the bracket form
  `["CAT"].confidenceScore` is for ContentFilter / PromptAttack only.

- **Projection** selects the category record: `["MISCONDUCT"]`. The **projection key**
  must be one of the declared keys — `["NOTACAT"].confidenceScore` is a hard error.
  **Argument 1 is not validated by the compiler**, so
  `ContentFilter(["NOTACAT"], …).maxConfidenceScore()` compiles clean, but the service
  does not accept it. Spell every category exactly as listed in the vocabularies below.
- **Provider arguments are not type-checked against the action schema.** Any path in
  argument 1 or 2 is accepted by the _compiler_ — an undeclared field, a `Long` or `Bool`
  field, even a bare string literal or an entity — so a **wrong** argument 2 is never
  caught: getting the inspect path right is on the translator, not the compiler. That the
  compiler would accept an undeclared path is **not** license to emit one — argument 2
  must still resolve to a declared `context.input.<field>` (see the field-resolution rule
  above), because an unanchored inspect path silently inspects nothing. The same path in a
  plain Cedar condition **is** checked (`when { context.input.reason == "x" }` fails when
  `reason` is undeclared).
- **SensitiveInformation is always aggregated — never bracket-projected.** For
  `BedrockGuardrails::SensitiveInformation`, do **not** use the bracket form
  `["ENTITY"].confidenceScore`; always collapse to a scalar with an aggregate method
  — `.maxConfidenceScore()` (or `.minConfidenceScore()`). The reason is semantic, not a
  type constraint: a sensitive-information entity type can match **multiple times** in one
  input (e.g. two emails in a message), so a single indexed score is not meaningful and
  the aggregate is the only well-defined scalar to threshold against. **The compiler will
  not stop you** — SI's declared output _is_ a record keyed by entity type, so both
  `["EMAIL"].confidenceScore` and `["EMAIL"].count` compile — but the **service rejects**
  it (see `agentcore-service-rules.md`). Bracket projection is for
  ContentFilter / PromptAttack (one verdict per category); SensitiveInformation is
  the exception.
- **`confidenceScore` is a `decimal`**, so compare it with the decimal methods
  (`.greaterThan`, `.greaterThanOrEqual`, `.lessThan`, `.lessThanOrEqual`), **not**
  `>`/`<`. ("at most t" is `.lessThanOrEqual(decimal("t"))`; "at least t" is
  `.greaterThanOrEqual(...)`.)
- **Never threshold a score with `==` or `!=` — always use an ordering comparison.**
  Cedar _does_ permit decimal equality, so `["HATE"].confidenceScore == decimal("0.9")`
  compiles and the validator will not stop you. But AgentCore returns scores in
  discrete steps of 0.2 (`0.0`, `0.2`, `0.4`, `0.6`, `0.8`, `1.0`), so an `==` on a value
  between the steps (`0.9`, `0.5`) never fires and its `!=` always fires, and an `==` on
  a step value matches that one step only — the rule is behaviorally dead (or always
  live) rather than wrong-by-a-little. Even NL that sounds exact — "at confidence 0.9",
  "when the score is 0.5", "exactly medium risk" — means a **threshold**, so render it
  with an ordering method:

  ```text
  BedrockGuardrails::ContentFilter(["HATE"], [context.input.reason])
      ["HATE"].confidenceScore.greaterThanOrEqual(decimal("0.9"))
  ```

### A guardrail policy names exactly one action

A guardrail provider call is an ordinary Cedar expression to the compiler, but AgentCore
needs **exactly one named action** in a guardrail policy (`action == …`; why, and what
happens with a bare action, a group or a list: see `agentcore-service-rules.md`, Scope). So a rule that does not name a specific action becomes one policy for **each action
whose input declares the field** it inspects. A rule that names no inspectable
**field** is still `non_translatable`: argument 2 must resolve to a declared
`context.input.<field>` (see the field-resolution rule above), so "**Deny any
request** if a prompt attack is detected" — no action _and_ no field — is
`non_translatable`. When the NL does name a field the schema declares:

```text
// NL: "For any action, block if the reason field shows a jailbreak"
//   (one such policy for every tool whose input declares `reason`)
forbid ( principal, action == AgentCore::Action::"Tools___Refund", resource == AgentCore::Gateway::"<gateway-arn>" )
when guardrails {
    BedrockGuardrails::PromptAttack(["JAILBREAK"], [context.input.reason])
        ["JAILBREAK"].confidenceScore.greaterThanOrEqual(decimal("0.4"))
};
```

### Scope qualifiers in a guardrail rule are NOT Cedar conditions and are NOT schema-validated

In a rule whose condition is a Bedrock Guardrails check, a **principal /
user-role / identity label** ("admin users", "'analyst' OAuthUser", "non-admin
users", "IamEntity 'X'") and a **server / gateway reference** ("on the production
gateway", "on the 'internal' server") are **pure scope qualifiers**, not
translatable conditions and not fields to inspect. Accept them **as-is**: do
**not** validate them against the ACTION_SCHEMA, and do **not** route the rule
non-translatable because such a label has no matching schema entity. **Only the
action is schema-validated** (with flexible semantic matching, same as any rule).

Render the qualifier into the scope triple when it maps cleanly to a schema
principal/resource type or a literal id from the NL; otherwise **leave that slot
bare** and keep the rule translatable — the guardrail check is what matters. The
resource slot is the exception: it is always the context's Gateway,
`resource == AgentCore::Gateway::"<gateway-arn>"`, whatever gateway or server name the
NL uses (there is no `AgentCore::Server` type).

### Category vocabularies

- **ContentFilter:** `VIOLENCE`, `HATE`, `SEXUAL`, `MISCONDUCT`, `INSULTS`.
- **PromptAttack:** `JAILBREAK`, `PROMPT_INJECTION`, `PROMPT_LEAKAGE`.
- **SensitiveInformation:** `ADDRESS`, `AGE`, `EMAIL`, `NAME`, `PHONE`, `PASSWORD`,
  `USERNAME`, `URL`, `IP_ADDRESS`, `CREDIT_DEBIT_CARD_NUMBER`,
  `US_SOCIAL_SECURITY_NUMBER`, `CA_HEALTH_NUMBER`, `CA_SOCIAL_INSURANCE_NUMBER`,
  `AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, `PIN`, `SWIFT_CODE`, and more (see the provider
  file for the full list). Each entity carries **both** `confidenceScore` (decimal)
  and `count` (integer); use the aggregate methods only.
- The authority for every list is the provider schema (`guardrail_providers.categories`);
  any other name is not accepted (for example `ACCOUNT_NUMBER`; use
  `US_BANK_ACCOUNT_NUMBER` or `INTERNATIONAL_BANK_ACCOUNT_NUMBER`).

### Effect: block vs. allow

Map the NL intent to the rule effect:

- **"Block / do not allow if detected"** → `forbid ... when { <guardrail> >= threshold }`.
- **"Allow if …"** → `permit ... when { <guardrail> … }`.
- **"Permit X as long as / provided that confidence stays below t"**
  (permit-with-guardrail-exception) → `permit ... when { <guardrail>.lessThan(decimal("t")) }`.
  This is translatable — a `permit` gated by an upper-bound guardrail check:

  ```text
  // NL: "Permit refunds as long as hate-speech confidence stays below 0.4"
  //   (exact threshold given → use it verbatim; "below" → the strict `.lessThan`)
  permit ( principal, action == AgentCore::Action::"Tools___Refund", resource == AgentCore::Gateway::"<gateway-arn>" )
  when guardrails {
      BedrockGuardrails::ContentFilter(["HATE"], [context.input.reason])
          ["HATE"].confidenceScore.lessThan(decimal("0.4"))
  };
  ```

### Threshold mapping

The deprecated JSON used `threshold` + `comparisonOperator`. Map directly:

| JSON operator      | Dogwood decimal method                                                           |
| ------------------ | -------------------------------------------------------------------------------- |
| `GREATER_THAN`     | `.greaterThan(decimal("t"))`                                                     |
| `GREATER_OR_EQUAL` | `.greaterThanOrEqual(decimal("t"))`                                              |
| `LESS_THAN`        | `.lessThan(decimal("t"))`                                                        |
| `LESS_OR_EQUAL`    | `.lessThanOrEqual(decimal("t"))`                                                 |
| `EQUAL`            | `.greaterThanOrEqual(decimal("t"))` — no faithful equality form; never emit `==` |
| `NOT_EQUAL`        | `.greaterThanOrEqual(decimal("t"))` — no faithful equality form; never emit `!=` |

The threshold must be a numeric decimal between 0 and 1. Derive it as follows,
in priority order:

1. **Exact numeric threshold given** ("… above 0.75 …") → use that value verbatim
   (`decimal("0.75")`), clamped to the 0–1 range.
2. **Semantic threshold given** ("low / medium / high risk", or wording that means
   the same — use judgment, the exact keyword need not appear) → map, the **same
   across all three providers**:

   | Semantic level | Decimal |
   | -------------- | ------- |
   | Low            | `0.4`   |
   | Medium         | `0.6`   |
   | High           | `0.8`   |

3. **No threshold given** ("… must be blocked when a prompt attack is identified in
   the reason field", "block action Y if X is detected in the reason field") → a
   missing _threshold_ does **not** make the rule non-translatable — do **not** route
   it out for lacking a number; use the **per-provider default** below. (A missing
   _inspect field_ is a different matter — that DOES make the rule non-translatable;
   see the field-resolution rule in §6.)

   | Provider                                  | Default |
   | ----------------------------------------- | ------- |
   | `BedrockGuardrails::ContentFilter`        | `0.2`   |
   | `BedrockGuardrails::PromptAttack`         | `0.4`   |
   | `BedrockGuardrails::SensitiveInformation` | `0.2`   |

The default operator, when the NL states none, depends on the effect:

- **`forbid`** (block when the content is detected) → `.greaterThanOrEqual` with the
  derived threshold.
- **`permit`** (allow only when the content is NOT detected) → `.lessThan`, the exact
  complement of the forbid check (see [Effect: block vs. allow](#effect-block-vs-allow)).
  Never default a `permit` to `.greaterThanOrEqual`: that would allow the request only
  when the content IS detected.

A strict bound stated in the NL overrides the default: "higher than", "above", "more
than", "exceeds" → `.greaterThan`; "below", "less than" → `.lessThan`. Use
`.lessThanOrEqual` only for "at most" or "no more than".

Scores come back in discrete steps of 0.2 (`0.0`, `0.2`, …, `1.0`), so a threshold only
matters where it falls between two steps: `.greaterThan(decimal("0.4"))` fires from
`0.6`, and `.greaterThan(decimal("0.5"))` fires from `0.6` too. Still copy the NL's
number verbatim; do not round it to a step.

> **"Risk level" and "severity level" are the same knob.** A policy phrased with a
> `confidenceScore` threshold, a `severityScore` threshold, or a `low/medium/high`
> **risk level** _or_ **severity level** on a declared guardrail category is
> translatable — all of them derive a numeric threshold by the rules above
> (semantic level → the low/medium/high map; a bare number → verbatim). The
> providers expose a single `confidenceScore` leaf, so compare against **that**
> projection regardless of whether the NL said "confidence", "risk", or
> "severity"; there is no separate `severityScore` field to read.

### Output methods (aggregations over categories)

Instead of projecting one category, you may call an aggregate **method** on the
provider output:

- `.maxConfidenceScore()` / `.minConfidenceScore()` → `decimal`
- `.count()` → `integer`
- `.categories()` → `set<string>`

```text
// NL: "Block the request if violence or hate speech scores above 0.45"
//   (exact threshold given → use it verbatim; "above" → the strict `.greaterThan`)
BedrockGuardrails::ContentFilter(["VIOLENCE","HATE"], [context.input.prompt])
    .maxConfidenceScore().greaterThan(decimal("0.45"))
```

When a call names several categories, the bracket form screens only the category it
indexes: `ContentFilter(["VIOLENCE","HATE"], …)["VIOLENCE"]…` leaves `HATE` unscreened.
Index every named category (joined with `||`) or use `.maxConfidenceScore()`.

### Worked guardrail examples (validated)

**Content misconduct (block)** — "prevent misconduct in the refund reason field with
severity above 0.2":

```text
forbid ( principal, action == AgentCore::Action::"Tools___Refund", resource == AgentCore::Gateway::"<gateway-arn>" )
when guardrails {
    BedrockGuardrails::ContentFilter(["MISCONDUCT"], [context.input.reason])
        ["MISCONDUCT"].confidenceScore.greaterThan(decimal("0.2"))
};
```

**Prompt attack (one rule per category)** — "block jailbreak at 0.7 or above, prompt
injection at 0.65 or above, and prompt leakage at 0.55 or above". Each category names
its own number, so each gets its own rule, and each rule copies **that category's**
threshold from the NL:

```text
forbid ( principal, action == AgentCore::Action::"Tools___Refund", resource == AgentCore::Gateway::"<gateway-arn>" )
when guardrails { BedrockGuardrails::PromptAttack(["JAILBREAK"], [context.input.reason])
        ["JAILBREAK"].confidenceScore.greaterThanOrEqual(decimal("0.7")) };

forbid ( principal, action == AgentCore::Action::"Tools___Refund", resource == AgentCore::Gateway::"<gateway-arn>" )
when guardrails { BedrockGuardrails::PromptAttack(["PROMPT_INJECTION"], [context.input.reason])
        ["PROMPT_INJECTION"].confidenceScore.greaterThanOrEqual(decimal("0.65")) };

forbid ( principal, action == AgentCore::Action::"Tools___Refund", resource == AgentCore::Gateway::"<gateway-arn>" )
when guardrails { BedrockGuardrails::PromptAttack(["PROMPT_LEAKAGE"], [context.input.reason])
        ["PROMPT_LEAKAGE"].confidenceScore.greaterThanOrEqual(decimal("0.55")) };
```

**PII in a memo (block a CA health number at high confidence):**

```text
forbid ( principal, action == AgentCore::Action::"Tools___Refund", resource == AgentCore::Gateway::"<gateway-arn>" )
when guardrails {
    BedrockGuardrails::SensitiveInformation(["CA_HEALTH_NUMBER"], [context.input.reason]).maxConfidenceScore()
        .greaterThanOrEqual(decimal("0.8"))
};
```

**Combining a guardrail with a plain condition:**

```text
forbid ( principal, action == AgentCore::Action::"Tools___Refund", resource == AgentCore::Gateway::"<gateway-arn>" )
when guardrails {
    context.input.amount > 100
    && BedrockGuardrails::ContentFilter(["MISCONDUCT"], [context.input.reason])
        ["MISCONDUCT"].confidenceScore.greaterThan(decimal("0.2"))
};
```

**Conjunction of two guardrail checks** — "block if **both** hate speech **and** an
email address are detected". Two provider calls conjoined with `&&`; translatable.
Neither clause states a threshold, so **each takes its own provider default** —
ContentFilter `0.2` and SensitiveInformation `0.2` — not a semantic level (nothing in
the NL says low/medium/high):

```text
forbid ( principal, action == AgentCore::Action::"Tools___Refund", resource == AgentCore::Gateway::"<gateway-arn>" )
when guardrails {
    BedrockGuardrails::ContentFilter(["HATE"], [context.input.reason])
        ["HATE"].confidenceScore.greaterThanOrEqual(decimal("0.2"))
    && BedrockGuardrails::SensitiveInformation(["EMAIL"], [context.input.reason]).maxConfidenceScore()
        .greaterThanOrEqual(decimal("0.2"))
};
```

### NOT translatable: cross-category gating and counting distinct types

Two guardrail categories combined by **plain AND/OR** (both checked in the same
request, as above) are translatable. But two narrower patterns are **NOT** —
route them `non_translatable`:

1. **Cross-category gating** — one category's result is used as a **condition that
   gates or triggers** a check on a _different_ category. This is a conditional
   dependency between providers, not a conjunction:
   - "Permit PII **only when no** jailbreak is detected" / "Allow addresses in logs
     **only when no** hate speech is also present"
   - "**If** prompt injection fires above 0.8, **also scan** for violence at a
     lowered threshold of 0.4"

   These make the _decision about category B_ depend on _whether category A fired_,
   which the provider model cannot express (each provider call independently
   compares one category's score against a fixed threshold). Note this is distinct
   from a plain `permit … when { A && !B }` over two categories in one request —
   the tell is a **triggering/gating dependency** ("only when no", "if X then also
   check Y"), not a static conjunction.

2. **Counting distinct GUARDRAIL CATEGORIES** — the rule counts _how many different
   categories/entities_ fired, rather than checking specific ones:
   - "if **more than 4 different types** of sensitive information are found"
   - "either hate speech OR **more than 2 different PII types**"
   - "the **count of detected SI entities across all fields exceeds 5**"

   No operator counts distinct categories-fired across providers, so this is not
   expressible even though each individual category check would be.

   This carve-out is limited to **guardrail** categories/entity types. Counting
   distinct **values of a declared schema field** — "transfers to more than 5
   different destination accounts", "records for more than 10 distinct patients" —
   **is** translatable, via `count for (v: String)`; see the distinct-value
   aggregation in §5. The distinction is _what is counted_: values of a
   `context.input.<field>` (translatable) versus which detectors fired (not).

---

## 7. Putting it together — a translation recipe

1. **Read the schema.** Identify the action(s) the NL policy targets, the exact
   `Namespace::Action::"Id"` names, the principal/resource entity types, and the
   `context.input.<field>` paths.
2. **Pick the effect.** "allow/permit only if" → `permit`; "block/deny/never/must not"
   → `forbid`. How existing policies change the choice: `agentcore-service-rules.md`
   (Before you write) and `document-authoring.md`.
3. **Set the scope.** Constrain `action ==` (or `in [...]`) to the targeted action(s);
   a temporal or guardrail policy takes `action ==` with one action (§5, §6).
   Constrain `principal` only if the policy names a user/role. Leave the principal slot
   bare otherwise. The resource is always `resource == AgentCore::Gateway::"<gateway-arn>"`.
4. **Classify the condition:**
   - Property of the current request → **Cedar** `when { … }`.
   - Depends on time-of-day / a date window → **Cedar datetime** (`context.system.now`).
   - Depends on past events ("within the last …", "more than N times", "cumulative") →
     **temporal** `when temporal { … }`.
   - Content safety / PII / prompt attacks → **Bedrock Guardrails** provider call.
5. **Handle "unless".** An exception ("… unless approved recently") is an `unless`
   clause (Cedar or temporal) on the same rule.
6. **Anchor.** Every name must exist in the schema. (Storing, validating and repairing
   drafts: `SKILL.md`, Step 3.)

---

## 8. Logic Dogwood CANNOT express

If an NL policy needs any of the following, it cannot be faithfully translated — flag
it rather than emitting an incorrect policy.

- **Disjunction _inside a single_ `temporal { … }` block.** There is no `||` within one
  temporal block: `formerly within 1h A || formerly within 1h B` (inside `temporal { … }`)
  is rejected. **This is escapable, though** — the `temporal { … }` marker is also an
  ordinary Cedar primary expression, so you can wrap each disjunct in its _own_
  `temporal { … }` block and combine them with Cedar's `||` in a bare `when { … }`:
  `when { temporal { formerly within 1h A } || temporal { formerly within 1h B } }`
  validates and expresses "A or B held in history". So true disjunction of history
  conditions **is** expressible; only `||` _inside one block_ is not (see §5).
- **Future / unbounded history, or a look-back longer than the schema's cap.** All
  temporal operators are past-only and require a bounded `within` window. "X will happen"
  or "X ever happened, no time limit" is inexpressible. There is also no week/month/year
  unit — only `s`/`m`/`h`/`d` — and no window may exceed the event schema's `max_window`,
  which is **24h** by default and is left unset by the deployed schema. So "in the last 7
  days" or "this month" cannot be expressed at all (see §5); flag it rather than quietly
  substituting a 24h window. **This limit is _temporal-only_ — it does NOT reach a Cedar
  datetime condition on the current request's own fields (or on `context.system.now`),
  which has no window cap and no past-only restriction regardless of horizon (see §4).
  Do not route a date/time rule out as temporal-out-of-scope just because it mentions
  the future or a span longer than a day; decide by whether the rule reads the _event
  trace_ (temporal) or the _current request's_ datetime fields (Cedar).**
- **Calendar concepts a `datetime` value does not carry — day-of-week, named holidays,
  a timezone-local clock, or an unbounded named clock window (see §4).** Even as a
  current-request Cedar condition, these are inexpressible and route `non_translatable`:
  (1) **weekday / weekend** ("on weekends", "business days") — there is no day-of-week
  extraction; (2) **named holidays or a recurring calendar blackout** ("U.S. holidays",
  "when the Fed is closed", "every year-end") — needs an external calendar (a single
  fixed `datetime(...)` range is fine); (3) **a wall-clock window in a NAMED timezone**
  ("4 PM PST", "9:30 AM–4 PM EST") — `.toTime()` is UTC-only with no tz conversion and
  cannot represent a DST offset; (4) **a named clock window with NO explicit numeric
  bounds in that condition** ("during/after business hours", "evening hours",
  "nighttime") — the hours would have to be invented. A plain **UTC** time-of-day window
  with explicit numeric bounds is still translatable; only the timezone-pinned or
  bounds-less forms are out.
- **A temporal condition under an action-_group_ or action-list scope.** `action in Ns::Action::"<Group>"`
  does not validate together with a `when temporal` clause, and AgentCore does not accept
  any `action in` (list or group) with temporal conditions (see §5). Emit one policy per action.
- **A cross-session (or otherwise cross-pinned-key) history condition.** When the event
  schema `pin`s a field, every temporal predicate is implicitly scoped to the current
  request's value for it — under the deployed `pin sessionId`, history is always
  per-session. A rule whose intent is genuinely global ("system-wide", "across all users",
  "across every session") cannot be written; no policy-side phrasing escapes a pin.
- **min / max / average aggregations over history.** Only `count` and `sum` exist.
  "The largest transfer in the last day" or "the average request rate" cannot be
  computed in temporal.
- **`sum` over a field the action schema types as `decimal`.** `sum` sums `Long`
  (integer) values only, so a running-total threshold over a `context.input.<field>`
  declared `decimal` is not expressible (see above). Decide by the summed field's declared schema type, not the
  NL wording: `Long` → the sum is in scope; `decimal` → route the rule non-translatable.
- **Division or modulo.** Arithmetic is `+`, `-`, `*` only. "amount / count > X" is
  rejected (`` `/` is not a supported operator ``). A ratio against a constant can
  sometimes be rewritten with integer multiplication (`a / b > 2` → `a > 2 * b`), but
  percentage thresholds that require fractional/decimal ratios are not expressible
  (decimals support neither `*` nor ordering with `<`/`>`).
- **Ordered decimal comparison with operators.** `score > 0.5` on a decimal is a type
  error; only the decimal _methods_ order decimals, and decimals support neither
  arithmetic ordering via `<`/`>` nor `+`/`*`. Inside `temporal { … }` a decimal cannot
  be ordered at all (the methods are not accepted there); only equality works.
- **Stateful counters that are not event counts.** Dogwood counts/sums over the event
  trace; it has no mutable per-principal counter you can increment arbitrarily outside
  the event model.
- **Guardrail categories or PII types not in the provider declarations.** Only the
  categories/entity types declared in the provider schema are valid; a content type Bedrock does not support
  cannot be checked.
- **A guardrail dataPath that reaches _through_ a list/set — as a field path.** A field
  path that a guardrail inspects (argument 2) must resolve to a scalar (a field path to a
  list or set, including a whole `Set<String>` field, is not accepted). Two
  shapes have no reachable scalar, and **the compiler catches only one of them**:
  **positional list indexing** (`$.messages[0].content` →
  `context.input.messages[0].content`) is a parse error, since Dogwood has no positional
  indexing (`["key"]` needs a string-literal key); but **projecting a field through a set**
  (`.content` on a `Set<Record>`) **compiles silently**, because provider arguments are not
  type-checked (see §6). Flag both as non-translatable as field paths — the second would
  otherwise yield a policy that validates cleanly and inspects nothing. On inference, HTTP and Runtime targets use the
  JSONPath strings of `agentcore-targets-and-effects.md` instead; on MCP targets such a rule is non-translatable.
- **Arbitrary external lookups.** The supported providers are the Bedrock Guardrails.
  General third-party data providers / custom scripts are out of scope (only the Bedrock Guardrails are supported; `agentcore-service-rules.md`, Guardrails), so a
  policy needing "look up the user's credit score from service X" cannot be expressed.
- **Semantic/NL judgments beyond the guardrail categories.** "Block rude-but-not-quite-
  insulting messages" or other bespoke content judgments must map onto an existing
  guardrail category or be flagged as unsupported.

---

## 9. Quick syntax reference

```text
// Scope — action ids are "<target>___<tool>"; the resource is always the Gateway ARN
permit ( principal, action == AgentCore::Action::"<target>___X", resource == AgentCore::Gateway::"<gateway-arn>" );
forbid ( principal is AgentCore::OAuthUser, action in [AgentCore::Action::"<target>___A", AgentCore::Action::"<target>___B"], resource == AgentCore::Gateway::"<gateway-arn>" );

// Cedar condition
when   { context.input.amount <= 1000 && context.input.stock != "BLOCKED" }
unless { context.input.stock like "TEST_*" }

// Datetime (time-of-day / window)
when { context.system.now.toTime() >= duration("9h") && context.system.now.toTime() <= duration("15h") }
when { context.system.now >= datetime("2025-01-01T00:00:00Z") }

// Temporal (history) — max window 24h; scoped action must declare `sessionId: String`;
//   exactly one action (`action ==`); `eventResource: resource` in every predicate;
//   at most 3 temporal operators; pinned fields stay out of the policy
when temporal { formerly within 1h AgentCore::Action::"<target>___Read"::request{ eventResource: resource, input.doc: context.input.doc } }
unless temporal { formerly within 5m AgentCore::Action::"<target>___Approve"::request{ eventResource: resource, eventPrincipal: principal } }
when temporal { exists (n: Long). ((count for (t: Timepoint). where (formerly within 1h (AgentCore::Action::"<target>___Login"::request{ eventResource: resource, input.user: _ } && tp(t)))) == n && n > 2) }
unless temporal { exists (n: Long). ((count for (t: Timepoint). where (formerly within 1h (AgentCore::Action::"<target>___refund"::error{ eventResource: resource } && tp(t)))) == n && n >= 3) }

// Bedrock Guardrails — one action per policy; the thresholds below are the per-provider DEFAULTS, i.e. what to
//   emit when the NL states no threshold at all. If the NL states a number, copy that
//   number verbatim instead; if it states a level, use LOW 0.4 / MEDIUM 0.6 / HIGH 0.8.
when guardrails { BedrockGuardrails::ContentFilter(["MISCONDUCT"], [context.input.reason])["MISCONDUCT"].confidenceScore.greaterThanOrEqual(decimal("0.2")) }
when guardrails { BedrockGuardrails::PromptAttack(["JAILBREAK"], [context.input.prompt])["JAILBREAK"].confidenceScore.greaterThanOrEqual(decimal("0.4")) }
when guardrails { BedrockGuardrails::SensitiveInformation(["EMAIL"], [context.input.memo]).maxConfidenceScore().greaterThanOrEqual(decimal("0.2")) }
```
