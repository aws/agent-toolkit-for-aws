#!/usr/bin/env python3
"""Hook: report a migration run's progress as MigrationActivity telemetry.

    python3 scripts/telemetry/metric_emission/migration.py                 # PostToolUse (Write|Edit|Bash)
    python3 scripts/telemetry/metric_emission/migration.py --reconcile     # Stop
    python3 scripts/telemetry/metric_emission/migration.py --session-end   # SessionEnd

Nothing is inferred from the conversation and no skill instruction has to be
followed. The migration skills maintain `.migration/<id>/.phase-status.json` (and
`.gate-failures.json`) for their own gate enforcement; this script reads those
files, diffs them against a snapshot it keeps beside them, and POSTs one event per
transition found: RUN_STARTED, PHASE_COMPLETED, GATE_FAILED, RUN_COMPLETED. The
diff is idempotent and the run is locked while it runs, so overlapping hooks
cannot report the same transition twice. RUN_COMPLETED is sent once per runMode:
a run that ends decision-only and is later executed ends again, under
DECIDE_AND_EXECUTE, so consumers read a run's runMode from its latest
RUN_COMPLETED and count completed runs by distinct runId. The same ending is
never repeated, even after a confirmed re-entry; a held ending the run has
since outgrown is superseded by the new one rather than re-sent.

Consent is `record.is_accepted()`, the plugin's single gate; the install id comes
from the same record. Attribution is read from disk: a run names its owner in
`owning_skill`, and a run without one, or with one outside the migration set,
emits nothing.

Fail-open: every path exits 0 and swallows every error. A refusal the service may
later withdraw (403 while the launch gate is closed, 429, 5xx), or no connection
at all, leaves that event unrecorded so only it is re-sent; anything the service
took, or refused for good (400), is never repeated.
"""

import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_TELEMETRY = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(_TELEMETRY / "consent"), str(_TELEMETRY / "metric_emission")]

import client  # noqa: E402  (paths set above so these resolve in-plugin)
import migration_attributes as attrs  # noqa: E402
import record  # noqa: E402

MIGRATION_SKILLS = frozenset({"AZURE_TO_AWS", "GCP_TO_AWS", "HEROKU_TO_AWS", "LLM_TO_BEDROCK"})

# A hook killed by the host mid-run leaves its lock behind; anything older than
# this is treated as abandoned.
LOCK_STALE_SECONDS = 60.0
POST_TIMEOUT_SECONDS = 3.0
# Claude Code gives all SessionEnd hooks one shared budget, 1.5 s by default. A
# longer per-hook timeout can raise it, but a hook killed at the budget would leave
# accepted events unrecorded, so the sweep budgets itself to the default instead;
# the reserve leaves room for the snapshot write.
SESSION_END_BUDGET_SECONDS = 1.5
SESSION_END_RESERVE_SECONDS = 0.4
STDIN_TIMEOUT_SECONDS = 2.0

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

STATUS_FILE = ".phase-status.json"
GATE_FILE = ".gate-failures.json"
SNAPSHOT_FILE = ".telemetry-snapshot.json"
LOCK_DIR = ".telemetry-lock"

SNAPSHOT_UNREADABLE = object()


# ---------------------------------------------------------------- utilities


def as_uuid(value):
    """A lower-case UUID string, or None: the data lake accepts only lower case,
    while macOS uuidgen (what the skills run) mints upper case."""
    if isinstance(value, str) and UUID_RE.match(value):
        return value.lower()
    return None


def read_snapshot(path):
    """None when absent, SNAPSHOT_UNREADABLE when present but not JSON. A missing
    snapshot means a new run; a corrupt one must not, or the run would be
    re-reported from RUN_STARTED. The caller rebuilds it from the current state
    without sending, so the run reports again from its next transition."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return SNAPSHOT_UNREADABLE
    return data if isinstance(data, dict) else SNAPSHOT_UNREADABLE


def write_json(path, value):
    """Temp file plus rename, so a hook killed at the host's timeout cannot leave
    a half-written file where read_snapshot would find it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("%s.%d.tmp" % (path.name, os.getpid()))
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def read_hook_payload(stream=None, timeout=STDIN_TIMEOUT_SECONDS):
    """The hook's stdin parsed as a dict, or {}. Read on a daemon thread so a host
    that holds the pipe open cannot stall the turn."""
    stream = sys.stdin if stream is None else stream
    box = {}

    def read():
        try:
            box["raw"] = stream.read()
        except Exception:
            pass

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout)
    try:
        payload = json.loads(box.get("raw") or "")
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def via_mode(argv):
    """`--via cli` marks an invocation made from a skill instruction instead of a hook."""
    try:
        return "cli" if argv[argv.index("--via") + 1] == "cli" else "hook"
    except (ValueError, IndexError):
        return "hook"


