"""The optional account helper must not affect the anonymous runtime."""

import json
import subprocess
import sys

from conftest import TELEMETRY


def isolated_python(code, home):
    return subprocess.run(
        [sys.executable, "-S", "-c", code],
        capture_output=True,
        text=True,
        env={
            "HOME": str(home),
            "USERPROFILE": str(home),
            "PATH": "/usr/bin:/bin",
        },
        check=False,
    )


def test_import_never_loads_sdk_or_reads_credentials(home):
    code = """
import builtins
import sys
sys.path.insert(0, %r)
original = builtins.__import__
def forbidden(name, *args, **kwargs):
    if name.startswith(("botocore", "rfc8785")):
        raise AssertionError("optional SDK imported")
    return original(name, *args, **kwargs)
builtins.__import__ = forbidden
import auth
reporter = auth.AwsAccountReporter("startup-advisor:test:report:v1")
assert reporter._session is None
assert reporter._sdk is None
print("OK")
""" % str(TELEMETRY)
    result = isolated_python(code, home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"
    assert not list(home.iterdir())


def test_cli_without_optional_sdk_returns_only_bounded_status(home):
    script = TELEMETRY / "auth/identity.py"
    code = """
import runpy
import sys
sys.path.insert(0, %r)
sys.argv = [%r]
runpy.run_path(%r, run_name="__main__")
""" % (str(script.parent), str(script), str(script))
    result = isolated_python(code, home)
    assert result.returncode == 1
    assert not result.stderr
    output = json.loads(result.stdout)
    assert output["status"] == "ERROR"
    assert output["reasonCode"] in {"SDK_UNAVAILABLE", "PYTHON_VERSION_UNSUPPORTED"}
    assert set(output) == {"status", "reasonCode"}
    assert not list(home.iterdir())


def test_sdk_files_only_ship_with_migration_skills():
    import importlib.util

    path = TELEMETRY / "sync_bundles.py"
    spec = importlib.util.spec_from_file_location("account_bundle_manifest", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in module.MIGRATION_SKILLS:
        assert "auth/aws_account.py" in module.BUNDLES[name]
        assert "auth/pyproject.toml" in module.BUNDLES[name]
    assert not any(name.startswith("auth/") for name in module.OPERATE_FILES)


def test_legacy_payload_building_does_not_load_auth_or_add_identity(home):
    code = """
import builtins
import sys
sys.path.insert(0, %r)
original = builtins.__import__
def forbidden(name, *args, **kwargs):
    if name == "auth" or name.startswith(("botocore", "rfc8785")):
        raise AssertionError("legacy client loaded account reporting")
    return original(name, *args, **kwargs)
builtins.__import__ = forbidden
import client
payload = client.build_payload({"test": {}}, "00000000-0000-4000-8000-000000000001")
assert payload
assert not {"identity", "expectedAwsAccountId", "awsIdentityProof"} & payload.keys()
print("OK")
""" % str(TELEMETRY / "metric_emission")
    result = isolated_python(code, home)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "OK"
