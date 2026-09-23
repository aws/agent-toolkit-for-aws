# Interpreter

The plugin-shared contract for DSL-driven migration skills: how to read and act on
the structured frontmatter that phase files carry. It is skill-AGNOSTIC — any
migration skill under this plugin can author its phases to this grammar and drive
execution from this one interpreter. When a phase file begins with a `---` YAML
block, read it first and act on the keys below, then execute the phase's prose body.

Frontmatter is being introduced phase-by-phase. A phase file with no frontmatter
runs entirely from its prose, as before.

## Skill bindings (what SKILL.md declares)

This contract is skill-agnostic; a skill BINDS it in its SKILL.md. Every binding has
a default, so a skill that declares nothing (e.g. heroku-to-aws) runs entirely on the
defaults. Where a skill declares a binding, the declaration is part of this contract
— not an override of it.

| Binding           | Default                                              | A skill MAY declare                                                                                                                                                                                                                                                                                                     |
| ----------------- | ---------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Entry phase       | — (always declared)                                  | the backbone head carrying `_init: true` (§ The interpreter loop, step 1)                                                                                                                                                                                                                                               |
| Run root          | `.migration/`                                        | its own state directory (e.g. `.agent-advisor/`). Throughout this contract, `.migration/` means "the skill's run root" and `$MIGRATION_DIR` means "the run directory under it" — a skill may name that variable differently (e.g. `$RUN_DIR`); the run-id format (`MMDD-HHMM`) and single-run discipline are unchanged. |
| State shape       | `references/vendored/state/phase-status.schema.json` | its own state-file shape, documented in SKILL.md, when its state carries skill-specific keys. The update protocol and validation below still apply.                                                                                                                                                                     |
| Resolved statuses | `pending` / `in_progress` / `completed`              | additional RESOLVED statuses (e.g. `skipped`, `not_applicable`) for phases its routing marks not-applicable. A resolved status satisfies `_requires_phase` and the backbone walk exactly like `completed`; state validation treats declared statuses as recognized.                                                     |
| Backbone routing  | every backbone phase runs                            | conditional-routing prose (e.g. "entry-point routing"): rules that resolve a backbone phase WITHOUT running it. When the loop advances into such a phase, mark it per the rule (e.g. `skipped`) and continue along its `_advances_to` in the same step — never leave it `pending` behind a completed successor.         |

Sidebar PLACEMENT was already the skill's to declare (§ Backbone vs sidebar);
these bindings extend the same principle to naming, state shape, and routing.

## The interpreter loop

This is the execution controller — how you drive a migration from invocation to
completion. It is skill-agnostic: the phase set, ordering, and per-phase behavior
are all DERIVED from the phase files' frontmatter (never hardcoded here).

**On each invocation:**

