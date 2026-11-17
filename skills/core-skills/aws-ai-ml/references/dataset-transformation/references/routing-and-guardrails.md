# Routing & Guardrails (single source of truth)

This file defines the **client-side routing thresholds** the skill uses to decide
whether a transformation uses the **local lane**, the **API lane** (CreateJob
DataTransformation), or needs sharding because no validated whole-file workflow
applies. The local lane executes in the client/agent process; the API lane runs
on managed service compute. Every other reference and template MUST refer to these
constant NAMES, never the literal numbers, so the values change in exactly one place.

## Routing constants

| Constant      | Value | Applies to         | Meaning                                                                                                                                                         |
| ------------- | ----- | ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LOCAL_CAP`   | 50 MB | local sources      | recommendation boundary for a **local** file: at/under → local is a safe recommendation; above → recommend the API (a large local run risks crashing the agent) |
| `API_CEILING` | 10 GB | validated workflow | above this → this reference has no validated whole-file workflow; recommend sharding or sampling, or offer a clearly labeled best-effort API run               |

`API_CEILING` is the largest whole-file input covered by this reference's
validation evidence; it is not a documented universal DataTransformation API
limit. Above it, recommend sharding or sampling below the ceiling as the
validated path. Never set up or run the whole file locally. A managed API run
may proceed only as clearly labeled best-effort guidance, after disclosing the
validation gap and receiving the user's explicit confirmation.

### Required large-local warning

When the user explicitly chooses the local lane for an input above
`LOCAL_CAP`, say exactly: **"This local run may be slow and may crash the
client/agent."** Say it once when acknowledging or confirming the local choice
and repeat it in the reply that provides or sets up the local artifact. Do not
replace either warning with benchmarks, streaming claims, bounded-memory
claims, or throughput estimates.

## Mandatory first-response contract

For any request to run, set up, or prepare to run a transformation, read this
file **before** building a spec or inspecting the input. Until the route is
confirmed, permitted tool activity is limited to reading the skill and its
references plus one metadata-only size probe: filesystem metadata for an exact
local file, or `HeadObject` for an exact S3 object. Do not list prefixes,
download, read, parse, or sample data; create or save a Transformation Spec;
write/show/test transform code; upload/copy data; or submit/run a job. A probe
failure is non-blocking: state the recommendation conditionally from the known
source and size. A request such as "remove the duplicates" is transformation
intent, not permission to choose the local lane.

**Check for an already-confirmed lane before asking anything.** If the user
says where the transformation should run—such as "I want to run this locally
on my laptop, not through the API"—the local lane is already confirmed below
`API_CEILING`. Do not ask local versus API again, do not merely recommend
local, and do not stop at another confirmation. Continue directly with the
local workflow. By contrast, saying only that the file is located on a laptop
does not choose the execution lane.

Use the source and estimated size stated by the user or already present in the
request/context. If size is missing, the metadata-only probe above is allowed
before the routing reply. When metadata is unavailable or the source is not an
exact object/file, state the `LOCAL_CAP`-based recommendation conditionally
instead of escalating to a listing, download, or content read.

The routing response is a hard stop. End the reply immediately after the
routing question/default note. Do not include fenced code, inline code,
commands, examples, pseudocode, or an "optional" implementation. Even a short
illustration such as `awk`, `sort -u`, `uniq`, `jq`, or a Python snippet is
transform code and must wait for the user's route choice. Do not describe the
script, notebook, operator parameters, algorithm, threshold, or later
implementation steps in this reply. For deduplication, the only permitted
operation detail is one plain sentence that fuzzy / near-duplicate removal is
the default and exact dedup is available on request.

Use one of these response shapes:

- **Above `API_CEILING`:** state that this reference has no validated
  whole-file workflow at that size and recommend sharding or sampling below
  the ceiling. Decline a whole-file local setup or run. For an API-capable
  request, also offer a clearly labeled best-effort whole-file managed API path
  with the normal cost, resource, reversibility, and approval disclosures; do
  not submit it without explicit confirmation.
- **S3/Hub below the ceiling:** state that the source defaults to the SageMaker
  DataTransformation API and that nothing will be submitted before
  confirmation, then ask whether to use the API lane or explicitly process it
  locally. If the user already chose local, do not ask again; for inputs above
  `LOCAL_CAP`, emit the required large-local warning above before providing
  local code and repeat it in the artifact/setup reply.
- **Local below the ceiling:** ask local vs. API as a standalone question,
  recommend local at/under `LOCAL_CAP` and API above it, and stop.
- **API-only operator:** state that `LanguageFilter` or `PiiRedaction` has no
  local-lane implementation and ask for confirmation before API setup/submission.
  If a PII hand-off has not chosen an action, state without adding a second
  question that the available actions are tag, redact, and drop. Also state
  that a non-mutating Data Quality PII preview is available before redaction;
  do not add a second question for the preview in this route-only reply.

After the user confirms, proceed to spec/artifact work on only that lane. Never
emit multiple alternative implementations "for convenience."

### Narrow exception: show-only artifact, with no action

If the latest request clearly asks only for one complete inline script,
notebook, command, or code artifact and does not authorize action, the request
is artifact authoring rather than execution. "Show me exactly what you'd run,"
"do not execute/start/submit it," and code-only requests qualify; the user need
not enumerate every prohibited side effect. It may proceed without treating
the artifact itself as a submitted route choice:

- read the relevant operation reference and show exactly one inline artifact;
- do not save, test, probe, upload, submit, or run anything;
- above `API_CEILING`, never show a whole-file local artifact. Recommend a
  sharding, sampling, or already-bounded artifact; a whole-file managed API
  artifact is allowed only when clearly labeled as best effort and outside this
  reference's validation evidence;
- select the artifact lane deterministically: API-only operators use the API
  lane, S3/Hub defaults to the API lane, and a local source uses an explicit lane choice or
  otherwise the size-based recommendation;
- if the local lane remains unsettled, present local versus API, recommend by
  `LOCAL_CAP`, show only the recommended artifact, and continue to wait for
  confirmation before any later execution. After the artifact, state exactly:
  **"This artifact does not select a lane. I am still waiting for your lane
  choice and will not execute it without separate approval."** Ask only for
  the lane choice, not whether to run the artifact.

This exception never applies to a plain "remove the duplicates" request, never
authorizes local language detection or PII masking, and never authorizes the
artifact to be executed later without a separate confirmation.

**Apply the `API_CEILING` workflow gate FIRST.** Below that ceiling, routing
keys on the source location (S3/Hub vs. local), then the chosen lane is
confirmed with the user before executing. Decision order (see `../overview.md`
Step 0 "Route execution intent before spec work"; Step 2 only revalidates the
confirmed lane):

1. **estimated size > `API_CEILING` → disclose the validation gap and recommend
   sharding or sampling.** Evaluate this FIRST. Decline a whole-file local setup
   or run even when the user explicitly requests it. For the managed API, the
   user may instead confirm a clearly labeled best-effort whole-file path that
   is not validated by this reference. A show-only whole-file artifact is
   likewise limited to that best-effort managed API path.
2. **Source is S3 / Hub → default to the API lane.** Do **not** execute yet: tell the user
   you'll process it on the DataTransformation API and **confirm they're OK with that
   approach, or whether they want to explicitly run the transform locally instead (not recommended).**
   Only an explicit user request moves an S3/Hub file off the API lane.
3. **Source is local → ask the user to choose the local lane vs. the API lane,** and **make a
   size-based recommendation**: at/under `LOCAL_CAP` → local is a safe recommendation;
   above `LOCAL_CAP` → recommend the API (running a large local file in-process risks
   crashing the agent). The user confirms the final choice either way.

Code generation and intents without a built-in operation are classified after
the lane is confirmed, except for supplied transformer code and an explicit
request for the service CodeGen path; those API intents use the exceptions
below.

## Routing procedure

Apply the `API_CEILING` workflow gate first. Below it, decide the lane from the
**source location**, then confirm with the user before executing. Inputs: the
**source location** (S3/Hub vs. local — from the spec `input`),
the file size from the Step 0 metadata-only probe or Step 2 revalidation
(`ContentLength` for S3, on-disk size for local,
compared against `LOCAL_CAP` / `API_CEILING`), the row count (used ONLY for the
≥10K-rows time-estimate trigger and manifest counts, never as a routing threshold),
the operation(s) in the spec, and any explicit user lane preference.

1. **No validated whole-file workflow above `API_CEILING` — check first.** If
   the dataset is larger than `API_CEILING`, say that the size is outside this
   reference's validation evidence and recommend sharding or sampling it below
   the ceiling. Do not describe the ceiling as a universal service limit.
   Decline whole-file local setup and execution even after an explicit local
   request. A managed whole-file API setup or run may proceed only as
   best-effort general AWS guidance after the user explicitly confirms that
   unvalidated path. A show-only request may receive that same clearly labeled
   best-effort API artifact, but it authorizes no submission or run.
   Preserve applicable cost disclosures and service/operator limits; never
   represent the run as validated by this reference.

2. **S3 / Hub source → default to the API lane.** If the input is an `s3://` path or a
   Hub-registered dataset, the default is API-lane execution via the `DataPreparer`
   pySDK. **File size does NOT change this** — a small S3/Hub dataset (even well under
   `LOCAL_CAP`) still defaults to the API, because the source location decides the
   default, not the size. `LOCAL_CAP` governs only a **local** source; never
   apply it to an S3/Hub source to justify a local run. Tell the user you'll run it on
   the API and confirm before submitting (do not submit the job until they confirm). The
   file stays on the API lane **unless the user explicitly asks to run it locally** — honor
   that request. For a file above `LOCAL_CAP`, emit the required large-local
   warning before proceeding and repeat it in the artifact/setup reply.

