"""Tests for the shell blocks in skills/claude-apps-to-bedrock/references/aws-setup.md.

The Identity Center preflight runs against a stubbed `aws` on PATH, so no AWS
account is needed. It must stop when ClaudeBedrockInference already exists,
wherever it appears in the list (a `| grep -q` pipe under pipefail skipped
the check unless the match came last).
"""
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

DOC = (pathlib.Path(__file__).resolve().parent.parent
       / "skills" / "claude-apps-to-bedrock" / "references" / "aws-setup.md")

STUB = """#!/bin/bash
case "$*" in
  *"sts get-caller-identity"*) echo "123456789012 arn:aws:iam::123456789012:user/t";;
  *"sso-admin list-instances"*) printf 'arn:aws:sso:::instance/ssoins-1\\td-1\\n';;
  *"identitystore get-group-id"*) echo "g-1";;
  *"sso-admin list-permission-sets"*) echo "$PS_ARNS";;
  *"sso-admin describe-permission-set"*)
    arn=$(sed -n 's/.*--permission-set-arn \\([^ ]*\\).*/\\1/p' <<<"$*")
    echo "${arn##*/}";;
  *) echo "unexpected: $*" >&2; exit 2;;
esac
"""


def preflight_block():
    text = DOC.read_text(encoding="utf-8")
    m = re.search(r"Preflight \(read-only\):\s*```bash\n(.*?)```", text, re.S)
    assert m, "preflight block not found"
    return (m.group(1)
            .replace("<identity-center-region>", "us-east-1")
            .replace("<bedrock-account-id>", "123456789012")
            .replace("<group display name>", "Engineers"))


@unittest.skipUnless(shutil.which("bash"), "needs bash")
class PreflightTest(unittest.TestCase):
    def run_preflight(self, names):
        with tempfile.TemporaryDirectory() as d:
            stub = pathlib.Path(d) / "aws"
            stub.write_text(STUB)
            stub.chmod(0o755)
            env = dict(os.environ, PATH=f"{d}{os.pathsep}{os.environ['PATH']}",
                       PS_ARNS=" ".join(f"arn:aws:sso:::permissionSet/ssoins-1/{n}" for n in names))
            return subprocess.run(["bash", "-c", preflight_block()], env=env,
                                  capture_output=True, text=True)

    def test_stops_when_existing_set_is_first(self):
        r = self.run_preflight(["ClaudeBedrockInference", "AdminAccess", "ReadOnly"])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("already exists", r.stdout)

    def test_stops_when_existing_set_is_last(self):
        r = self.run_preflight(["AdminAccess", "ClaudeBedrockInference"])
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)

    def test_continues_when_absent(self):
        r = self.run_preflight(["AdminAccess", "ReadOnly"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Target account: 123456789012", r.stdout)


if __name__ == "__main__":
    unittest.main()