1. **Load state.** Find the run directory under the skill's run root (§ Skill
   bindings; default `.migration/`) and read its `.phase-status.json`. If none exists, this is a COLD START: load the skill's
   DECLARED entry phase (the skill's SKILL.md names it) and run it — it carries
   `_init: true` and establishes state (see § `_init`). Do NOT scan every phase's
   frontmatter to find the root; the skill declares its own entry so this is a
   single, direct load. (The entry phase is, by contract, the backbone head — the
   one phase with no `_requires_phase` and with `_init: true`; CI enforces that
   these coincide, so the declared entry is unambiguous.) "Run it" means run it per
   step 5 below — including its `_exec` dispatch if it declares one. The `_init`
   state setup always happens in THIS (main) window BEFORE any dispatch (a
   dispatched sub-agent never bootstraps state; it is handed an initialized
   `$MIGRATION_DIR`).
2. **Determine the current phase (deterministic):**
   - **Deferred-advance sidebar resume (mandatory):** If `current_phase` is
     set, `phases.<current_phase>` is already `"completed"`, and a skill-declared
     sidebar key (e.g. `workshop`) is `"pending"` or `"in_progress"` because
     that backbone phase defers advancing `current_phase` until the sidebar
     resolves (see SKILL.md sidebar orchestration — what-if workshop after
     Estimate is the canonical case), **do not re-run** the completed backbone
     phase. Follow SKILL.md: re-present the sidebar offer if `"pending"`, or
     load `references/phases/<sidebar>/<sidebar>.md` if `"in_progress"`.
     Explicit phrases that match the sidebar `_trigger` also enter it when its
     `_requires_phase` artifacts exist — still without re-running Estimate (or
     whichever predecessor completed).
   - Else if `current_phase` is present in `.phase-status.json`, use it (it is
     authoritative). This is the normal WARM-START path.
   - Otherwise (state exists but has no `current_phase`) walk the backbone in order
     (see § Backbone vs sidebar) and pick the FIRST phase whose
     `phases.<phase>` is not RESOLVED (`"completed"` or a skill-declared resolved
     status — § Skill bindings). If all backbone phases are resolved, the state is
     the terminal (`complete`). (On a cold start there is no state to read —
     step 1's declared entry phase is used directly.) When the skill gates a later
     backbone phase on a sidebar being `"completed"` (e.g. Generate requires
     `phases.workshop == "completed"`), honor that gate while walking.
3. **Validate state before proceeding.** See § State-file validation below. STOP
   on any inconsistency rather than guessing.
4. **Load the phase orchestrator.** A phase's orchestrator file is, by convention,
   `references/phases/<phase>/<phase>.md`. Load it in full and read its
   frontmatter first. (Sidebar resume from step 2 loads the sidebar
   orchestrator instead — still never as `current_phase`.)
5. **Run the phase.** Run its `_preconditions` entry gate (§ Gate protocol) in
   THIS (main) window; if it passes, set the phase `in_progress`, then run the
   phase's WORK — its `_fragments` (each when its `_trigger` fires) then its
   `_assemble` — and finally run its `_postconditions` completion gate in THIS
   window.
   - **If the phase declares `_exec` (§ `_exec`): dispatch the WORK, do not run it
     inline.** On a host with a sub-agent mechanism, spawn ONE fresh sub-agent at
     the `_exec._agent` capability tier and have it run the phase's fragments +
     assembler with file-only I/O (it reads `_input` from `$MIGRATION_DIR`, writes
     the phase's `_produces` artifact(s) back to `$MIGRATION_DIR`, and returns a
     terse status — it MUST NOT emit `HANDOFF_OK`, touch `.phase-status.json`, or
     converse with the user). The entry gate (already run above), any `_init` state
     setup, and the completion gate + state transition all stay in THIS window. On
     a host with NO sub-agent mechanism, run the same work inline here (the tier is
     inert — see § `_exec`). Either way, re-read the produced artifact(s) from disk
     before the completion gate.
   - **Otherwise, run the fragments + assembler inline in this window** (the
     default).
6. **Advance only on `HANDOFF_OK`.** A phase is complete ONLY when its completion
   gate emits the `HANDOFF_OK` line (§ Gate protocol). On `GATE_FAIL`, STOP — do
   not update `.phase-status.json`, do not load the next phase; tell the user
   which phase to re-run. Never load the next phase from a completion message that
   lacks `HANDOFF_OK`.
7. **Update state.** After `HANDOFF_OK`, apply the phase-status update protocol
   below, then load the next phase — the current phase's `_advances_to` — and
   repeat from step 4. When `_advances_to` is a terminal (`complete`), the
   migration is complete. If the skill's routing (§ Skill bindings) marks the next
   phase not-applicable, resolve it per the routing rule (e.g. set it `skipped`)
   and continue along that phase's `_advances_to` — in the same state write.

Sidebar phases (§ Backbone vs sidebar) are OFF this loop — they are entered
by their own `_trigger` at a point the skill's orchestrator (SKILL.md) chooses,
and return control without changing `current_phase`.

### State discipline

- **Single run directory.** Use ONE `$MIGRATION_DIR` (`<run root>/[MMDD-HHMM]/`;
  default `.migration/[MMDD-HHMM]/`) for the entire migration; do not mix artifacts
  across sessions under the run root.
- **Re-read from disk.** Before each phase and before each gate, read the required
  artifacts from `$MIGRATION_DIR/`. Do not rely on chat memory.

### Phase-status update protocol (read-merge-write)

Update `.phase-status.json` with read-merge-write, never a blind overwrite:

1. Read the current file before every update.
2. Change only the phase key(s) being advanced and `last_updated`.
3. Leave prior completed phases unchanged.
4. Set `current_phase` to the next phase (the completed phase's `_advances_to`),
   or the terminal (`complete`) when the backbone is exhausted.
5. Write the full file in the same turn as the phase's final output message.

Status values progress `"pending"` → `"in_progress"` → `"completed"` and never go
backward (except a confirmed re-entry reset — see § `_re_entry_guard`). A
skill-declared resolved status (§ Skill bindings) is set directly from `"pending"`
when the skill's routing resolves the phase without running it. At most one
backbone phase is `"in_progress"` at a time.

### State-file validation

When reading `.phase-status.json`, STOP (surface the diagnostic, do not proceed or
guess) on any of:

1. **Multiple run directories** under the skill's run root: list them with their
   phase status and ask `[A] Resume latest / [B] Start fresh / [C] Cancel`.
2. **Invalid JSON:** "State file corrupted (invalid JSON). Delete the file and
   restart the current phase."
3. **Unrecognized phase name** in `phases` (not a phase the skill declares).
4. **Unrecognized status** (not `pending` / `in_progress` / `completed` or a
   resolved status the skill declares — § Skill bindings).
5. **Invalid `current_phase`** (present but not a declared phase or the terminal).
6. **Out-of-order completion:** a later backbone phase is `"completed"` while an
   earlier one is not — "Inconsistent phase ordering detected. Reconcile
   `.phase-status.json` before resuming."

(The single-active-phase invariant is enforced structurally by the first phase's
`_preconditions._check_single_active_phase`; see § Gate protocol.)

## Phase frontmatter keys

| Key                 | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `_phase` / `_title` | the phase's id and human title                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `_kind`             | `backbone` (default when absent) or `sidebar`. A **backbone** phase is a step on the linear lifecycle (see below). A **sidebar** phase is off-backbone — optional, entered by a phase-level `_trigger`, returns control instead of advancing. `feedback` is a sidebar.                                                                                                                                                                                                                                                                           |
| `_requires_phase`   | the phase that must be `completed` before this one may start (omitted for the first phase; on a sidebar, its minimum precondition)                                                                                                                                                                                                                                                                                                                                                                                                               |
| `_init`             | `true` only on the first phase — this phase establishes migration state before its fragments run (see below)                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| `_interactive`      | (optional) does the phase's WORK (fragments + assembler) prompt the user? Declare `false` to make the phase a dispatch candidate (required alongside `_exec`); a dispatched worker is file-only and cannot converse. Absent or `true` = the phase runs inline. Interactive phases (clarify, feedback) cannot be dispatched.                                                                                                                                                                                                                      |
| `_input`            | what the phase reads — prior-phase artifacts, or `workspace` for the initial file scan                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `_knowledge`        | the reference/data files the phase consults (`knowledge/**.json` sizing/mapping/pricing tables). Each entry is `{ file, _when? }`; each `file` must resolve on disk. Load a knowledge file ONLY when its `_when` holds — see § `_knowledge`.                                                                                                                                                                                                                                                                                                     |
| `_trigger`          | (sidebar phases only) how the phase is ENTERED — same forms as a fragment `_trigger` (below). `feedback` uses `_when: "user opts in"`. Backbone phases have no phase-level `_trigger` (they are advanced INTO via a predecessor's `_advances_to`).                                                                                                                                                                                                                                                                                               |
| `_fragments`        | the ordered units of work the phase composes. Each is `{ _id, _trigger, _file }`. Load + follow a fragment's `_file` when its `_trigger` fires                                                                                                                                                                                                                                                                                                                                                                                                   |
| `_assemble`         | the single terminal unit (`{ _file }`) that combines the fragment outputs into the phase's artifact(s)                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| `_produces`         | the artifact file(s) the phase writes. Each entry is either a bare filename (unconditional) or an inline conditional map `{ file: <path>, _when: <prose> }` — an artifact produced ONLY when the design predicate holds (e.g. `terraform/eks.tf` only when EKS is in the design). Same `{ file, _when }` shape as `_knowledge`; `_when` is opaque prose the interpreter reads at runtime and CI does NOT evaluate. A trailing-slash `file` (e.g. `kubernetes/`) names a produced DIRECTORY when the unit emits a set of dynamically-named files. |
| `_advances_to`      | (backbone phases only) the phase that runs next on success — or a terminal (`complete`). A sidebar has NO `_advances_to`.                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `_gates`            | (sidebar phases only, optional) the backbone phase that must NOT start while this sidebar is UNRESOLVED (its `phases.<sidebar>` status is not `"completed"`). Declares in the contract what previously lived in prose (e.g. the what-if workshop holds Generate until it resolves). A declined sidebar is `"completed"` (resolved), so the gate lifts — this key never makes a sidebar mandatory. The target must be an existing backbone phase, never a terminal.                                                                               |
| `_exec`             | (optional) the phase's EXECUTION MODE. When present, the phase's WORK (fragments + assembler) is dispatched to a fresh isolated sub-agent window with file-only I/O, at the capability tier named by `_exec._agent`; the interpreter keeps the gates, `_init` setup, and the state transition in the MAIN window (see § `_exec`). Requires `_interactive: false`. Absent = the phase runs inline in the main window.                                                                                                                             |
| `_re_entry_guard`   | (backbone phases with a downstream only) the stale-downstream guard — STOP re-running this phase if its downstream phase already completed, unless the user confirms (see below). Terminal phases and sidebars have none.                                                                                                                                                                                                                                                                                                                        |
| `_preconditions`    | the entry gate — an ordered list of checks that MUST pass before the phase does any work (predecessor completed, single active phase, inputs present/valid). See § Gate protocol.                                                                                                                                                                                                                                                                                                                                                                |
| `_postconditions`   | the completion gate — an ordered list of checks that MUST pass before the phase is marked `completed` and control advances. See § Gate protocol.                                                                                                                                                                                                                                                                                                                                                                                                 |
| `_forbids_files`    | a glob list of files/dirs this phase MUST NOT create (scope boundary). See § Gate protocol.                                                                                                                                                                                                                                                                                                                                                                                                                                                      |

### `_knowledge` — conditional data loading

`_knowledge` declares a phase's (or assembler's) data dependencies: the
`knowledge/**.json` lookup tables it consults (sizing, mapping, pricing). Each
entry is `{ file, _when? }` — the same shape as `_produces` conditional artifacts.

- Load a knowledge file **only when its `_when` predicate holds** against the
  phase's inputs. Do NOT speculatively load knowledge for resource types absent
  from the inventory. A bare entry (no `_when`) is always loaded.
- `_when` is opaque prose the interpreter evaluates at runtime; CI validates only
  that each `file` resolves on disk (skill-root relative), never the predicate's
  truth (same policy as `_trigger._when`).

### `_trigger` forms

- `{ _always: true }` — the fragment always runs.
- `{ _glob: "<pattern>" }` — the fragment runs when one or more files matching the glob exist in the workspace; otherwise it is skipped.
- `{ _when: "<condition>" }` — the fragment runs when the prose condition holds (evaluated by you, the interpreter, against the phase's inputs); otherwise it is skipped. The condition is opaque prose — CI validates only that the form is well-formed, not the condition's truth. Used for fragments gated on a preference or a design-artifact shape (e.g. the EKS branches, gated on the Kubernetes preference / an `eks_cluster` design entry).

### `_re_entry_guard` — stale-downstream re-entry

A backbone phase whose downstream phase has already completed is unsafe to re-run
silently: its artifact feeds the downstream, so overwriting it leaves the
downstream artifact stale. `_re_entry_guard` encodes that check. It has four keys,
all required when the guard is present:

| Key                   | Meaning                                                                                                    |
| --------------------- | ---------------------------------------------------------------------------------------------------------- |
| `_stale_if_completed` | the downstream phase whose `"completed"` status makes re-running THIS phase unsafe (equals `_advances_to`) |
| `_stale_artifact`     | the downstream artifact named in the `GATE_FAIL` line (one of that downstream phase's `_produces`)         |
| `_on_reentry`         | what to do on re-entry — `stop_unless_confirmed` (the only value today)                                    |
| `_on_confirm`         | what to do when the user confirms the re-run — `reset_downstream_to_pending` (the only value today)        |

**Enforcement (at this phase's completion gate, BEFORE the phase's checks):**

1. Read `.phase-status.json`. If `phases.<_stale_if_completed>` is NOT
   `"completed"`, the guard does not fire — proceed normally.
2. If it IS `"completed"` **and** the user has not explicitly confirmed re-running
   this phase: **STOP**. Emit exactly:

   ```
   GATE_FAIL | phase=<this phase's _phase> | field=<_stale_artifact> | reason=stale_downstream
   ```

   Do NOT modify artifacts. Do NOT update `.phase-status.json`. Tell the user the
   downstream work may be stale and they must confirm the re-run.
3. If the user HAS explicitly confirmed the re-run (`_on_confirm:
   reset_downstream_to_pending`): before proceeding, set every phase downstream of
   this one (its `_advances_to` and everything after it on the backbone) back to
   `"pending"` in `.phase-status.json`. Then run the phase normally.

`phase=` and `reason=stale_downstream` are NOT stored in the frontmatter — you
reconstruct the `GATE_FAIL` line from this phase's `_phase` plus the constant
`stale_downstream` reason. This guard is the single source of truth for
stale-downstream re-entry; there is no separate per-phase prose or shared-file
table for it.

## `_exec` — execution mode (agent dispatch)

By default a phase runs INLINE: the interpreter loads its orchestrator and runs the
phase's fragments and assembler in the same (main) window. A phase MAY instead
declare `_exec` to run its WORK in a fresh, isolated sub-agent window. This is for a
phase whose work is heavy, self-contained, and non-interactive, and whose
intermediate DATA (e.g. raw Terraform/HCL, billing CSVs, large tool output) would
otherwise bloat the main context. Discovery is the canonical case: it parses bulky
source files down to one small inventory artifact.

```yaml
_interactive: false # REQUIRED to dispatch: the phase's work does not prompt the user
_exec:
  _agent: rw # capability tier: ro | rw | rwx | git
```

`_exec` may only be declared on a phase that also declares `_interactive: false`.
A dispatched worker has file-only I/O and cannot converse with the user, so only a
phase whose WORK (fragments + assembler) is non-interactive is a dispatch candidate.
The author affirms this explicitly — a phase with `_interactive: true` or no
`_interactive` declaration at all cannot carry `_exec` (CI rejects it). Interactive
phases (clarify, feedback) therefore run inline, always.

### What moves, and what STAYS in the main window

`_exec` dispatches the phase's WORK only. The interpreter keeps ownership of the
state machine. When a phase declares `_exec`, the interpreter:

1. **Runs the entry gate (`_preconditions`) in the MAIN window**, before dispatch.
   Dispatch only happens if the gate passes.
2. **Performs `_init` state setup in the MAIN window** if the phase carries `_init`
   (create `.migration/`, resolve resume-vs-fresh, write `.phase-status.json`). The
   agent never bootstraps state — it is handed an already-initialized
   `$MIGRATION_DIR`.
3. **Dispatches the fragments + assembler to one sub-agent** at the `_agent` tier.
   The agent reads the phase's `_input` from `$MIGRATION_DIR` (and the workspace),
   runs the fragments (each when its `_trigger` fires) then the assembler, and
   writes the phase's `_produces` artifact(s) to `$MIGRATION_DIR`. The agent's I/O
   is FILE-ONLY: it returns nothing but its written artifacts (plus a terse status).
   It does NOT converse with the user — every interactive gate stays in the main
   window (this is why only non-interactive phases are dispatch candidates).
4. **Runs the completion gate (`_postconditions`) in the MAIN window**, re-reading
   the artifact(s) from disk (never trusting the agent's summary), then emits
   `GATE_FAIL` or `HANDOFF_OK` and writes the state transition — exactly as for an
   inline phase. The agent MUST NOT emit `HANDOFF_OK` or touch `.phase-status.json`.

One controller owns the lifecycle; the agent is a pure artifact-producing worker.

### How to dispatch (the generic tiered worker)

The dispatched agent is GENERIC and phase-agnostic: one worker shell per capability
tier, whose only baked-in trait is its tool allow-list. The PHASE it runs is passed
in at dispatch time, so a single shell serves every phase at that tier. The plugin
ships these workers under `agents/`; the tier maps to the worker name:

| `_agent` | Worker to dispatch                             | Allow-list (the tier)               |
| -------- | ---------------------------------------------- | ----------------------------------- |
| `ro`     | `aws-startup-advisor:generic-phase-worker-ro`  | Read, Grep, Glob                    |
| `rw`     | `aws-startup-advisor:generic-phase-worker-rw`  | Read, Grep, Glob, Write, Edit       |
| `rwx`    | `aws-startup-advisor:generic-phase-worker-rwx` | Read, Grep, Glob, Write, Edit, Bash |
| `git`    | `aws-startup-advisor:generic-phase-worker-git` | rw + git                            |

(Only the workers a skill actually needs are shipped. A phase may only name a tier
whose worker file is present on disk — CI rejects an `_exec._agent` that names a tier
with no `agents/generic-phase-worker-<tier>.md`, since dispatching to an absent worker
would fail at runtime. `rw` deliberately excludes shell/Bash so it cannot reach `git`
— that keeps the `rw`/`git` distinction real. `rwx` is `rw` plus a SCOPED shell whose
sole purpose is running the read-only `tf-best-practices` policy checker in-fragment
(e.g. `python3 .../validate-terraform-policy.py`); it is still not a `git` tier — a host
that can scope commands SHOULD restrict its Bash to the checker (e.g. `Bash(python3:*)`),
and the `rwx` worker's prompt binds that scope where the host cannot enforce it.)

To dispatch, invoke the tier's worker via the host's Agent/subagent tool with a
context block that tells the generic worker WHICH phase to run and where. Build these
exact labeled lines (the worker parses them; omit an optional line when empty):

```
Skill: <the skill name, e.g. heroku-to-aws>
Skill root: <absolute path to the skill directory (where references/ and knowledge/ live)>
Phase: <the _phase id, e.g. discover>
Phase file: <path, relative to Skill root, of the phase orchestrator (references/phases/<phase>/<phase>.md)>
Migration dir: <the absolute $MIGRATION_DIR>
Input artifacts (Read these): <comma-joined paths of the phase's _input artifacts already on disk — omit if none>
```

Pass upstream artifacts as FILE PATHS, never inlined. The worker loads the phase
file, runs its fragments + assembler (skipping the `_init`/gate/handoff scaffolding,
which stay here), writes the `_produces` artifact(s) to `Migration dir`, and returns
one status line:

- `WORKER_DONE | phase=<phase> | artifacts=<paths>` — proceed to step 4 (re-read the
  artifacts from disk and run the completion gate here; do NOT trust this line as the
  handoff).
- `WORKER_BLOCKED | phase=<phase> | reason=<...>` — the work did not complete. Do NOT
  advance; run the completion gate anyway (it will fail on the missing/partial
  artifact and emit `GATE_FAIL`), and tell the user which phase to re-run.

**Fallback — no subagent tool (inline hosts).** If the host has no Agent/subagent
dispatch tool (e.g. inline-only platforms), do NOT fail: run the phase's fragments +
assembler INLINE in the main window instead, exactly as a non-`_exec` phase. The
`_exec` tier is inert here (nothing to enforce it) and the only cost is the heavier
main-window context `_exec` was meant to avoid. Behavior is identical; isolation is
not. (See the platform-asymmetry note below.)

### `_agent` — capability tiers

`_agent` names the capability tier the dispatched work runs at. The tiers are an
ordered, closed vocabulary (least → most privileged):

| Tier  | Capabilities                                                               | Use for                                                                  |
| ----- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `ro`  | read-only (Read / Grep / Glob / read-only Bash)                            | analysis-only phases that produce NO artifact                            |
| `rw`  | `ro` + Write / Edit (file creation in the run)                             | a phase that writes its `_produces` artifact(s)                          |
| `rwx` | `rw` + a scoped shell (run the tf-best-practices policy checker); no `git` | a producing phase that must run the Terraform policy checker in-fragment |
| `git` | `rw` + git operations (commit / branch / push)                             | a phase that mutates the user's repo history                             |

**Derive the minimum, then declare it.** A phase that `_produces` any artifact does
write work, so it needs at least `rw`; declaring `ro` on a producing phase is a
validator error (a phase can't produce a file it has no permission to write). The
author declares the tier and CI verifies it is not below the minimum derivable from
what the phase produces — the same declare-but-verify pattern as the rest of the
grammar. Pick the LEAST tier that covers the phase's real work.

### What CI enforces (structure only)

The validator checks the STRUCTURE of `_exec` (never the runtime tier — that is the
harness's job, see the platform-asymmetry note):

1. `_exec` sub-keys are in the closed set (`_agent`); unknown sub-keys are a typo error.
2. `_agent` is present and ∈ `{ro, rw, rwx, git}`.
3. **Derived-minimum:** a producing phase (`_produces` non-empty) cannot declare `ro`.
4. **Non-interactive affirmation:** the phase MUST declare `_interactive: false`. A
   phase with `_interactive: true` or no `_interactive` key cannot carry `_exec` —
   a dispatched, file-only worker cannot prompt the user.
5. **Worker-exists:** the tier's `agents/generic-phase-worker-<tier>.md` must be
   shipped on disk. A phase cannot dispatch to a tier whose worker the plugin does
   not ship (it would fail at runtime). (Skipped when the plugin `agents/` dir
   cannot be located — tolerant of a non-standard layout.)

### One level only

Dispatch is ONE level deep. A phase's fragments run INSIDE the dispatched agent;
they cannot themselves declare `_exec` and spawn a further sub-agent (most harnesses
forbid a sub-agent spawning a sub-agent). `_exec` is a PHASE-only key — a fragment
or assembler carrying it is a closed-vocabulary error.

### Platform asymmetry — the tier is a scoping HINT, not a guarantee

The capability tier is only _enforced_ where the host harness has a real sub-agent
allow-list (e.g. Claude Code's `tools:` frontmatter). On harnesses with no sub-agent
model (inline-only hosts), there is nothing to dispatch to: the phase runs in the
main session at full access and the tier is INERT — it fails **open**. Treat
`_exec._agent` as a least-privilege _intent_ the harness enforces when it can, NOT as
a security boundary you can rely on. Do not put a safety-critical permission
restriction behind a tier and assume it holds everywhere. (Same fail-open discipline
as `_when`: structure records the intent; enforcement is the harness's job.)

## Gate protocol

The LLM runs two gates around each phase, reading them from frontmatter. This is
heroku-to-aws's own gate contract — phases do NOT load any shared gate file.

### Check kinds (used in `_preconditions` and `_postconditions`)

Each entry is a single check plus an `_on_failure` action (see the `_on_error`
dictionary below). Closed vocabulary of check kinds:

| Check                        | Arg                       | Passes when                                                                                                  |
| ---------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `_check_phase_completed`     | a phase name              | `.phase-status.json` `phases.<name>` is `"completed"` or a skill-declared resolved status (§ Skill bindings) |
| `_check_single_active_phase` | `true`                    | at most one core phase is `in_progress`                                                                      |
| `_check_file_exists`         | filename or `[names]`     | each named file exists in `$MIGRATION_DIR/`                                                                  |
| `_validate_json`             | filename or `[names]`     | each named file parses as valid JSON                                                                         |
| `_assert`                    | an opaque prose predicate | you (the interpreter) evaluate the prose against the artifacts                                               |

`_assert` is the JUDGMENT escape hatch: arithmetic (e.g. the Property-16 total ==
sum invariant), enum-membership over an artifact's runtime content (e.g.
`recommendation.path ∈ {...}`), and conditionals (e.g. "if Postgres in inventory
→ `database_ha` set") are `_assert` prose, NOT structured checks — CI cannot open a
runtime artifact to verify them, so the interpreter evaluates them. CI validates
only that the `_assert` form is well-formed, never the predicate's truth (same
policy as `_when`).

### `_on_error` actions

Every `_on_failure:` names one of these. Each is an effect plus a phase-status
transition:

| Action              | Effect                                     | Phase status         |
| ------------------- | ------------------------------------------ | -------------------- |
| `_warn_and_skip`    | record a warning; skip this item; continue | remain `in_progress` |
| `_default_and_warn` | apply a documented default; warn; continue | remain `in_progress` |
| `_halt_and_inform`  | stop; surface a diagnostic to the user     | retain `in_progress` |
| `_unrecoverable`    | stop; surface an error                     | revert to `pending`  |

### `_preconditions` — the entry gate

Before the phase does ANY work, run each `_preconditions` check in order. On a
failure, apply that check's `_on_failure` action. A `_halt_and_inform` /
`_unrecoverable` failure STOPS the phase (it does not proceed to its fragments).
Only when all preconditions pass does the phase set itself `in_progress` and run.

### `_postconditions` — the completion gate

Before the phase is marked `"completed"` and control advances, **re-read the
relevant artifacts from disk** (do not trust chat memory), then run each
`_postconditions` check in order.

- **On any failure:** apply the `_on_failure` action and emit exactly:

  ```
  GATE_FAIL | phase=<this phase's _phase> | field=<the failing file/field> | reason=<missing|invalid>
  ```

  Do NOT modify artifacts to force a gate to pass. Do NOT update
  `.phase-status.json`. Do NOT advance. Tell the user which phase to re-run.

- **On all-pass:** emit exactly:

  ```
  HANDOFF_OK | phase=<this phase's _phase> | artifacts=<comma-separated files verified>
  ```

  then update `.phase-status.json` (set this phase `"completed"`, set
  `current_phase` to `_advances_to`, update the timestamp) in the same turn.

`phase=` is reconstructed from the phase's own `_phase` (not stored in each check).
The orchestrator (SKILL.md) MUST NOT load the next phase until it sees the
`HANDOFF_OK` line; a completion message without it is not a valid handoff.

### `_forbids_files` — scope boundary

A glob list of files/directories the phase MUST NOT create. After the phase runs,
if any path matching a `_forbids_files` glob was written, that is a scope
violation — treat it as a `_postconditions` failure. This encodes the per-phase
"do not emit README.md / *.txt / downstream artifacts" boundaries.

### Backbone vs sidebar phases

A **backbone** phase (the default) is a step on the linear lifecycle: it is
advanced into by its predecessor's `_advances_to`, and it advances to the next
phase (or the `complete` terminal). The backbone is the chain of backbone phases
wired by `_advances_to` (forward) and `_requires_phase` (backward), from the first
phase (no `_requires_phase`) to the one whose `_advances_to` is the terminal
`complete`. The interpreter derives this chain from the phase frontmatter; it is
not hardcoded. The head of the backbone (the phase with no `_requires_phase`) is
the skill's entry phase and carries `_init: true`; the skill names it in SKILL.md
so a cold start loads it directly rather than scanning to find it (see § The
interpreter loop, step 1).

A **sidebar** phase (`_kind: sidebar`, e.g. `feedback`) is OFF the backbone.
It is optional, entered only when its phase-level `_trigger` fires (e.g. the user
opts in), and it returns control to the flow rather than advancing `current_phase`
— so it has no `_advances_to`, and it never appears as a `current_phase` value.
WHERE a sidebar is offered is orchestration prose (see SKILL.md), not part of
the phase contract.
A sidebar MAY declare `_gates: <backbone-phase>`: while the sidebar is
UNRESOLVED (its `phases.<sidebar>` status is not `"completed"`), the interpreter
must not start the named phase. Resolution — including a decline — lifts the
gate (see the status semantics below: declined is still `"completed"`), so
`_gates` holds ordering, never participation. A sidebar without `_gates` blocks
nothing. This generalizes: a future "re-probe Discover" sidebar would use the
same construct anchored at a different point.

**Sidebar status semantics (important):** marking a sidebar's
`phases.<sidebar>` as `"completed"` means the sidebar was RESOLVED (offered
and dealt with) — NOT that the user participated. A declined sidebar is still
`"completed"` (the lifecycle is resolved, so the migration can terminate cleanly).
Whether the user actually participated is a SEPARATE signal, carried by the
presence of the sidebar's artifact (e.g. `feedback.json` exists only if the
user engaged). Do not conflate "sidebar resolved" with "user participated."

## Fragment unit keys

A phase has 1..N fragments and exactly one assembler. A fragment does one unit of
work and writes its own contribution; fragments are independent (none reads
another's output). The assembler runs last and combines/validates the fragments'
contributions into the phase's artifact(s).

Each fragment file (named by a phase's `_fragments[]._file`) carries its own frontmatter:

| Key            | Meaning                                                                                                                                                                                                                                                                                                                                                                                                                  |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `_fragment`    | the fragment's id — must match the `_id` the phase's `_fragments` list uses to reference it                                                                                                                                                                                                                                                                                                                              |
| `_of_phase`    | the phase this fragment belongs to                                                                                                                                                                                                                                                                                                                                                                                       |
| `_contributes` | the artifact section(s) this fragment writes into (fragments contribute to the phase's artifact; they do not each create a standalone file). Same entry forms as `_produces`: a bare filename, or a conditional `{ file: <path>, _when: <prose> }` when the fragment only emits that artifact under a design predicate (e.g. the EKS fragment contributes `terraform/eks.tf` / `kubernetes/` only when EKS is selected). |

## Assembler unit keys

The assembler file (named by a phase's `_assemble._file`) carries:

| Key          | Meaning                                                                                                                                                                                    |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `_assemble`  | the assembler's id                                                                                                                                                                         |
| `_of_phase`  | the phase this assembler belongs to                                                                                                                                                        |
| `_reads`     | the fragment contributions it combines                                                                                                                                                     |
| `_knowledge` | reference/data files it loads (same shape as a phase's `_knowledge`: `{ file, _when? }`); each `file` must resolve on disk                                                                 |
| `_produces`  | the artifact file(s) it creates — the assembler is the single creator of the phase's artifact. Same entry forms as a phase's `_produces` (bare filename or conditional `{ file, _when }`). |

## `_init: true` — establish migration state

When the phase being entered has `_init: true`, perform migration-state setup
BEFORE running any of its fragments. This replaces what was previously written
out as a per-phase "initialize" step. Exactly one phase per skill carries `_init:
true` — the backbone head / declared entry phase — so this setup runs once, on the
cold start that begins a migration.

(Paths below use the default run root `.migration/` — substitute the skill's
declared run root (§ Skill bindings). A skill that declares its own state shape
writes `.phase-status.json` per its SKILL.md's state-file section instead of the
shared schema in step 4. The run-identity keys in step 4 (`run_id`,
`owning_skill`, `initiated_by`) are seeded only under the literal default root
`.migration/`; a skill that declares its own run root, such as agent-advisor,
skips them and keeps its own state contract.)

1. Check for an existing `.migration/` directory at the project root.
   - **If existing runs are found:** list them with their phase status and ask:
     - `[A] Resume: Continue with [latest run]`
     - `[B] Fresh: Create new migration run`
     - `[C] Cancel`
   - **If resuming:** set `$MIGRATION_DIR` to the selected run's directory. Read
     its `.phase-status.json` and validate it per § The interpreter loop
     (State-file validation). If the `_init` phase is already `completed`, apply
     the re-entry rules (see the phase's `_re_entry_guard` frontmatter and
     § `_re_entry_guard` above) before proceeding.
   - **If fresh, or no existing runs:** continue to step 2.

2. Create `.migration/[MMDD-HHMM]/` (e.g. `.migration/0315-1030/`) using the
   current timestamp (MMDD = month/day, HHMM = hour/minute). Set `$MIGRATION_DIR`
   to this new directory.

3. Create `.migration/.gitignore` (if not already present) with exact content:

   ```
   # Auto-generated migration state (temporary, do not commit)
   *
   !.gitignore
   ```

   This prevents accidental commits of migration artifacts.

4. Write `.phase-status.json` per the schema
   `references/vendored/state/phase-status.schema.json`. Seed `phases` with ONE entry per
   phase the skill declares (its phase files), all `"pending"` EXCEPT this `_init`
   phase which is `"in_progress"`; set `migration_id` to `[MMDD-HHMM]`,
   `last_updated` to the current ISO 8601 timestamp, and `current_phase` to this
   `_init` phase. (The schema does not enumerate phase names — the valid names are
   the skill's declared phases.) Under the default run root only, also seed two
   run-identity keys, read by telemetry and by the plugin-to-web handoff:
   `run_id` — a fresh random UUID (run `uuidgen` or equivalent and write its output
   verbatim; never copy a value from an example or a previous run), and
   `owning_skill` — the running skill's
   directory name in upper case with hyphens replaced by underscores
   (`gcp-to-aws` → `GCP_TO_AWS`). A skill invoked by another skill still records
   its own id as `owning_skill`; `initiated_by` (the invoking skill's id) is
   optional and may be left unset.

5. Confirm both `.migration/.gitignore` and `.phase-status.json` exist before
   running the phase's fragments.
