# Behavior Delta Detection

This skill enumerates known parameter-surface differences between a source LLM provider (OpenAI, Gemini) and Bedrock. The **analyzer** uses it to find user-visible occurrences in source code; the **rewriter** uses it to confirm each user-visible change with the user before modifying code.

The motivation is to prevent silent UX changes during migration. Example: OpenAI accepts `temperature ∈ [0, 2]` but Bedrock/Claude only accepts `[0, 1]`. A naive rewriter sees a UI slider with `max=2` and silently caps it to `1`, removing the upper half of the range without consent. This skill is the safeguard.

## When to load

- Track 2 migration AND
- `source_provider ∈ {openai, google}` (the analyzer emits `google` for both Gemini API and Vertex AI) AND
- `same_model_family == false`

For Anthropic 1P → Bedrock (`same_model_family: true`), parameter surfaces are identical — skip this skill entirely. For custom OpenAI-compatible providers (Together, Fireworks, etc.), v1 also skips — emit `behavior_deltas: []`.

**OpenAI → the same GPT model on Bedrock is also `same_model_family: true`.** When the target is a proprietary GPT model on `bedrock-mantle` (`openai.gpt-5.6-sol` / `-terra` / `-luna`, `openai.gpt-5.5`, `openai.gpt-5.4`), the model is unchanged, so the model-parameter deltas in `references/openai-to-bedrock.md` — temperature range, penalty parameters, stop-sequence limits — **do not apply**. Applying them would prompt the user to accept range changes that are not happening.

That case is not delta-free, though: the **API surface** can change (Chat Completions → Responses) and reasoning models require reasoning items to be echoed back across turns. Read only the "Same-model (mantle) deltas" section of `references/openai-to-bedrock.md` for those, and skip the parameter-surface blocks.

Decide from the resolved target model id, not from `source_provider`:

| Source | Target model id          | What to load                                              |
| ------ | ------------------------ | --------------------------------------------------------- |
| openai | `openai.gpt-5*` (mantle) | Same-model (mantle) deltas ONLY                           |
| openai | Claude / Nova / DeepSeek | Full parameter-surface deltas (cross-family)              |
| openai | `openai.gpt-oss-*`       | Full parameter-surface deltas — different model, Converse |

## Choose the right reference

| source_provider | reference file                  |
| --------------- | ------------------------------- |
| openai          | references/openai-to-bedrock.md |
| google          | references/gemini-to-bedrock.md |

Read ONLY the matching reference. Do not read both.

---

## How analyzer uses this

For each delta listed in the matching reference:

1. Run the reference's `detect_grep` recipe against `<REPO>` (the repository path supplied in your context).
2. For each hit, classify `user_visible`:
   - `true` if location is: Slider / NumberInput / Form / CLI flag / env var / config file users edit / API request body parameter that flows from a user-set control.
   - `false` if location is: hardcoded constant in backend, internal default in non-user-facing module.
3. Emit one `behavior_deltas` entry per hit:

```json
{
  "delta_type": "<delta slug from reference>",
  "location": "<file:line>",
  "source_value": "<what the source code currently has, e.g., 'max=2'>",
  "target_constraint": "<what target accepts, e.g., 'Bedrock max=1'>",
  "user_visible": true,
  "resolution_kind": "ux_choice",
  "option_set_id": "range_narrowed"
}
```

For `resolution_kind: "impl_path"`, omit `option_set_id` (the schema enforces this via discriminated union).

---

## How rewriter uses this

For each `behavior_deltas` entry where `user_visible == true` AND `resolution_kind == "ux_choice"`, the rewriter does NOT ask the user — the user already chose at the orchestration sidebar. The orchestration sidebar presents the **option set** specified by that delta's `option_set_id` to the user; the rewriter receives the chosen resolution in its `Confirmed behavior-delta decisions` context and applies it. Each option set is fixed and ordered — do not reorder, do not invent new options. The option sets below define what the sidebar offers.

### Option set: `range_narrowed`

Used when the source param has a wider numeric range than the target (e.g., `temperature` 0-2 → 0-1). The user picks how the UI/backend should handle the narrowed range:

1. **Cap UI to target range (Recommended)** — modify the user-visible control to the target's range. Source-only range disappears, UI matches backend. Lossy but consistent.
2. **Linear rescale source range to target range** — preserve the UI range; backend transforms `target_value = source_value * (target_max / source_max)`. Best preserves the user's relative intent (1.4 on a 0-2 slider becomes 0.7 sent to Bedrock).
3. **Keep UI + add description note** — preserve UI; show a note like "values >X are clamped to X"; backend clamps. Honest UX, but the upper portion of the slider becomes inert.
4. **Keep UI + fail loud on out-of-range** — preserve UI; backend throws a clear error when out-of-range values are submitted. Forces discovery via error rather than silent clamping.

(Earlier drafts had a "Clamp backend silently" option here. Removed because it recreates the original silent-change bug under the cover of user consent.)

### Option set: `parameter_removed`

Used when the source param has no target equivalent (e.g., `presence_penalty`, `frequency_penalty`, Gemini `candidate_count > 1`). The parameter cannot be supported at all on Bedrock; the question is just how the UI should handle that:

1. **Drop UI control + remove from API call (Recommended)** — delete the user-visible control and remove the parameter from request construction. Honest about feature loss.
2. **Hide UI control + ignore in API call** — keep the control invisible/disabled with an explanatory note; do not pass to API. Less invasive to layout, but the control is "dead."
3. **Keep UI control as inert decoration** — control still rendered and accepts input, but is silently ignored. NOT recommended; flagged as misleading. Offered only because some users may prefer minimal layout disruption.

### Option set: `fallback`

Used by the rewriter's defense-in-depth fallback rule (see "Fallback rule" below) when an unlisted user-visible change is encountered mid-rewrite, OR when the analyzer emits an unrecognized `delta_type` / `option_set_id`:

1. **Apply change as planned (Recommended)** — agent describes the change in plain text; user confirms. Code applied verbatim from the agent's plan.
2. **Skip this change** — leave the original code unchanged; insert a `# TODO: Bedrock incompatibility — needs manual review` comment near the line.
3. **Let me describe what I want** — freeform answer; agent records the answer verbatim and either follows it or, if still ambiguous, records as a custom decision (see "Ambiguous user answers" below).

(`parameter_replaced` is intentionally NOT in v1's `option_set_id` enum. Adding it without a usable option set would be dead code. When Gemini Guardrails auto-mapping lands in v2, the enum gains the value and the option set.)

For `resolution_kind == "impl_path"` (e.g., JSON mode rewrite via prefill vs tool use, dropping incompatible safety_settings), DO NOT ask the user. Pick the default specified in the reference and document the choice in the rewriter's returned `notes` field (and in `behavior_delta_decisions`).

---

## Recording decisions

After asking the user (or applying an `impl_path` default, or running the fallback rule), the rewriter MUST record one entry per delta in `behavior_delta_decisions`:

```json
{
  "delta_type": "temperature-range-mismatch",
  "location": "app.py:95",
  "resolution_chosen": "range_narrowed_1",
  "source": "user_question"
}
```

`resolution_chosen` is a typed enum: `"{option_set_id}_{1-indexed_option_number}"` for ux_choice and fallback paths, or `"impl_path_default"` for impl_path defaults. The `behavior_deltas` item schema inside `scripts/schemas/analysis.json` is the authoritative field contract (the recording shape is `scripts/schemas/delta-decisions.json`).

`source` indicates how the decision was reached:

- `"user_question"` — user picked one of the numbered options.
- `"skill_default"` — `impl_path` delta, default from skill reference.
- `"fallback_question"` — fallback rule fired and user picked an option from the `fallback` set.
- `"ambiguous_user_answer_recommended"` — user's answer didn't map after one clarification; rewriter fell back to (Recommended) and recorded both attempts in `user_verbatim_answer`.

---

## Ambiguous user answers

The orchestration sidebar (not the rewriter) presents the options to the user and resolves ambiguity. If the user's answer does NOT map to one of the numbered options (they typed something freeform that doesn't match an option label or its semantic), the sidebar:

1. Asks one clarifying follow-up that restates the options.
2. If the second answer is still ambiguous, falls back to **option 1 (Recommended)** for that delta.

The rewriter then receives — and records — whatever resolution the sidebar produced:

- `resolution_chosen` = the chosen option's enum value (e.g., `"range_narrowed_1"`)
- `source` = `"ambiguous_user_answer_recommended"` when the (Recommended) fallback fired
- `user_verbatim_answer` = both attempts joined with `" | "`

Rationale: a customer waiting on a migration shouldn't be blocked by an LLM that can't parse free text. The Recommended option is documented as safe; the verbatim record makes the divergence auditable.

---

## Grouping policy

**v1: one question per delta location.** Do NOT group multiple locations into a single question even if they look identical. This avoids the failure mode where the user says "Cap UI" not realizing it applies to 5 different pages. Revisit grouping in v2 if PM reports user fatigue with field data.

---

## Fallback rule (rewriter-side, defense-in-depth)

If during code rewrite (llm2bedrock-code-rewriter §10) you are about to modify a parameter affecting **user-visible behavior** that was NOT in `behavior_deltas`, do NOT modify it and do NOT improvise a resolution. Apply the rewriter's safe default (llm2bedrock-code-rewriter §9 "Missing / unrecognized decision rule"): leave the original code in place, add a `# TODO: Bedrock incompatibility — needs manual review` comment at the site, record the situation in `notes` naming the **`fallback` option set** above, and add an entry to `behavior_delta_decisions` with `source: "missing_confirmation_safe_default"`. Do NOT return `blocked` for this — the blocked enum has no matching reason and the rest of the rewrite can still complete; the user resolves the flagged site as a follow-up via the fallback options the orchestration skill surfaces from your notes.

Same applies if the analyzer emitted a delta with an unrecognized `delta_type` or `option_set_id` (version skew between analyzer and rewriter): trigger the same safe default and add an `errors:` note in the returned notes.

This is a safety net for grep-recipe gaps in this skill. Better to flag-and-skip than recreate the original silent-change bug through a code path the analyzer missed.