# ------------------------------------------------------------ run discovery


def find_run_dirs(start_dir):
    """Run directories (.migration/<id>/ with a state file) for the nearest
    .migration tree, walking up a bounded number of levels so runs from parent or
    sibling projects are not mixed in."""
    runs = []
    directory = Path(start_dir or os.getcwd()).resolve()
    for _ in range(4):
        root = directory / ".migration"
        try:
            entries = list(os.scandir(root))
        except OSError:
            parent = directory.parent
            if parent == directory:
                break
            directory = parent
            continue
        for entry in entries:
            if entry.is_dir() and (Path(entry.path) / STATUS_FILE).exists():
                runs.append(Path(entry.path))
        break
    return runs


# ------------------------------------------------------------------ the lock


def acquire_lock(run_dir):
    """An exclusive per-run lock (directory creation as atomic test-and-set).
    Overlapping hooks would otherwise read the same "before" state and report the
    same transitions twice; this is the one duplication defence no downstream
    layer can substitute for."""
    lock = Path(run_dir) / LOCK_DIR
    try:
        lock.mkdir()
        return lock
    except FileExistsError:
        try:
            if time.time() - lock.stat().st_mtime > LOCK_STALE_SECONDS:
                shutil.rmtree(lock, ignore_errors=True)
                lock.mkdir()
                return lock
        except OSError:
            pass
        return None  # the holder is about to report the same transitions
    except OSError:
        return None  # unwritable run directory: emit nothing


def release_lock(lock):
    shutil.rmtree(lock, ignore_errors=True)


# ------------------------------------------------------------------- the diff


def gate_failure_entries(gate_failures):
    """The skill records each failed gate in .gate-failures.json, keyed by phase
    (see INTERPRETER.md, "Recording a failed gate"). Only phases the model knows
    are reportable; a null, scalar or array entry is not a failure."""
    if not isinstance(gate_failures, dict):
        return []
    entries = []
    for name, entry in gate_failures.items():
        if not isinstance(entry, dict):
            continue
        phase = str(name).upper()
        if phase in attrs.PHASES:
            entries.append((phase, entry))
    return entries


BACKBONE = ("discover", "clarify", "design", "estimate", "generate")


def run_ended(status):
    """(ended, runMode). The skills flip `run_mode` to decide_and_execute before
    Generate runs and may leave `current_phase: complete` from the decision-only
    finish in place, so an executed ending counts only once Generate is done.

    `current_phase` is optional in the shared state schema and authoritative when
    present. Without it the owning skill evaluates the backbone in order and is
    complete only when every backbone phase, Generate included, is completed;
    Generate stays opt-in, so a decision-only run that omits the field has not
    ended. Sidebars (workshop, feedback) never decide completion."""
    run_mode = attrs.map_enum(attrs.RUN_MODE, status.get("run_mode"))
    phases = status.get("phases") or {}
    generate = str(phases.get("generate", "")).lower()
    executing = run_mode == "DECIDE_AND_EXECUTE" and generate != "completed"
    current = status.get("current_phase")
    if current is None:
        ended = all(str(phases.get(name, "")).lower() == "completed" for name in BACKBONE)
    else:
        ended = current == "complete"
    return ended and not executing, run_mode


def reported_run_modes(snapshot):
    """Every runMode this run has already been reported ending under. Older
    snapshots kept only the last one under completedRunMode."""
    snapshot = snapshot or {}
    modes = snapshot.get("completedRunModes")
    if isinstance(modes, list):
        return [m for m in modes if isinstance(m, str)]
    last = snapshot.get("completedRunMode")
    return [last] if isinstance(last, str) else []


