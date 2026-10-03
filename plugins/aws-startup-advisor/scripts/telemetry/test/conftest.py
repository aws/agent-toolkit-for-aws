"""Shared test setup: importable modules, an isolated HOME, a local collector.

Run from anywhere with:  uv run --with pytest python -m pytest -q
"""

import http.server
import subprocess  # nosec B404 — test-only, inputs are hardcoded literals
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

TELEMETRY = Path(__file__).resolve().parents[1]
CONSENT = TELEMETRY / "consent"
EMISSION = TELEMETRY / "metric_emission"
PLUGIN_ROOT = TELEMETRY.parent.parent

# The same two directories the scripts put on their own path, so a test imports a
# module by the name its callers use.
sys.path[:0] = [str(CONSENT), str(EMISSION)]


def run(script, *args, home, env=None):
    """Run one of the scripts, by path relative to scripts/telemetry/.

    HOME points at a temp dir and the environment is built from scratch rather
    than inherited, so nothing in the developer's shell can change what these
    tests assert.
    """
    full_env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "USERPROFILE": str(home),  # Path.home() on Windows
    }
    full_env.update(env or {})
    return subprocess.run(  # nosec B603 — fixed argv, no shell
        [sys.executable, str(TELEMETRY / script), *args],
        capture_output=True,
        text=True,
        env=full_env,
    )


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty HOME, so no test can read or clobber a real consent record."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # Path.home() on Windows
    return tmp_path


@pytest.fixture
def collector():
    """A local HTTP server standing in for the telemetry endpoint.

    A real socket rather than a patched `urlopen`, because the scripts under test
    run in subprocesses and the thing worth proving is that the bytes leaving the
    process are the bytes the service's model accepts.
    """
    received = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802  (http.server's required spelling)
            length = int(self.headers.get("Content-Length", 0))
            received.append(
                {
                    "path": self.path,
                    "content_type": self.headers.get("Content-Type"),
                    "body": self.rfile.read(length),
                }
            )
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass  # keep pytest output clean

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(
            url="http://127.0.0.1:%d/v1/plugin-telemetry-event" % server.server_port,
            received=received,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
