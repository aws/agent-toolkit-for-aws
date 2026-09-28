# Run Source-Model Baseline

The Track 2 evaluator scores Bedrock outputs against a baseline. When that
baseline is just an agent-synthesized `assistant_response` from the golden
dataset, "Bedrock matches baseline" only proves Bedrock matches the agent's
own writing — PM rejected the previous "100% pass rate" report on exactly
this gap. This skill produces a fresh side-by-side baseline by re-running
each golden prompt against the customer's live source model.

The skill uses Python stdlib `urllib.request` only — no SDK install needed;
it runs fine under the pinned `uv` toolchain.

`<REPO>` is the repository path supplied in your context (the evaluator that
loads this skill receives it). `<scriptsDir>` is the pinned-toolchain scripts
directory supplied in your context. Substitute both before running.

## Input

- `source_provider`: `openai` | `anthropic` | `google`
- `source_model_id`: the model ID to call (e.g., `gpt-4o`, `claude-3-5-sonnet-20241022`, `gemini-1.5-pro`)
- `golden_dataset_path`: usually `<REPO>/.saws-migrate/golden-dataset/prompts.jsonl`
- `output_path`: usually `<REPO>/.saws-migrate/eval-results/source_baselines.jsonl`

## Preconditions

- `<REPO>/.saws-migrate/.source-provider-env` exists (written by the
  orchestration skill's Phase B3 when the user provided a source-provider
  API key). The file contains a single `KEY=VALUE` line, one of:
  `OPENAI_API_KEY=...` / `ANTHROPIC_API_KEY=...` / `GEMINI_API_KEY=...`.
- The golden dataset JSONL exists at `golden_dataset_path` and each entry
  has at least `id`, `user_prompt`, optionally `system_prompt`.

If the env file is absent, do NOT run this skill — the caller should set
`live_source_baseline: false` and skip to static baselines.

## Procedure

### Step 1: Verify the env file

```bash
test -f <REPO>/.saws-migrate/.source-provider-env && echo present || echo absent
grep -qE '^(OPENAI|ANTHROPIC|GEMINI)_API_KEY=.+' <REPO>/.saws-migrate/.source-provider-env 2>/dev/null && echo format_ok || echo format_bad
```

- `absent` → return immediately with `status: "skipped"`.
- `present` + `format_bad` → the file exists but has no parseable `KEY=VALUE` line (e.g. a bare
  key was written without the env-var prefix). Do NOT proceed — the resolver would silently hit
  the `no_key` path. Return `status: "skipped"` with a note telling the caller the env file is
  malformed and needs re-collection in `KEY=VALUE` form. Never print the file's contents.
- `present` + `format_ok` → continue.

### Step 1.5: Resolve the source model ID against the live provider catalog

The `source_model_id` you were handed is the user's STATED source model
(extracted by llm2bedrock-code-analyzer / log-ingestor from the customer's source
code or plan). It might be a slight misspelling, a stale alias, or a
date-suffixed variant compared to what the provider actually exposes
right now. Before running the baseline, check that the ID exists in the
provider's live catalog and resolve to the closest valid variant **of
the SAME model line** if needed.

🚫 **Hard rule — model line is sacred.** You may auto-resolve `gpt-5.4`
to `gpt-5.4-2024-08-06` (a date-pinned variant of the same model). You
MUST NOT resolve it to `gpt-5`, `gpt-5.5`, `gpt-4o`, `gpt-5.4-mini`,
`gpt-5.4-pro`, `gpt-5.4-latest`, or any other model line / alias. The
migration report's pass rate is meaningful only when the live baseline
is the SAME deterministic model the customer said they were running. A
cross-line swap or a moving alias is worse than no baseline.

Run the committed resolver script `<scriptsDir>/resolve_source_model.py` (do NOT write an
ad-hoc script — instructions only ever run committed scripts, with paths passed as
arguments). The resolver:

1. Calls the provider's list-models endpoint with the env key:
   - OpenAI: `GET https://api.openai.com/v1/models`
   - Anthropic: `GET https://api.anthropic.com/v1/models`
   - Gemini: `GET https://generativelanguage.googleapis.com/v1beta/models` (key via `x-goog-api-key` header, never a query parameter)
2. Looks for, in order:
   - **Exact match** for `source_model_id` → use unchanged.
   - **Safe prefix match**: a catalog ID that starts with
     `<source_model_id>-` AND whose suffix is a date (`YYYY-MM-DD`) or
     pure version number (e.g. `2`, `3.1`). These are the same model
     pinned to a date or version — same-line. Examples:
     `gpt-5.4` matches `gpt-5.4-2026-03-05`; `claude-3-5-sonnet`
     matches `claude-3-5-sonnet-20241022`. Does NOT match `gpt-5`,
     `gpt-5.5`, `gpt-54` (different lines), nor `gpt-5.4-mini`,
     `gpt-5.4-pro`, `gpt-5.4-latest` (alphabetic suffixes — those are
     either different model lines or non-deterministic aliases).
     If multiple safe variants, pick the shortest ID (most general).
   - **Ambiguous prefix** (catalog has prefix hits but ALL of them have
     alphabetic / alias suffixes — `mini`, `nano`, `pro`, `turbo`,
     `latest`, `codex`, etc.): do NOT auto-pick. Surface the prefix
     hits as `not_found` candidates so the user picks the right
     model line themselves.
   - **No match** → emit a JSON record with the top 5 catalog IDs
     whose names share the longest common prefix with
     `source_model_id`, for the caller to show the user.

The script detects the provider from whichever `*_API_KEY` the env file
carries (all three are implemented — OpenAI, Anthropic, Gemini) and calls only
that provider's list-models endpoint. The resolution rules above are the
behavior contract, unit-locked in `test_resolve_source_model.py`.