3. **Local source → ask the user: local lane or API lane,** with a size-based recommendation:
   at/under `LOCAL_CAP` → recommend local; above `LOCAL_CAP` → recommend the API, because
   running a large file locally in-process risks crashing the agent. Honor
   the user's final choice (if they choose local for a large file, warn and proceed).

   **The question is a hard stop.** The size-based recommendation is a recommendation, not a
   decision: a small file, or a request like "remove the duplicates", is NOT the user choosing
   local. Ask local vs. the API as its own message (do not bundle it with other questions),
   state your recommendation and why, and wait for the answer. Before the answer, do not
   write, show, run, or probe any transform code, including inline code, an example,
   an optional implementation, or a trial run on a copy of the file.
   Only an explicit statement from the user that the file is local and should run locally
   (next paragraph) counts as already answered.

   **An explicit local request for a local source is binding.**
   When the user has already said the file is on their machine AND that they want to run
   it locally, that choice is made — do NOT re-recommend the API, do NOT ask them to
   justify it again, and above all do NOT upload the local file to S3 to force the API
   lane. For a large input, emit the required large-local warning, then generate
   the LOCAL script rather than `DataPreparer`/`DataSet.create` API-lane code. Writing
   `INPUT_SOURCE = "s3://…"` with an "upload it first" note for a file the user said is
   local is a routing ERROR. (The only thing that overrides an explicit local request is
   the `API_CEILING` workflow gate in the first routing step.)

