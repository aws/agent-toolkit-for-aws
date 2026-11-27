#!/usr/bin/env python3
"""SessionEnd hook: send the session log to AWS Context with PutTrace.

Off unless "feedback" is "on" in ~/.aws-context/config.json. Always exits 0.

The log is sent as recorded, with nothing removed: the user turned this on after a data
notice that says so. Filtering it here would make that notice wrong.

The client can stop this hook as soon as it exits, so the hook only queues a job naming the
session's log, and a detached process sends it. The job holds no transcript text. Anything
unsent goes at a later session end.

PutTrace stores one session log record per document and converts a session's documents
together, so each JSONL line goes as its own document, oldest first, in batches of at most 100
lines and 4 MiB (a call takes 100 documents and 7 MiB after base64). `~/.aws-context/sessions/`
records how many lines of each session the service has accepted, and only a batch the service
accepted moves that count, so a resumed session sends only its new lines and a failed batch is
sent again, with the same clientToken, at a later session end.

The PutTrace `sessionId` is "content-agent-", Claude Code's session ID and a hash of the graph and readers, so
a session's lines sent after the user changes the readers start a new service session with
only the new readers.
"""

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hook_config  # noqa: E402

SPOOL = hook_config.CONFIG_DIR / "spool"
SESSIONS = hook_config.CONFIG_DIR / "sessions"
STATUS_FILE = hook_config.CONFIG_DIR / "feedback-status.json"
JOB_VERSION = 2
MAX_BATCH_DOCS = 100
MAX_BATCH_BYTES = 4 * 1024 * 1024
MAX_SESSION_BYTES = 16 * 1024 * 1024
MAX_SPOOLED = 100
MAX_SESSIONS = 500
DEADLINE_SECONDS = 25
DETACHED_DEADLINE_SECONDS = 120
SEND_TIMEOUT_SECONDS = 15
UPLOAD_BYTES_PER_SECOND = 256 * 1024
CONTEXT_TOOL_MARKER = "context___"
TRACE_FORMAT = "ANTHROPIC"
TRACE_SOURCE = "claude-code"
SENDER_ENV = "AWS_CONTEXT_TRACE_SENDER"
# Marks the plugin's sessions apart from other agents' traces, such as IRA's.
SESSION_ID_PREFIX = "content-agent-"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,900}\Z")
CREDENTIAL_ERRORS = ("ExpiredTokenException", "ExpiredToken", "InvalidSignatureException", "UnrecognizedClientException",
                     "InvalidClientTokenId", "IncompleteSignatureException")
# Outcomes that end the whole run: every further call would fail the same way.
STOP_ALL = ("trace-analysis-disabled", "credentials-rejected", "unreachable", "no-credentials")


def log_lines(text):
    """The log's lines. JSONL separates records with "\\n" only; str.splitlines would also split
    on characters such as U+2028 that JSON strings may hold unescaped."""
    return text.split("\n")


def used_context(transcript_text):
    """True when the agent called an AWS Context tool. Transcripts also name the tools in tool
    lists and search results, so only tool_use blocks count."""
    for line in log_lines(transcript_text):
        if CONTEXT_TOOL_MARKER not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        content = (entry.get("message") or {}).get("content") if isinstance(entry, dict) else None
        if isinstance(content, list) and any(isinstance(block, dict) and block.get("type") == "tool_use"
                                             and CONTEXT_TOOL_MARKER in str(block.get("name", "")) for block in content):
            return True
    return False


def log_records(text):
    """The session log's lines that are JSON objects, compact as written. Blank lines and a line
    still being written are skipped."""
    records = []
    for line in log_lines(text):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            records.append(line)
    return records


def settings_hash(cfg):
    key = json.dumps([cfg.get("graphArn"), cfg.get("readers")], sort_keys=True)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def session_key(event):
    """A stable name for the session: Claude Code's session ID, or a hash of the log's path."""
    value = event.get("session_id")
    if isinstance(value, str) and SESSION_ID_PATTERN.match(value):
        return value
    return "log-" + hashlib.sha256(str(event.get("transcript_path", "")).encode("utf-8")).hexdigest()[:32]


def service_session_id(key, cfg):
    return "%s%s-%s" % (SESSION_ID_PREFIX, key, settings_hash(cfg))


def first_unsent(records, accepted):
    """Where sending resumes: after the lines the service accepted, and no earlier than the
    newest MAX_SESSION_BYTES of what is left."""
    start, total = len(records), 0
    while start > accepted:
        size = len(records[start - 1].encode("utf-8"))
        if size <= MAX_BATCH_BYTES:
            if total + size > MAX_SESSION_BYTES:
                break
            total += size
        start -= 1
    return start


