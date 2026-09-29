# Resolve Bedrock Model ID

Migration plans are authored ahead of execution. By the time the execute agent
runs, plan-supplied Bedrock inference-profile IDs may be stale, use the wrong
regional prefix (`us.` / `global.` / `eu.`), or never existed. This skill
takes an input ID, lists live profiles, and returns a validated ID — asking
the user to choose when the match is ambiguous.

## Input

- `plan_model_id`: normally the target_model_id from the migration plan
  (e.g., `anthropic.claude-sonnet-4-6-20250514-v1:0` — a plausible-looking ID
  that does NOT exist; broken inputs like this are exactly what this helper
  repairs, so this example is intentionally invalid). **Can also be a
  free-text friendly name** (e.g., `anthropic claude haiku`, `Nova Micro`) when
  the caller is collecting a user-typed model request rather than reading a
  plan (see `llm-to-bedrock/SKILL.md` AC2/AC3.5) — Step 3's ranking handles
  both shapes, see the note there.
- `region`: the AWS region from your context (e.g., `us-east-1`)

## Procedure

### Step 0: Route the OpenAI proprietary GPT ids by family

**Check this before Step 1.** The proprietary GPT models split into two cases (verified 2026-08-21; see
`gcp-to-aws/references/shared/openai-on-bedrock.md`):

**Case A — GPT-5.5 / GPT-5.4 (`openai.gpt-5.5`, `openai.gpt-5.4`): mantle-only, no inference profile.** The
inference-profile path below cannot resolve them — `list-inference-profiles` never returns them, and Step 3's token
ranking would end in a spurious `blocked` for a perfectly valid id. Validate against the model catalog instead:

```bash
aws bedrock list-foundation-models \
  --region <region> \
  <add --profile <profile> when your context has an `AWS profile` line> \
  --query "modelSummaries[?starts_with(modelId, 'openai.')].[modelId,modelName]" \
  --output json
```

- **Exact match** on `plan_model_id` → return it unchanged. Do not add a regional prefix or a `-v1:0`-style suffix;
  the mantle id form is the literal `openai.gpt-5.5` shape.
- **No exact match, but `plan_model_id` is a free-text friendly name (see § Input)** — apply Step 3's token-ranking
  procedure (same tokenizer: split on `.`/`-`/`_`/`/`/whitespace, lowercase, drop date/version-stamp tokens) against
  this catalog's `modelId` + `modelName` pairs instead of against inference profiles. **Do this check before
  falling through to Step 1** — a friendly name like `"OpenAI GPT-5.5"` (tokens `{openai, gpt, 5}`) has full token
  overlap with `openai.gpt-5.5`'s own id (`{openai, gpt, 5}`) and would otherwise fall through to Step 1's
  `list-inference-profiles`, which never lists a mantle-only model — the free-text input would then reach Step 3's
  ranking with zero candidates and dead-end at `blocked` with no matches shown, even though the foundation catalog
  had the exact model the whole time. A single candidate with full token overlap on the model-identifying tokens
  (excluding generic tokens like a bare `gpt`) → surface it as the ONE candidate through Step 4 exactly as an
  inference-profile candidate would be (still never auto-applied — Step 5's confirm-on-ambiguity rule applies
  identically to a foundation-model candidate). Multiple or weak candidates → include them in Step 4's candidate
  list alongside any inference-profile candidates Steps 1–3 separately produce; do not silently drop either source.
- **No match at all (exact or token) and `plan_model_id` looked ID-shaped, not free-text** → not enabled or not
  available in this region. Return `blocked` with `reason: model_unresolvable`, putting the region and the
  `openai.*` ids that _were_ returned in `detail`. These two models have no CRIS, so the remedy is a region change
  or a different model — never an inference-profile prefix.
- CLI failure / missing `bedrock:ListFoundationModels` → `blocked` with `reason: model_unresolvable` and the exact
  error in `detail`, rather than guessing.

These two need `bedrock-mantle:*` IAM actions (e.g. `AmazonBedrockMantleInferenceAccess`), not
`bedrock:InvokeModel`; resolution success does not imply invoke authorization.

**A free-text name that does NOT token-match this catalog** (e.g. `"anthropic claude haiku"`, `"Nova Micro"`)
continues to Step 1 as before — this catalog check only short-circuits the specific case a mantle-only model would
otherwise be unreachable from free text; it is not a replacement for Step 1's inference-profile search for every
other provider/model.

**Case B — GPT-5.6 (`openai.gpt-5.6-sol` / `-terra` / `-luna`, or already `us.` / `in.` / `global.` prefixed):
BOTH paths exist.** The bare id is the mantle form; `bedrock-runtime` serves these models through CRIS inference
profiles (`us.openai.gpt-5.6-*`, `in.openai.gpt-5.6-*` in India Regions, `global.openai.gpt-5.6-*`), which
`list-inference-profiles` DOES return. Route on the plan's intent:

- Plan targets the mantle endpoint (`migration_path` starts with `mantle`, or the id is bare) → validate the bare id
  against the model catalog exactly as in Case A.
- Plan targets `bedrock-runtime` (`migration_path: runtime_openai_cris`, or the id already carries a CRIS prefix) →
  continue to Step 1; the normal inference-profile resolution below applies to these ids like any other CRIS
  profile. Note the runtime base URL for these models is `bedrock-runtime.{region}.amazonaws.com/openai/v1`.

Non-`openai.gpt-5*` ids continue to Step 1 unchanged.

### Step 1: List live inference profiles

```bash
aws bedrock list-inference-profiles \
  --region <region> \
  <add --profile <profile> when your context has an `AWS profile` line> \
  --query 'inferenceProfileSummaries[].[inferenceProfileId,inferenceProfileName]' \
  --output json
```

Parse the JSON. Each entry is a `[id, name]` pair.

### Step 2: Try exact match

If `plan_model_id` appears verbatim in the list, return it. No user prompt
needed.

### Step 3: Token-based ranking when no exact match

Tokenize both `plan_model_id` and each live ID by splitting on `.`, `-`, `_`,
`/`, **and whitespace** (a free-text friendly name like `anthropic claude
haiku` is space-separated, not `.`/`-`/`_`/`/`-separated, so without splitting
on whitespace too it stays one token and matches nothing — see § Input).
Lowercase every token before comparing (a plan ID's tokens are already
lowercase, but a user-typed name like `Nova Micro` is not). Drop tokens that
match the regex `^v?\d{6,}` or `^v\d+$` (these are date stamps like
`20250514` or version tags like `v1`).

For each live profile, build its comparison token set from **both** its
`inferenceProfileId` AND its `inferenceProfileName` (tokenized the same way) —
an ID-only comparison set is fine for an ID-shaped `plan_model_id` (the name's
tokens rarely add new overlap there) but is why a friendly-name input like
`anthropic claude haiku` found nothing: the display name is where "claude"
and "haiku" actually appear as separate words; the ID
(`anthropic.claude-3-5-haiku-...`) has "claude" and "haiku" too, but a
provider name typed as a separate word ("anthropic") only ever appears in the
profile _name_, not the ID, for some providers' listings — do not restrict
matching to the ID alone.

Compute the size of the intersection of each live profile's combined
(ID + name) token set with `plan_model_id`'s token set. Keep the top 3 by
intersection size, breaking ties in this order:

1. Prefer profiles whose ID starts with `us.`
2. Then `global.`
3. Then no prefix
4. Then `eu.` / others

### Step 4: Defer to the orchestration skill

The subagent that loads this skill is non-interactive and cannot prompt the
user. When no exact match exists, return `blocked` with
`reason: model_unresolvable` and put the plan's ID and the top candidates in
`detail`, so the orchestration skill (main session) presents the choice. The
candidate-selection logic above (Steps 1-3) defines what the orchestrator
offers; format `detail` so it can render the choices:

```
The migration plan references Bedrock model '<plan_model_id>', but that ID is
not available in <region>. Closest matches found:
  - <candidate 1 id> (<candidate 1 name>)
  - <candidate 2 id> (<candidate 2 name>)
  - <candidate 3 id> (<candidate 3 name>)
The user may also supply a different inference profile ID, or abort to fix the
plan first.
```

Include fewer candidates if fewer exist. If zero candidates have token overlap

> 0, omit the candidate rows and note only that the user must supply a correct
> ID or abort.

### Step 5: Return

ONLY an exact match (Step 2) returns an ID directly. Token ranking (Step 3)
exists solely to produce the candidate list inside Step 4's `blocked` detail —
a token-ranked match is NEVER auto-applied, because silently substituting a
different model than the plan named would make every downstream eval and
rewrite target the wrong model without the user knowing. Anything short of an
exact match returns the `blocked` signal from Step 4 — the orchestration skill
asks the user and re-invokes resolution with the chosen (or pasted) ID, or
stops on abort.

## Notes

- This skill is idempotent: calling it twice with the same already-validated
  ID will hit Step 0 (mantle) or Step 2 (inference profile) and return immediately.
- Steps 1–5 assume the target is a `bedrock-runtime` model reachable through an
  inference profile. Mantle-only ids (GPT-5.5/5.4, and GPT-5.6 when the plan
  targets the mantle endpoint) are handled entirely in Step 0; GPT-5.6 CRIS ids
  flow through Steps 1–5 like any other inference profile. See
  `gcp-to-aws/references/shared/openai-on-bedrock.md` for the authoritative
  family split.
- Output of this skill should replace the plan's `target_model_id` in the
  caller's context — downstream phases (evaluator, rewriter) receive the
  validated ID only.