def diff_events(status, snapshot, gate_failures):
    """One event per transition between the snapshot and the state file, plus one
    GATE_FAILED per phase newly present in the gate record (a repeat failure of
    the same phase is not a new event; its later success is). A run ends once
    per runMode: a decision-only finish the user later turns into an executed
    one is reported again, under DECIDE_AND_EXECUTE, and each mode at most once."""
    events = []
    if snapshot is None or snapshot.get("started") is False:
        events.append({"eventName": "RUN_STARTED"})
    reported = set((snapshot or {}).get("gateFailures") or [])
    for phase, entry in gate_failure_entries(gate_failures):
        if phase in reported:
            continue
        event = {"eventName": "GATE_FAILED", "phase": phase, "status": "FAILED"}
        reason = attrs.map_enum(attrs.FAILURE_REASON, entry.get("reason"))
        if reason:
            event["failureReason"] = reason
        events.append(event)
    before = (snapshot or {}).get("phases") or {}
    for name, state in (status.get("phases") or {}).items():
        if before.get(name) == state:
            continue
        mapped = attrs.RESOLVED_STATUS.get(str(state).lower())
        phase = str(name).upper()
        if not mapped or phase not in attrs.PHASES:
            continue
        events.append({"eventName": "PHASE_COMPLETED", "phase": phase, "status": mapped, "key": name})
    ended, run_mode = run_ended(status)
    reported_modes = reported_run_modes(snapshot)
    # A workshop re-entry clears run_mode and reopens the decision gate while the
    # run stays completed; a mode already reported is never reported again.
    ended_again = bool(run_mode and reported_modes and run_mode not in reported_modes)
    if ended and (not (snapshot or {}).get("completed") or ended_again):
        event = {"eventName": "RUN_COMPLETED", "status": "SUCCESS"}
        if run_mode:
            event["runMode"] = run_mode
        events.append(event)
    return events


def build_activity(event, ctx):
    """The `migrationActivity` union member for `event`."""
    activity = {"eventName": event["eventName"], "skill": ctx["skill"]}
    if ctx.get("initiatingSkill"):
        activity["initiatingSkill"] = ctx["initiatingSkill"]
    activity["runId"] = ctx["runId"]
    if ctx.get("sessionId"):
        activity["sessionId"] = ctx["sessionId"]
    if event.get("phase"):
        activity["phase"] = event["phase"]
    if event.get("status"):
        activity["status"] = event["status"]
    try:
        attributes = attrs.derive_attributes(ctx["runDir"], ctx["skill"], event, ctx["status"])
    except Exception:
        attributes = None  # an artifact of an unexpected shape costs its attributes, never the event
    if attributes:
        activity["attributes"] = attributes
    return {"migrationActivity": activity}


def is_held(status):
    """Outcomes that mean the service did not take the event but may later: no
    connection at all (offline, DNS), 403 (a closed launch gate, or a WAF rate
    limit), 429 and 5xx. Anything else is the loss the design tolerates rather
    than risk a duplicate: a 400 the event would earn again, and a timeout or a
    dropped connection (None), after which the service may have taken it."""
    return status == client.UNREACHABLE or status in (403, 429) or (status is not None and status >= 500)


# ------------------------------------------------------------------ per run