def next_batch(records, start):
    """The documents of the batch that starts at `start`, and the index after it. A line over
    MAX_BATCH_BYTES is left out."""
    documents, size, end = [], 0, start
    while end < len(records) and len(documents) < MAX_BATCH_DOCS:
        data = records[end].encode("utf-8")
        if len(data) > MAX_BATCH_BYTES:
            end += 1
            continue
        if documents and size + len(data) > MAX_BATCH_BYTES:
            break
        documents.append(data)
        size += len(data)
        end += 1
    return documents, end


def build_request(sid, start, documents, cfg):
    """The PutTrace request for one batch. Everything in it follows from the session, the batch's
    position and its documents, so a resend is the identical request under the same token."""
    return {
        "format": TRACE_FORMAT,
        "sessionId": sid,
        "traceDocuments": [base64.b64encode(doc).decode("ascii") for doc in documents],
        "agentContextArns": [cfg["graphArn"]],
        "accessControlConfig": {"accessControlList": cfg["readers"]},
        "traceMetadata": {"source": TRACE_SOURCE},
        "clientToken": hashlib.sha256(("%s:%d:" % (sid, start)).encode("utf-8")
                                      + b"\n".join(documents)).hexdigest()[:64],
    }


def remove(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def write_private(path, text):
    """Write a 0600 file atomically: a client that kills the hook mid-write leaves either the
    old file or none, never a truncated one."""
    tmp = path.with_name(".%s.%d.%s.tmp" % (path.name, os.getpid(), os.urandom(4).hex()))
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.replace(str(tmp), str(path))


def private_dir(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(str(path), 0o700)


def accepted_count(key):
    """How many of the session's log records the service has accepted."""
    try:
        return max(0, int(json.loads((SESSIONS / ("%s.json" % key)).read_text()).get("accepted", 0)))
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def save_accepted_count(key, count):
    private_dir(SESSIONS)
    write_private(SESSIONS / ("%s.json" % key), json.dumps({"accepted": count}))


def prune_sessions():
    try:
        files = sorted(SESSIONS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for old in files[MAX_SESSIONS:]:
        remove(old)


def record_status(cfg, state, detail=""):
    """Record the outcome of the latest sending run, for `/context-hooks status`: "sent" when
    every job went, or the first reason one did not."""
    write_private(STATUS_FILE, json.dumps({
        "state": state,
        "detail": detail[:500],
        "graphArn": cfg.get("graphArn"),
        "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "spooled": len(list(SPOOL.glob("*.json"))),
    }))


def remove_stale_temp_files(max_age_seconds=3600):
    """Remove temp files a killed writer left behind. Recent ones may still be in use."""
    now = time.time()
    for directory in (SPOOL, SESSIONS, hook_config.CONFIG_DIR):
        for tmp in directory.glob(".*.tmp"):
            try:
                if now - tmp.stat().st_mtime > max_age_seconds:
                    tmp.unlink()
            except OSError:
                pass


def read_job(path):
    try:
        job = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(job, dict) or job.get("v") != JOB_VERSION or not isinstance(job.get("key"), str) \
            or not isinstance(job.get("transcript"), str):
        return None  # unreadable, or queued by an older version of this hook
    return job


def matches_settings(job, cfg):
    """True when a job was queued under the graph and readers the user has chosen now."""
    return job.get("settings") == settings_hash(cfg)


def queue_job(event, cfg):
    """Queue the session for sending. Returns the job's path, or None when nothing is to send."""
    transcript = Path(event.get("transcript_path") or "")
    if not transcript.is_file():
        return None
    if not used_context(transcript.read_text(errors="replace")):
        return None
    key = session_key(event)
    path = SPOOL / ("%s.json" % key)
    write_private(path, json.dumps({"v": JOB_VERSION, "key": key, "transcript": str(transcript),
                                    "settings": settings_hash(cfg), "queued": time.time()}))
    return path


def classify(result):
    """The status a failed call records."""
    if result.trace_analysis_disabled:
        return "trace-analysis-disabled"
    if result.status in (401, 403):
        rejected_credentials = result.error_type in CREDENTIAL_ERRORS or any(
            word in result.message.lower() for word in ("expired", "signature", "security token"))
        return "credentials-rejected" if rejected_credentials else "access-denied"
    if result.rejected:
        return "rejected"
    return "unreachable"  # no answer, throttling, a server error or anything unexpected


def send_job(cfg, path, job, creds, deadline_at):
    """Send a job's unsent lines, a batch at a time. Returns (state, detail, documents sent);
    state is "sent" when the job is done and removed."""
    sent = 0
    try:
        text = Path(job["transcript"]).read_text(errors="replace")
    except OSError:
        remove(path)  # the log is gone; nothing left to send
        return "sent", "", 0
    records = log_records(text)
    key = job["key"]
    sid = service_session_id(key, cfg)
    accepted = accepted_count(key)
    if accepted > len(records):
        accepted = 0  # not the log that count was taken from
    start = first_unsent(records, accepted)
    rejected = None
    while start < len(records):
        documents, end = next_batch(records, start)
        if documents:
            remaining = deadline_at - time.monotonic()
            if remaining <= 0:
                return "unreachable", "stopped at the time limit; the rest goes at a later session end", sent
            payload = build_request(sid, start, documents, cfg)
            timeout = min(remaining, SEND_TIMEOUT_SECONDS + sum(len(d) for d in documents) / UPLOAD_BYTES_PER_SECOND)
            result = hook_config.call(cfg, hook_config.PUT_TRACE_PATH, payload, timeout, creds,
                                      agent=hook_config.user_agent("session-trace", key))
            if result.ok:
                sent += len(documents)
            else:
                state = classify(result)
                detail = "%s %s: %s" % (result.status, result.error_type, result.message)
                if state != "rejected":
                    return state, detail, sent  # kept; this batch goes again at a later session end
                # The service refused this batch as invalid, so sending it again cannot succeed:
                # its lines are left out and the rest of the session still goes.
                rejected = detail
                hook_config.debug("feedback: batch at line %d rejected: %s" % (start, detail[:200]))
        save_accepted_count(key, end)
        start = end
    remove(path)
    return ("rejected", rejected, sent) if rejected else ("sent", "", sent)


def send_spooled(cfg, deadline):
    deadline_at = time.monotonic() + deadline
    paths = sorted(SPOOL.glob("*.json"), key=lambda p: p.stat().st_mtime if p.exists() else 0)
    jobs = []
    for path in paths:
        job = read_job(path)
        if job is None or not matches_settings(job, cfg):
            remove(path)  # queued for a graph or readers the user has since changed
            continue
        jobs.append((path, job))
    for path, _ in jobs[:-MAX_SPOOLED] if len(jobs) > MAX_SPOOLED else []:
        remove(path)
    jobs = jobs[-MAX_SPOOLED:]
    if not jobs:
        return
    creds = hook_config.credentials(cfg.get("profile"), SEND_TIMEOUT_SECONDS)
    if not creds:
        record_status(cfg, "no-credentials", "the AWS CLI could not export credentials for profile %r" % cfg.get("profile"))
        return
    problem, sent, sessions = None, 0, 0
    for path, job in jobs:
        state, detail, count = send_job(cfg, path, job, creds, deadline_at)
        sent += count
        if state == "sent":
            sessions += 1
        elif problem is None:
            problem = (state, detail)
        if state in STOP_ALL:
            break
        # access-denied can be one session's (another identity started it), and rejected is
        # one batch's, so the other sessions still go.
    prune_sessions()
    if problem:
        record_status(cfg, problem[0], "%s (%d log lines sent this run)" % (problem[1], sent))
    else:
        record_status(cfg, "sent", "%d log lines from %d sessions, latest sessionId %s"
                      % (sent, sessions, service_session_id(jobs[-1][1]["key"], cfg)))


def main():
    cfg = hook_config.load()
    if cfg.get("feedback") != "on" or not hook_config.parse_arn(cfg.get("graphArn")) or not cfg.get("readers"):
        return
    private_dir(SPOOL)
    if os.environ.get(SENDER_ENV) == "1":
        # The detached sender: the hook has already queued this session.
        send_spooled(cfg, DETACHED_DEADLINE_SECONDS)
        return
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    if not isinstance(event, dict):
        return
    remove_stale_temp_files()
    queue_job(event, cfg)
    if not list(SPOOL.glob("*.json")):
        return
    # The client can stop this hook as soon as it exits, so a detached process does the sending.
    # A resend of a batch is harmless: its clientToken makes PutTrace idempotent.
    try:
        subprocess.Popen([sys.executable, str(Path(__file__).resolve())], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                         env=dict(os.environ, **{SENDER_ENV: "1"}))
        return
    except OSError:
        pass  # send from this process instead
    send_spooled(cfg, DEADLINE_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001  fail open
        pass
    sys.exit(0)
