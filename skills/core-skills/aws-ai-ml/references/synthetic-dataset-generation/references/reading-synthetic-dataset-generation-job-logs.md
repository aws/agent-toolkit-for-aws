# Reading a Synthetic Dataset Generation Job's Logs and Output

The synthetic dataset generation service writes and repeatedly repairs the code that generates your data, and it logs the
errors it is fixing at `ERROR` while logging the fixes themselves at `INFO`. So the log is not the
deliverable — **the row count is**. This reference gives the fixed list of signals you may act on,
the list you must ignore, and the remedy order for the two failure shapes that are real. Read it
before interpreting any synthetic dataset generation job log, and before touching a line of service-generated code.

Every number below is measured over 24 container logs from 22 real customization runs.

## Which mode ran, and which mode self-corrects

The submission shape decides whether the service can repair its own code:

| Submission | `report.json` `mode` | Phases | Self-repairs? |
|---|---|---|---|
| `DatasetSpecification.SpecS3Uri` | `phase1_and_phase2` | Phase 1 (code optimization) → Phase 2 (scale) | **Yes** |
| `DatasetSpecification.CodeArtifacts` | `phase2_only` | Phase 2 only | **No** |

The service source states the asymmetry outright: coherence failures are not transient, and *"the
orchestrator catches these in Phase 1 and feeds them into the refinement loop; in Phase 2 BYO they
bubble up."* Under `SpecS3Uri` the code is **regenerated per job**, so a resubmit is a fresh draw;
under `CodeArtifacts` you are handing the service fixed code with no repair loop behind it.

The consequence, stated once: **the same defect is invisible under `SpecS3Uri` and fatal under
`CodeArtifacts`.** A run that succeeded on its 10-record sample from a spec and then failed on full
generation from that sample's code artifacts has not hit a service defect — it has moved to the mode
that cannot heal.

## The five retry layers

Only the outermost is a "job attempt". Four of the five emit `ERROR` during normal, successful
operation.

| Layer | Marker | What it means |
|---|---|---|
| L0 | `Job attempt 1 of 3.` | Container-fault budget. All 24 observed logs say `1 of 3`; it never advances. Useless as a signal. |
| L2 | `prepare_batch (attempt N/3, batch_size=…)` | `batch_size` is always `3.5 × NumSamples`. Three failures ⇒ `=== FAILED:` ⇒ job status `Failed` ⇒ the SDK raises. |
| L3 | `execution_agent - ERROR - Generator execution error for sample N: …` | The Phase-1 refinement loop (`SpecS3Uri` only, max 5 iterations, 60% pass-rate target). |
| L4 | `parallel_generator - ERROR - Worker error: …` | One sample discarded; another worker draws from the 3.5× oversample budget. No code change, no re-plan. |
| L5 | `__main__ - ERROR - generator: …` | The **generated code's own** validate → retry → correct loop. |

**The errors are ERROR; the repairs are INFO.** Under `SpecS3Uri`,
`execution_agent - ERROR - Generator execution error for sample N` can fire for every sample in the
batch and the job still delivers in full: the orchestrator answers at WARNING
(`Generation quality is below target (0% pass rate, target 60%). Continuing to refine.`) and then at
INFO (`Refining code via CodeOptimizingAgent…`, `Plan updated to v2`,
`Code optimization successful. 9/10 samples passed (90% pass rate).`). Treating the ERROR block as
the outcome and stopping there is the single most common misreading of these logs. Verified case: a
generated module raised `'int' object is not subscriptable` on **all ten** samples, the service
repaired it in one refinement round, and the job delivered 10 of 10.

The Phase-1 loop has a second lever that is easy to miss because it is logged at INFO:
`Verifier quality issue detected: pass rate 0% is consistently below target (15% threshold).
Automatically adjusting verifier.` The service relaxes **its own verifier** until the code passes.
When that line is present, a full sample count proves nothing about quality — see *The reverse trap*.

At L5 the generated code recovers on its own and says so on the next line, e.g.
`ERROR - generator: computation parse failed attempt 1: …` immediately followed by
`INFO - generator: filing+computation extracted on attempt 1`.

## Signals you may act on