def process_run(run_dir, session_id, session_end, url, deadline, edited_path, via):
    if time.time() >= deadline:
        return  # out of budget: untouched, so the next trigger reports it
    run_dir = Path(run_dir)

    def read_state():
        status = attrs.read_json(run_dir / STATUS_FILE)
        if not isinstance(status, dict) or not status.get("migration_id"):
            return None, None
        return status, attrs.read_json(run_dir / GATE_FILE)

    status, gate_failures = read_state()
    if status is None:
        return

    # Attribution is read from disk, never from an argument: a run that declares
    # no owner, or an owner outside the migration set, emits nothing (fail
    # closed) rather than emitting under the wrong skill.
    skill = status.get("owning_skill")
    if skill not in MIGRATION_SKILLS:
        return

    # Consent is the plugin's one gate; without it nothing is read into a
    # snapshot either, so a user who never agreed, or opted out, leaves no trace.
    state = record.read_state()
    if not state or state.get("consentStatus") != record.ACCEPTED:
        return
    install_id = as_uuid(state.get("installId"))
    if not install_id:
        return

    snapshot_file = run_dir / SNAPSHOT_FILE
    lock = acquire_lock(run_dir)
    if lock is None:
        return
    try:
        # Read again under the lock. Hooks run concurrently: one that read the
        # state before another reported a newer transition, and took the lock
        # only after that report, would otherwise diff against stale state and
        # move the snapshot backwards, and the next reconcile would re-send the
        # newer transition.
        status, gate_failures = read_state()
        if status is None or status.get("owning_skill") != skill:
            return
        snapshot = read_snapshot(snapshot_file)
        rebuild = snapshot is SNAPSHOT_UNREADABLE
        if rebuild:
            snapshot = None  # re-observed below, without sending
        valid_session_id = as_uuid(session_id)

        # Teardown sweeps only the session that wrote the snapshot; a run last
        # touched by another session is that session's to report.
        owner_before = (snapshot or {}).get("sessionId")
        if session_end and owner_before and valid_session_id and owner_before != valid_session_id:
            return

        # Identifiers read back from customer-editable files are validated, not
        # trusted: the service rejects the whole event on one malformed UUID. A
        # run directory is one lifecycle, so the id the snapshot already reports
        # under stays authoritative: a state file rebuilt after corruption
        # carries a fresh run_id, which must not split the run.
        run_id = as_uuid((snapshot or {}).get("runId")) or as_uuid(status.get("run_id")) or str(uuid.uuid4())

        def in_run(path):
            if not path:
                return False
            try:
                Path(path).resolve().relative_to(run_dir.resolve())  # is_relative_to needs 3.9
                return True
            except (OSError, ValueError):
                return False

        modes_before = reported_run_modes(snapshot)

        def write_snapshot(phases, completed, gates, started, owner, completed_modes):
            value = {"runId": run_id}
            if owner:
                value["sessionId"] = owner
            if started is False:
                value["started"] = False
            value.update({"phases": phases, "gateFailures": gates, "completed": completed, "via": via,
                          "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
            if completed_modes:
                value["completedRunModes"] = completed_modes  # every runMode the run has been reported ending under
            write_json(snapshot_file, value)

        def observe(phases, completed, gates, completed_modes):
            """Record the state last observed, whether or not anything was sent.
            Ownership moves to this session only when it changed the run or
            edited a file inside it; a hook that merely scanned past leaves the
            owner alone. Written only when something changed."""
            changed = (
                snapshot is None
                or (snapshot.get("phases") or {}) != phases
                or bool(snapshot.get("completed")) != completed
                or modes_before != completed_modes
                or (snapshot.get("gateFailures") or []) != gates
            )
            touched = changed or in_run(edited_path)
            owner = (valid_session_id or owner_before) if touched else (owner_before or valid_session_id)
            if not changed and snapshot.get("sessionId") == owner:
                return
            write_snapshot(phases, completed, gates, (snapshot or {}).get("started"), owner, completed_modes)

        if rebuild:
            # A corrupt snapshot (not this script's: its write is atomic) cannot
            # say what was reported. Those transitions are lost; recording the
            # current state lets the run report again from the next one.
            ended, run_mode = run_ended(status)
            observe(status.get("phases") or {}, ended, [phase for phase, _ in gate_failure_entries(gate_failures)],
                    [run_mode] if ended and run_mode else [])
            return

        events = diff_events(status, snapshot, gate_failures)
        known_gates = list(dict.fromkeys((snapshot or {}).get("gateFailures") or []))
        if not events:
            # Nothing to send, but the observation may have changed: a phase reset
            # (a confirmed re-entry sets downstream phases back to pending) or a
            # run taken over by this session. Record it, or the phase's next
            # completion would read as already reported and this session's
            # teardown would skip the run.
            observe(status.get("phases") or {}, bool((snapshot or {}).get("completed")), known_gates, modes_before)
            return

        ctx = {
            "runDir": run_dir,
            "status": status,
            "skill": skill,
            # Only a known migration skill may be named as the invoker; anything
            # else is dropped rather than risk rejecting the whole event.
            "initiatingSkill": status.get("initiated_by") if status.get("initiated_by") in MIGRATION_SKILLS else None,
            "runId": run_id,
            "sessionId": valid_session_id,
        }

        # Concurrently, under one budget: sent serially, a reconcile catching a
        # whole run could outlive the host's hook timeout and never reach the
        # snapshot write, so the next trigger would repeat the batch.
        activities = [build_activity(event, ctx) for event in events]
        timeout = max(0.05, min(POST_TIMEOUT_SECONDS, deadline - time.time()))
        with ThreadPoolExecutor(max_workers=max(1, len(events))) as pool:
            results = list(pool.map(
                lambda activity: client.post_event_status(activity, install_id, url, timeout=timeout),
                activities,
            ))
        held = [event for event, result in zip(events, results) if is_held(result)]
        if len(held) == len(events):
            return  # nothing taken: nothing recorded

        # The snapshot records exactly what the service took. A held phase keeps
        # its previous state so only that transition is re-sent; a held
        # RUN_STARTED, GATE_FAILED or RUN_COMPLETED is re-sent alone. Accepted
        # events are never repeated, even when a later trigger replays the held ones.
        phases = dict(status.get("phases") or {})
        before = (snapshot or {}).get("phases") or {}
        for event in held:
            if event["eventName"] != "PHASE_COMPLETED":
                continue
            if event["key"] in before:
                phases[event["key"]] = before[event["key"]]
            else:
                phases.pop(event["key"], None)
        run_started = next((e for e in events if e["eventName"] == "RUN_STARTED"), None)
        run_completed = next((e for e in events if e["eventName"] == "RUN_COMPLETED"), None)
        sent_gates = [e["phase"] for e in events if e["eventName"] == "GATE_FAILED" and e not in held]
        ended_now = bool(run_completed and run_completed not in held)
        modes = list(modes_before)
        if ended_now and run_completed.get("runMode") and run_completed["runMode"] not in modes:
            modes.append(run_completed["runMode"])
        write_snapshot(
            phases,
            bool((snapshot or {}).get("completed")) or ended_now,
            list(dict.fromkeys(known_gates + sent_gates)),
            not (run_started and run_started in held),
            valid_session_id or owner_before,
            modes,
        )
    finally:
        release_lock(lock)


# ---------------------------------------------------------------------- main


def reconcile(start_dir, session_id=None, session_end=False, edited_path=None, url=None, via="hook"):
    """Report every run reachable from `start_dir`. Returns nothing; never raises."""
    url = url or client.endpoint()
    deadline = time.time() + SESSION_END_BUDGET_SECONDS - SESSION_END_RESERVE_SECONDS if session_end else float("inf")
    for run_dir in find_run_dirs(start_dir):
        try:
            process_run(run_dir, session_id, session_end, url, deadline, edited_path, via)
        except BaseException:
            continue  # one run's trouble must not silence the others


def main(argv, stdin=None):
    session_end = "--session-end" in argv
    payload = read_hook_payload(stdin)
    # Claude Code sends session_id on every hook; Cursor sends conversation_id.
    session_id = payload.get("session_id") or payload.get("conversation_id")
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    edited_path = tool_input.get("file_path") or payload.get("file_path")
    if not isinstance(edited_path, str):
        edited_path = None

    # Post-write fast path: an edit outside any .migration tree is no work at all.
    # A Bash payload carries a command, not a file path, and the agent does write
    # state files through the shell (a heredoc instead of the Write tool), so it
    # falls through to a reconcile of every run under the hook's cwd: a few file
    # reads, and nothing is sent unless a transition is new.
    if not session_end and "--reconcile" not in argv and edited_path and ".migration" not in edited_path:
        return 0

    # Start discovery at the directory that owns the .migration tree, so an edit
    # deep inside a run's artifacts still resolves to its run.
    marker = edited_path.find("%s.migration%s" % (os.sep, os.sep)) if edited_path else -1
    roots = payload.get("workspace_roots")
    start_dir = (
        edited_path[:marker] if marker != -1 else None
    ) or payload.get("cwd") or (roots[0] if isinstance(roots, list) and roots else None) or os.getcwd()

    reconcile(start_dir, session_id=session_id, session_end=session_end, edited_path=edited_path, via=via_mode(argv))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except BaseException:
        sys.exit(0)  # telemetry must never make the user's work look like it failed