**Below `API_CEILING`, always confirm the approach — both sources.** Whatever
lane you land on (the S3/Hub API-lane default, or the local recommendation),
**tell the user the lane and the reason and confirm they're OK with it, or
whether they want the other route**, before executing.
Examples: "this dataset is in S3, so I'll run it on the SageMaker DataTransformation
API — let me know if you'd rather I process it locally instead," or "this is a local
file at ~30 MB, so I'd recommend running it locally; I can send it to the
DataTransformation API instead if you prefer — which would you like?" Do not proceed
until the user confirms.
Above `API_CEILING`, do not ask a local-versus-API lane question. Recommend
sharding or sampling; for an API-capable request, ask whether the user wants
that validated path or the clearly labeled best-effort whole-file managed API
path.

For the API lane, also state that the job can incur SageMaker charges and
leaves the source unchanged. Raw S3 registration creates a new input DataSet
version. Full-dataset jobs create output DataSet versions; CodeGen Job 1
creates only review artifacts and no output DataSet. Offer background
submission. For the local lane, state which confirmed project outputs may be
created or overwritten and that no SageMaker job charge applies.

**Mixed workflows.** The routing recommendation does not change with workflow
composition — source location and (for local sources) the single `LOCAL_CAP`
recommendation boundary apply regardless of which operators are present.