Run it, passing the plan model id via env and the env-file path as the argument:

```bash
SOURCE_PROVIDER=<source_provider> \
  PLAN_MODEL_ID=<source_model_id> \
  uv run --project <scriptsDir> python <scriptsDir>/resolve_source_model.py <REPO>/.saws-migrate/.source-provider-env
```

`SOURCE_PROVIDER` (this skill's declared input) is authoritative for provider selection —
if the env file carries several provider keys, the stated provider's key is used and a
missing key is a hard `no_key`, never a guess.

Interpret the JSON output:

| `status`    | Action                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ----------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `exact`     | `resolved_id == source_model_id`. Continue to Step 2 with `SOURCE_MODEL_ID = source_model_id`. No notes entry needed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `prefix`    | Use `resolved_id` as `SOURCE_MODEL_ID` for Step 2. Caller appends to the evaluator's returned notes field: `live baseline used <resolved_id> (resolved from plan id <source_model_id>)`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `not_found` | Do NOT auto-pick a catalog entry and do NOT prompt — the evaluator that loads this skill is non-interactive. Skip the live baseline: return `live_source_baseline: false` and record the situation in the evaluator's `notes` so the orchestration skill can surface the model choice to the user. Include up to 5 candidates from the JSON in the note, **using the raw catalog ID exactly as returned by the provider — do NOT add invented qualifiers like "(closest match)", "(latest stable)", "(recommended)", or any other editorializing tag. The skill has no basis to rank these; the user does.** Phrasing depends on the `ambiguous_prefix` flag in the JSON: if `true`, the candidates DO start with the plan ID but only via alphabetic / alias suffixes (e.g. `gpt-5.4-mini`, `gpt-5.4-pro`); note `plan source model <source_model_id> has prefix matches in the <provider> catalog but only as different model lines or non-deterministic aliases — orchestration skill should ask the user to pick the right model line or skip the live baseline; candidates: <list>`. Otherwise (no prefix hits at all): `plan source model <source_model_id> not in <provider> catalog — orchestration skill should ask the user to pick the closest match or skip the live baseline; candidates: <list>`. |
| `no_key`    | env file malformed; return `live_source_baseline: false`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| `error`     | catalog fetch failed (network/provider error; `detail` is redacted — it never carries the key). Return `live_source_baseline: false` and record the redacted detail in notes.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |

If the orchestration skill later re-invokes the baseline with a user-chosen
candidate, the caller appends to notes: `live baseline used <chosen_id> (selected from candidates after plan id <source_model_id> not found, confirmed by user)`.

NEVER silently substitute a different model line. The `prefix` rule
above is the only automatic substitution allowed.

### Step 2: Run the baseline script

Run the committed `<scriptsDir>/source_baseline.py` (do NOT write an ad-hoc
script). It detects the provider from the env file, builds the
provider-correct request shape (OpenAI `max_completion_tokens`, Anthropic
top-level `system`, Gemini `systemInstruction` — shapes unit-locked in
`test_source_baseline.py`), applies the partial-resume guard (prompts with a
`live` row in the output are never re-billed; failed rows are retried), and
writes the output contract below.

Pass `SOURCE_MODEL_ID`, `GOLDEN_DATASET_PATH`, `OUTPUT_PATH` via env and the
env-file path as the argument:

```bash
SOURCE_PROVIDER=<source_provider> \
  SOURCE_MODEL_ID=<source_model_id> \
  GOLDEN_DATASET_PATH=<golden_dataset_path> \
  OUTPUT_PATH=<output_path> \
  uv run --project <scriptsDir> python <scriptsDir>/source_baseline.py <REPO>/.saws-migrate/.source-provider-env
```

### Step 3: Classify the result

Parse the printed `live K/N` line and inspect the JSONL.

| Outcome                                                          | Caller should set                                                                                                                                                                              |
| ---------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `live N/N` (all succeed)                                         | `live_source_baseline: true`, all prompts have live `source_response`                                                                                                                          |
| `live K/N`, `0 < K < N`                                          | `live_source_baseline: true`, prompts with `status != "live"` fall back to static baseline                                                                                                     |
| `live 0/N`, all `http_401` / `http_403`                          | invalid key — the evaluator returns `blocked` with `reason: source_key_auth` (per the evaluator prompt) so the orchestration skill asks the user for a new key or to skip; do NOT echo the key |
| `live 0/N`, all network errors (DNS / connect refused / timeout) | `live_source_baseline: false`, host cannot reach provider; banner notes the gap                                                                                                                |
| Script exit code 2 (no recognized key in env file)               | `live_source_baseline: false`, file is malformed                                                                                                                                               |

## Security

- Never echo, log, or include the API key value in any returned notes or
  output (including any `blocked` detail). The key only lives in
  `<REPO>/.saws-migrate/.source-provider-env` on the local host.
- The script reads the key from the env file into `os.environ` only —
  never writes it to stdout or to the output JSONL.
- The key is only ever sent as an auth header to its OWN provider's official
  endpoint — `api.openai.com`, `api.anthropic.com`, or
  `generativelanguage.googleapis.com` — never to any other host, and never as
  a URL query parameter (query strings end up in logs). The endpoint set is
  pinned by `test_source_baseline.py`.

## Output contract

`source_baselines.jsonl`, one record per line:

```json
{
  "id": "<prompt_id>",
  "source_response": "<text or empty>",
  "status": "live | http_<code>: <reason> | error: <type>: <message>"
}
```

Only records with `status: "live"` carry a usable `source_response`. The
caller (llm2bedrock-prompt-evaluator Step 4) merges these into `raw_results.jsonl`
and falls back to the dataset's stored `assistant_response` for any
prompt without a live response.
