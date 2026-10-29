"""Verify payment resource discovery from a v1 project status."""
import importlib.util
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

script = Path(__file__).with_name("setup_payment_user.py")
spec = importlib.util.spec_from_file_location("setup_payment_user", script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

status = {
    "resources": [{
        "resourceType": "payment-manager",
        "arn": "arn:aws:bedrock-agentcore:us-east-1:111111111111:payment-manager/test",
        "children": [{"resourceType": "payment-connector", "id": "connector-test"}],
    }],
}

with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    (root / "agentcore").mkdir()
    (root / "agentcore" / "agentcore.json").write_text('{"version":2}')
    original_dir = Path.cwd()
    try:
        os.chdir(root)
        with patch.object(module.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = json.dumps(status)
            assert module._from_deployed_state() == (
                status["resources"][0]["arn"], "connector-test"
            )
            run.assert_called_once()
    finally:
        os.chdir(original_dir)

print("setup_payment_user v1 discovery: PASSED")
