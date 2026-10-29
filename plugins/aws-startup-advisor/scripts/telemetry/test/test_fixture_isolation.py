"""Verify the environment actually received by subprocess-based tests."""

import pytest
from conftest import ENDPOINT_ENV, TEST_ENDPOINT, run


@pytest.mark.parametrize("override", [None, "http://127.0.0.1:12345/collector"])
def test_child_endpoint_is_isolated_and_explicit_override_wins(
    home, tmp_path, monkeypatch, override
):
    # Even a developer shell pointed at production must not affect a test child.
    monkeypatch.setenv(ENDPOINT_ENV, "https://production.example/telemetry")
    probe = tmp_path / "endpoint_probe.py"
    probe.write_text("import os\nprint(os.environ[%r])\n" % ENDPOINT_ENV)
    proc = run(
        str(probe), home=home,
        env={ENDPOINT_ENV: override} if override else None,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == (override or TEST_ENDPOINT)