**Exception — explicit service CodeGen selects the API lane.** When the user
explicitly names the service CodeGen capability or path, treat that request as
the API lane selection; do not offer or re-ask local versus API. A generic
request to generate code does not trigger this exception. Follow the
capability-selection list in `api-execution-flow.md`, then apply the normal size,
cost, resource, reversibility, and approval requirements. Step 1 (the
`API_CEILING` workflow gate) still applies first.

**Exception — supplied transformer code means API direct BYOC.** A request to
run supplied transformer source selects the API lane unless the user explicitly
asks for local execution. Follow the capability-selection list in
`api-execution-flow.md`, then apply the normal size disclosure and API
confirmation. Step 1 (the `API_CEILING` workflow gate) still applies first.

**Exception — language filtering is API-only.** `LanguageFilter` needs a
language-identification model that exists only in the service, so this reference has no validated local
execution for it: a language filter takes the API lane from any source,
and the local option in steps 2–3 does not apply to it (do not offer local for a local
source; a request to run it locally cannot be honored). Step 1 still applies first. The
service also applies its own LanguageFilter input cap, set
independently of `API_CEILING`; step 1 is the only client-side size check (see
`api-operator-configs.md`, "LanguageFilter"). A local `filter` step can only use a language
field the records already carry (for example a `dataset-quality` `dq_language_detection_flagged__<column>`
column); never write local language-detection code or recommend a local language-ID
library as a substitute, even for a tiny local file. Say why when confirming the lane
("language filtering uses the API lane, even for small files").

**Exception — PII redaction is API-only.** `PiiRedaction` detects PII with a model that
only the service calls, so this reference has no validated local execution for it either: a PII step takes the
API lane from any source, and the local option in steps 2–3 does not apply
to it. Step 1 still applies first. The service applies its own PiiRedaction input cap, set
independently of `API_CEILING`, and a record limit the skill checks before submitting (see
`api-operator-configs.md`, "PiiRedaction" → Limits). Never write local PII detection or
redaction code (regexes, NER models, or a local `filter` / `map` step) or recommend it as
a substitute, even for a tiny local file. The
default API capability is the `PiiRedaction` built-in. After lane confirmation,
API capability overrides are owned by `api-execution-flow.md`.
The
exception covers finding PII inside a field's text only: dropping, renaming, or reshaping a
whole column the user names (for example "strip the PII column customer_name") is a column
change that follows the normal routing, because `PiiRedaction` cannot remove a column. Say
why when confirming the lane ("PII redaction uses the SageMaker DataTransformation API lane,
even for small files"). Unless the request is already a Data Quality hand-off,
state that the non-mutating `pii_detection` preview can estimate affected rows
and entity types before the user chooses a redaction action.

When a user says not to run AWS commands, treat that as a no-execution or
show-only constraint. Show the correct API-lane artifact when requested; never
reinterpret it as permission to replace `LanguageFilter` or `PiiRedaction`
with a local detector, regex, NER model, or masking script.

## Provenance & status (read before trusting the numbers)

- **NOT code-enforced in this skill.** These are documented workflow gates and
  routing defaults; there is no pre-existing enforcing constant in the skill.
  The user always confirms the
  final local-lane/API-lane choice (a local run
  above `LOCAL_CAP` is honored only after a crash/performance warning; a `LanguageFilter`
  or `PiiRedaction` step has no local option). Above `API_CEILING`, this
  workflow refuses whole-file local setup and execution. It recommends
  sharding or sampling for the validated API path, while allowing a clearly
  labeled best-effort managed API path after explicit confirmation.
- **`LOCAL_CAP` default.** `LOCAL_CAP` defaults to 50 MB — the boundary at which a
  **local** file stops being a safe local-execution recommendation. The user may
  override this for specific cases.

## Client caps vs. service compute routing (do not conflate)

The constants above are the **skill's client-side** local-lane/API-lane decision. The
DataTransformation **service** applies its OWN, separate routing once a job is
submitted — different numbers, different purpose, and NOT a customer knob. The skill
never predicts or exposes how the service will run a job; it submits the job and
surfaces `DescribeJob` status.

Implication: `API_CEILING = 10 GB` is this skill's whole-file validation
boundary, independent of the service's own maximum. Keep them as independent
named values; do not assume they move together or state that the API universally
rejects inputs above this boundary.