1. **`ecs_entrypoint - INFO - Sample generation complete: <got> of <req> samples generated
   (<failQC> failed quality checks).`** — `got` is the only authoritative in-log record count.
   **Ignore `failQC`**: it ranged from 0 to 1479 on jobs that delivered in full. The line is absent
   only when Phase 2 never ran (`Early exit: Phase 1 produced N samples (target: N)`) or the job
   hard-failed; its absence is not itself a failure.
2. **`ecs_entrypoint - ERROR - === FAILED: <exc> ===`** — the single job-fatal log line.
3. **`ecs_entrypoint - INFO - Progress: N/<req> samples generated (P%)`** — emitted exactly **nine
   times per job** (10% … 90%, never 100%). Nine ⇒ full delivery. **Zero, with a
   `=== PHASE 2: Generating N samples ===` banner present ⇒ zero samples.**
4. **`report.json`** at the job output root: `{status, mode, total_samples, dataset_size_requested,
   detected_output_format}`. Compare `total_samples` against `dataset_size_requested`.
   **`status: "COMPLETED"` with `total_samples: 0` is a real, observed outcome** — and the service
   still mints a DataSet ARN for it.
5. **The physical line count of `output/output_samples.jsonl`** (for CSV output: `output/output_samples.csv`, lines − 1). This is
   the ground truth that no status field can contradict.
6. **The launcher's own locally computed lines** — `parsed <N> record(s)`,
   `output jsonl files: []`, `Preview (<N> records from s3://…)`. These are computed from the
   downloaded file, so they cannot lie.

The output layout, relative to the job output root — note the returned `DataSet.source` **is** the
`output/` subdirectory, so the rest sit one level above it:

```
report.json
token_usage_report.json
output/output_samples.jsonl
generation_code/{generation.py,verifiers.py}
job_metadata/verified_samples.jsonl
```

`token_usage_report.json` holds the Bedrock tokens the job used, in total and per model. Report
them after the record counts; they say nothing about whether the job delivered.

`generation_code/generation.py` is the **post-refinement** code the service converged on, not the
first draft it tried. Under `SpecS3Uri` it is already corrected before you ever see it.

**Triage recipe.** Two commands answer "did this job deliver?" on any synthetic dataset generation log:

```
grep -E 'Sample generation complete|=== FAILED|finished with status|parsed [0-9]+ record|output jsonl files' <log>
grep -c 'ecs_entrypoint - INFO - Progress:' <log>   # 9 == full delivery, 0 == none
```

Two traps in that grep, both measured:

- **Grep the whole file, not a tail window.** The summary lines are followed by a client-side
  epilogue, so they land roughly 90–95 lines from the end. A `tail -80` misses
  `Sample generation complete:` and `=== FAILED:` on real logs while still showing plausible
  output — the worst possible failure mode for a triage command.
- **The teed logs are hard-wrapped at roughly 100 columns**, so
  `Sample generation complete: 0 of 10` and `samples generated (35 failed quality checks).` arrive
  as two separate physical lines. Match the first fragment, never the whole sentence.

## Signals you must ignore

| Do NOT use | Why |
|---|---|
| Any count or presence of `ERROR` lines | See the rule below. |
| `Job attempt 1 of 3` | All 24 observed logs say `1 of 3`; it never advances. |
| `Verifier requires LLM: True` | **All 20 observed occurrences say `True`**, including every run whose spec forced deterministic verification. One run filed this as a service defect and was wrong. |
| `parallel_generator - INFO - AST verdict: AUX-ONLY blockers …` | A thread-safety gate that selects the worker count. Not a verdict on the code's quality. |
| The service's `data-validation/**/quality_report.json` | On a **successful** 1000-record job that was then trained on without incident, it reported `validRecords: 0`, `failureRate: 1.0`, `WRONG_TYPE: field 'prompt' present but not a str` — the prompts were chat-message lists. Do not read it, not even "for context". |
| The client panel's `Sample Count` trajectory | Not reliable. One job polled `0 / 1000` **seventeen times** and then jumped to `1000 / 1000`, and it delivered 1,000 real rows. It is a race between poll cadence and a burst write. Human-facing hint only. |

