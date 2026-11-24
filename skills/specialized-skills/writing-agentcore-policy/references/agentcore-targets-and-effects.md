# AgentCore targets and guardrail scope

How-to for the parts of AgentCore Policy that are not language rules: what guardrail rules this
skill writes, the validation mode of guardrail statements, inference, HTTP and Runtime targets,
setup that looks like a policy bug, and design notes. Read it when a policy targets an inference,
HTTP or Runtime target, or uses a guardrail. The service rules (one action per guardrail policy,
categories, indexing, thresholds) are in `agentcore-service-rules.md`; the guardrail syntax is in
`dogwood-language.md` §6.

## Contents

- [Guardrail scope of this skill](#guardrail-scope-of-this-skill)
- [Inference and Runtime text: `$`-paths](#inference-and-runtime-text--paths)
- [Text locations per inference API](#text-locations-per-inference-api)
- [Screening responses with suppressOutput](#screening-responses-with-suppressoutput)
- [Submission mode](#submission-mode)
- [Inference, HTTP and Runtime targets](#inference-http-and-runtime-targets)
- [Guardrail checklist](#guardrail-checklist)
- [Setup prerequisites that look like policy bugs](#setup-prerequisites-that-look-like-policy-bugs)
- [Design notes](#design-notes)
- [Sources](#sources)

## Guardrail scope of this skill

The guardrail checks this skill writes, by target kind:

| Target kind                                     | Request (`permit` / `forbid`)                                                                                                                                  | Response                                                                                                   |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| MCP tools (Lambda, MCP server, OpenAPI, Smithy) | string fields: `[context.input.<field>]`, or a string inside a nested record, `[context.input.<record>.<field>]`, where `describe` shows the field as `String` | not supported                                                                                              |
| Inference, HTTP and Runtime targets             | the same string fields, and `$`-paths into the request body ([below](#inference-and-runtime-text--paths))                                                      | `suppressOutput` with `$`-paths into the response body ([below](#screening-responses-with-suppressoutput)) |

Guard every optional field with `has` (`validate`: `guardrail_unguarded_optional`).

These are **not supported**. Route such a rule non-translatable and give the reason:

- **Redaction and interruption** — `redactInput`, `redactOutput` and `interruptOutput` (gated
  per account). Reason: `redaction and stream interruption are not supported by this skill`.
- **Response screening on MCP targets**, and **`$`-paths on MCP targets**. On an MCP target,
  text that is only inside a list or a set of a tool argument makes the rule non-translatable.
  Reason: `the screened text is only inside a list or a set of a tool argument; JSON paths are
supported on inference and Runtime targets only`.
- `context.output` under `permit` / `forbid` is rejected by the service (an authorization effect
  reads the request only).

## Inference and Runtime text: `$`-paths

Chat and response APIs keep the text inside lists (`messages[*].content`). A field path cannot
reach it: naming the list (`context.input.messages`) is rejected at create
(`argument ... has type Set<record> ... declares argument type string`), and Dogwood has no
projection, so `messages[*].content` does not parse. Use a **`$`-path**: a string literal
starting with `$`, a JSONPath over the raw payload.

```dogwood
forbid (principal,
        action == AgentCore::Action::"<target>___POST:/v1/chat/completions",
        resource == AgentCore::Gateway::"<gateway-arn>")
when guardrails {
    BedrockGuardrails::ContentFilter(["VIOLENCE", "HATE"],
        ["$.messages[*].content", "$.messages[*].content[*].text"])
        .maxConfidenceScore().greaterThan(decimal("0.5"))
};
```

- **Rooted at the payload, not at `context`.** Write `$.messages[*].content`, never
  `$.context.input.messages[*].content`; `validate` rejects a path rooted at `context`.
- **The effect sets the direction.** A `$`-path has no direction marker: `suppressOutput` reads
  the response, `permit` / `forbid` read the request.
- **All matches are joined into one text**, so a phrase split across content blocks stays
  contiguous.
- **Not checked at create.** The service checks neither the syntax nor the fit of a `$`-path. If
  no path of a check resolves, every request in scope is denied ("request missing field(s)
  required for guardrail evaluation"); if some resolve, only the unresolved one is skipped
  silently. Take the paths only from the table below, never adapt them from another API, and
  recommend testing each policy with text it should catch.
- **Not checked against the generated Cedar schema**, so a text field that the schema dropped
  (for example a `oneOf` field) is still reachable by a `$`-path.
- Do not mix a `$`-path and a `context.input.*` field in one `suppressOutput` call: the service
  rejects it (`mixes 'context.input.*' and 'context.output.*' paths`).
- For a Runtime or HTTP target, take the paths from the request or response schema `describe`
  shows; when the text is a top-level string field, prefer the field path.

## Text locations per inference API

Take the paths of the endpoint the action names. List every path of that endpoint in one call:
each field accepts a plain string and a list of content blocks.

| Endpoint                    | Request (`permit` / `forbid`)                                                            | Response (`suppressOutput`)                                    |
| --------------------------- | ---------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `POST /v1/chat/completions` | `$.messages[*].content`, `$.messages[*].content[*].text`                                 | `$.choices[*].message.content`, `$.choices[*].message.refusal` |
| `POST /v1/responses`        | `$.input`, `$.input[*].content`, `$.input[*].content[*].text`, `$.instructions`          | `$.output[*].content[*].text`                                  |
| `POST /v1/messages`         | `$.messages[*].content`, `$.messages[*].content[*].text`, `$.system`, `$.system[*].text` | `$.content[*].text`                                            |

`instructions` (`/v1/responses`) and `system` (`/v1/messages`) are the system prompt; `input` /
`messages` are the user's text. Say which one a policy screens; include the system prompt when
injected instructions are a concern.

## Screening responses with suppressOutput

`suppressOutput` withholds a response after the authorized call has run (the model or Runtime
still runs; only the caller's copy is suppressed). It applies only to inference, HTTP and Runtime
targets in this skill.

```dogwood
suppressOutput (principal,
                action == AgentCore::Action::"<target>___POST:/v1/chat/completions",
                resource == AgentCore::Gateway::"<gateway-arn>")
when guardrails {
    BedrockGuardrails::ContentFilter(["VIOLENCE", "HATE"],
        ["$.choices[*].message.content", "$.choices[*].message.refusal"])
        .maxConfidenceScore().greaterThan(decimal("0.5"))
};
```

- The condition consists only of guardrail checks: no plain Cedar or `temporal` conditions.
- Screening the request and the response are two policies (`forbid` for the request,
  `suppressOutput` for the response), one per per-path action.
- It buffers the response: a streaming response is delivered whole or not at all.
- `validate` parses it through the effect adapter (`effect_adapter`), so its result is at most
  `incomplete`; say which parts were not checked (`interpreting-findings.md`).

## Submission mode

A statement that invokes a guardrail (`BedrockGuardrails::`, a `when guardrails` block, or
`suppressOutput`)
produces service validation findings even when correct, so it must be submitted with
`validation_mode = IGNORE_ALL_FINDINGS`. `validate` reports the required mode in
`submission.validation_mode`; `api create_policy` / `update_policy` refuse the default
`FAIL_ON_ANY_FINDINGS` for such statements.

That setting only suppresses findings on **this** statement. It does not require or authorize a
broader permit, and it must not be applied to a separately approved access-control permit (review
that one with the normal default). Findings and live evidence stay separate.

## Inference, HTTP and Runtime targets

- Action ids are `<target>___<METHOD>:<path>`, for example
  `AgentCore::Action::"ClaimsChat___POST:/v1/chat/completions"`. Paths seen on inference
  targets: `POST:/v1/messages`, `POST:/v1/chat/completions`, `POST:/v1/responses`; Runtime
  targets: `POST:/invocations`. `GET:/v1/models` is not a policy action. Two inference targets
  can serve the same path; they differ by target name, so take the name from `prepare`, not
  from the path.
- Decisions for HTTP and inference calls are not in the Gateway `APPLICATION_LOGS`; they appear
  in the 403 response body and in the `TRACES` spans.
- For "all inference targets", list every per-path action of every target whose `kind` is
  `inference` (`prepare` → `targets[].actions`, or `describe`). Write one guardrail policy per
  path (an action list is not supported at runtime), state the number of paths and policies before drafting, and give each
  policy its own name of at most 48 characters, for example `DenyViolentHateIn_ChatCompletions`.
- Plain Cedar conditions on HTTP and inference inputs read the overlay fields that `describe`
  lists (numbers are `Long`), for example
  `context.input has max_tokens && context.input.max_tokens > 4096`.

## Guardrail checklist

- [ ] An existing permit covers the intended callers; no new grant added without approval.
- [ ] One policy per per-path (or per-tool) action; no target group, no unconstrained `action`.
- [ ] Effect is `permit` / `forbid` on the request, or `suppressOutput` on the response of an
      inference, HTTP or Runtime target; field paths name string fields with a `has` guard on
      every optional level; `$`-paths come from the table above (no redaction effects).
- [ ] `ContentFilter` / `PromptAttack`: every named category indexed or `maxConfidenceScore()`
      used. `SensitiveInformation`: aggregation only; `count()` compared with `> 0`.
- [ ] Categories come from `guardrail_providers.categories`.
- [ ] **Optional fields.** Without a guard, a guardrail over an optional field denies any request
      that omits it (the guardrail cannot run). Guard it: `context.input has f && <check>` in a
      `forbid`, `!(context.input has f) || <check>` in a `permit` (see `agentcore-service-rules.md`).
- [ ] Target a field that can plausibly carry what you screen for; a check aimed at an identifier
      has nothing to detect.
- [ ] Threshold given exactly as the developer wrote it; boundary stated. The comparison follows
      the words: "higher than 0.5" / "above 0.5" → `.greaterThan(decimal("0.5"))`; "0.5 or higher" /
      "at least 0.5" → `.greaterThanOrEqual(decimal("0.5"))`. Do not use the other form.
- [ ] `submission.validation_mode` = `IGNORE_ALL_FINDINGS` carried to the write unchanged.
- [ ] Policy is unverified until an invocation fires it. Both failure directions are live:
      screening nothing, or denying everything in scope.

## Setup prerequisites that look like policy bugs

Report these as setup issues, not policy defects:

- The Gateway execution role needs permission to call Bedrock Guardrails
  (`bedrock:InvokeGuardrailChecks`) in addition to its AgentCore permissions; the policy data plane
  uses forward-access-session credentials derived from that role.
- Guardrails in policies are available in a subset of Regions. Confirm the Gateway's Region.
- Temporal policies: the client must send the `x-amzn-bedrock-agentcore-policy-session-id` header,
  and the Gateway role needs
  `bedrock-agentcore:GetWorkloadAccessToken`. Adding or updating a temporal policy invalidates
  open sessions (HTTP 409 on reuse).
- `::response` events are recorded only while the Gateway is in `ENFORCE`; in a Gateway-level
  `LOG_ONLY` shadow test a `::response` condition never matches. To shadow-test one, keep the
  Gateway in `ENFORCE` and set only the new policy's `enforcement_mode` to `LOG_ONLY`.

## Design notes

- Calibrate a guardrail threshold by running the policy as `LOG_ONLY` (policy
  `enforcement_mode`, see `interpreting-findings.md`) and reading the scores from the policy log
  before enforcing.
- Scores are probabilistic: the same content can score differently between calls. Where a rule can
  be expressed as a plain condition (role, claim, amount), express it that way instead; narrow by
  action and principal because each matching request costs a Bedrock invocation.
- Model money in minor units (cents) for temporal totals and thresholds (ordered comparisons in
  `temporal` need `Long`). Do not rewrite an existing decimal input as integer money in
  non-temporal conditions.
- Mutual exclusion needs two symmetric policies (one per order). A chain of N steps is N policies,
  one per link, plus a plain permit for the first action.
- A rule on earlier responses needs the earlier action to be authorized: check that an existing
  permit covers it. An error-count rule must not add grants merely to collect failures.
- A `response` event is recorded shortly after the call returns, so a dependent call sent back to
  back may not see it.
- Counting or sequencing requests can mutate the backend (a successful refund or email call is
  real even below a threshold). Obtain approval for a safe test backend; do not assume
  harmlessness.
- `::error` also records backend errors, not only policy denials. Say so; do not claim that an
  error count enforces "denied by policy X".

## Sources

- <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-guardrails-in-policies.html>
- <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-temporal.html>
- <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-session-based-temporal.html>
- <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/example-policies-temporal.html>
- Policy conditions and principal formats: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-conditions.html>
- Action and group reference: <https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/example-policies-reference.html>
- Amazon Bedrock Guardrails: <https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails.html>