**ERROR volume in a synthetic dataset generation log is not a failure signal.** Measured across 24 container logs: one job
emitted **3,423** `__main__ - ERROR` lines and delivered **1000/1000** usable records; another
emitted **zero** ERROR lines and delivered **0/10**. Roughly 95% of the ERROR volume comes from two
loggers — `__main__` (the generated code's own retry logging) and `parallel_generator` (per-sample
discards against the 3.5× oversample budget) — that are *designed* to emit errors during normal,
successful operation. Do NOT count them. Do NOT report them as a defect. Do NOT let them decide
whether an iteration succeeded.

## The two genuine failure shapes

**Shape 1 — the loud failure.** `=== FAILED: <exc> ===`, job status `Failed`, and the SDK raises
`DataPreparerJobFailedError`. Typically three `prepare_batch attempt N/3 failed` lines first. There
is no ambiguity here; read the exception and fix its cause.

**Shape 2 — the silent zero-sample `COMPLETED`.** Many `Worker error:` lines within a few
milliseconds, `Sample generation complete: 0 of N`, job status `Completed`, and a DataSet ARN is
still created. `parallel_generator` logs `Worker error:` followed by `str(exception)`, so the split
is lexical and exact:

- **Unhandled exception on the hot path** — a bare quoted token or a bare Python type error with no
  prose: `Worker error: 'weight'`, `Worker error: 'set' object is not subscriptable`. Expect zero
  samples.
- **The generated code's own quality gate** — a prose message from a deliberate `raise`:
  `Worker error: Failed to generate valid filing_excerpt and computation after 3 attempts`,
  `Worker error: Question-echo detected in payload: …`. **1,060** of these appeared on a job that
  delivered 1000/1000.

This classification is **diagnosis, never the verdict.** The counts in *Signals you may act on*
decide whether the job delivered; the message shape only tells you which remedy to reach for.

**Remedy order — do not skip a rung.**

Report the failure to the user, then recommend one of the following options. Wait for the user's
explicit approval before every resubmission.

1. **Resubmit the same job once.** The service regenerates the code per job, so a resubmit is a
   fresh draw. One run hit a 0-of-1000 `'set' object is not subscriptable` failure, resubmitted
   once, and got 1000/1000 — at one third the effort of the run that AST-scanned the artifacts and
   switched modes for the identical failure.
2. **Resubmit from the spec** (`SpecS3Uri`), which restores the Phase-1 self-repair loop that a
   `CodeArtifacts` submission does not have. `SpecS3Uri` is not immune — per-job regeneration is a
   fresh dice roll — but it is the only rung that can repair itself.
3. **Fix the spec** and resubmit. Almost every "service bug" in the run history root-caused to a
   spec instruction: an instruction to collect entities made the code generator call an LLM inside
   `prepare_batch` where the client is `None`; a "no shared 12-word span" rule fired on contract
   boilerplate and rejected nearly every candidate; a literal "every numeric literal must appear in
   the prompt" rule was implemented by *deleting* offending numbers.
4. **Only then**, and only with the user's explicit approval, edit the code artifacts.

**A per-file check cannot see the `'set'` bug — compare the two files.** `generation.py` and
`verifiers.py` resolve into one namespace under `CodeArtifacts`, and `verifiers.py`'s module-level
bindings win. Before reusing code artifacts, compare the **module-level** constant assignments in
both files: a name bound to a list or tuple in one and a set or dict in the other is a blocker. In
the run that produced this failure, three names collided that way — declared as lists at the top of
`generation.py` and as sets at the top of `verifiers.py` — and `generation.py`'s
`random.choices(question_type_values, weights=…, k=1)` then raised on every one of 3,500 attempts.
The regenerated `SpecS3Uri` code that worked shares **no** module-level names between the two files
at all: it declares them inside a function. Module scope is the whole discriminator. Do not go
looking for a subscript of a set in `generation.py` — the subscript is on the *result* of
`random.choices(...)`, which is exactly why scanning each file on its own finds nothing and invites
the wrong conclusion.

## The reverse trap: a clean log is not proof

A log with zero `Worker error` lines, zero `__main__` ERROR lines, and
`Sample generation complete: 10 of 10 samples generated (0 failed quality checks)` delivered
**0 of 10** usable records. Upstream in the same log the orchestrator had already fired
`Automatically adjusting verifier.` — it relaxed the gate until the code passed. The only check that
caught this was re-running the job's own delivered `verifiers.py` locally over every produced row.

So: **when `Automatically adjusting verifier.` appears, or whenever the delivery is about to feed
training, re-verify the output yourself.** Import the delivered `verifiers.py` and call
`verify_sample` on every row of `output_samples.jsonl` (write the loop into the run's `scripts/`).
**Count exceptions separately from failures.** `verify_sample` may need `auxiliary_datastore`
contents that only the job's `prepare_batch` built, so a raised exception means the check could not
run — it does **not** mean the row is invalid. Getting that backwards manufactures exactly the false
alarm this document exists to prevent.

Re-verification is still not enough on its own. Three consecutive jobs in one iteration each
reported 1000/1000 `Completed` and each passed local verification, yet two delivered the wrong
answer-precision distribution: the sandbox forbids `str.format`, every sample needing a decimal
answer raised, and the 3.5× oversample budget silently backfilled with integer-answer samples until
the count was met. **The self-healing is what hid the defect.** Compare the produced value mix
against the distribution the spec asked for before you train on it.

## Never hand-edit the service-generated code

**Hand-editing `generation.py` / `verifiers.py` is a LAST RESORT, not the first move.** Once you
edit the code, the code and the spec are permanently desynced and every later iteration inherits the
divergence — `CodeArtifacts` submissions never re-read the spec.

The run history is unambiguous about the cost:

- One iteration spent **5 synthetic dataset generation jobs and about 5 hours** chasing a Phase-1 self-correction. It
  **discarded two fully validated 1000/1000 datasets**, hand-patched the service-generated code, and
  the iteration then regressed dev by −0.0300 and terminated the loop. That run's own state file,
  written one iteration earlier, states the rule it later broke: *"Fixed the spec and re-ran the
  sample instead of editing generated code artifacts … editing code would have desynced code from
  spec permanently."* Nothing recorded the reversal.
- Another run did **four** "repair" regenerations, **stopped and invalidated two live 27B training
  grids** mid-flight, and rewrote **41.6%** of its generated rows with a bespoke LLM judge. Its
  `PLAN.md` and run report mention none of it; the only durable trace is the filenames.

If the samples are unusable because the job produced **nothing**, that is the remedy order above,
not a code edit. If the samples are unusable because the **content** is wrong, that is a spec
problem — fix the spec at the iteration boundary.

**Confirming deterministic verification.** When a spec forces deterministic, pure-Python
verification, confirm the service honoured it by reading the **delivered** `verifiers.py`:
`verifier_llm` must appear only as a parameter and never be called or attribute-accessed. Do **not**
use the log line `Verifier requires LLM: True` as evidence — it says `True` in all 20 observed
occurrences, including the runs whose specs forced deterministic verification.

## Rules

- Decide whether a job delivered from the record counts alone: `Sample generation complete:
  <got> of <req>`, the `Progress:` line count, `report.json` `total_samples`, and the physical row
  count of `output_samples.jsonl`. Never from ERROR lines.
- `status: "COMPLETED"` does not mean data was produced. A DataSet ARN does not mean data was
  produced. Check `total_samples` and the output file before training on anything.
- Never count, cite, or act on `ERROR` volume. 3,423 ERRORs delivered 1000/1000; zero ERRORs
  delivered 0/10.
- Never treat `Job attempt 1 of 3`, `Verifier requires LLM: True`, `AST verdict: AUX-ONLY blockers`,
  the DQE `quality_report.json`, or the client `Sample Count` trajectory as evidence of anything.
- On a zero-record delivery: report the failure to the user and recommend the remedy ladder
  (resubmit once → resubmit from spec → fix the spec). Wait for the user's explicit approval
  before every resubmission. Edit the generated code only as a last resort, only with explicit
  approval, and record why.
- Before reusing `CodeArtifacts`, compare the **module-level** constants in `generation.py` and
  `verifiers.py`. A list-versus-set collision on a shared name is a blocker, and no per-file scan
  will find it.
- When `Automatically adjusting verifier.` appears, re-verify every produced row with the delivered
  `verifiers.py`, counting exceptions separately from failures, and check the produced value mix
  against the spec's target distribution.
