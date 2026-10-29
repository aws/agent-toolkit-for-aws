"""Exercise generated AgentCore installation steps with inert package-manager stubs."""
from pathlib import Path
import re
import subprocess

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = (
    PLUGIN_ROOT
    / "skills/gcp-to-aws/references/phases/generate/generate-artifacts-ai.md"
)


def _script(name: str) -> str:
    section = REFERENCE.read_text().split(
        f"**Artifact 2: `ai-migration/deploy_{name}.sh`**", 1
    )[1]
    return section.split("```bash\n", 1)[1].split("\n```", 1)[0]


@pytest.mark.parametrize("name", ["harness", "strands"])
def test_generated_shell_syntax(name: str) -> None:
    subprocess.run(["/bin/bash", "-n"], input=_script(name), text=True, check=True)


@pytest.mark.parametrize("execute", [False, True])
def test_harness_missing_cli_recommends_official_distribution(tmp_path: Path, execute: bool) -> None:
    # No executable on PATH: the prerequisite check must take the missing-CLI branch.
    prerequisite = _script("harness").split("# Step 2:", 1)[0]
    result = subprocess.run(
        ["/bin/bash", "-c", prerequisite, "probe", *(["--execute"] if execute else [])],
        env={"PATH": str(tmp_path)},
        text=True,
        capture_output=True,
    )
    assert result.returncode == (1 if execute else 0)
    assert "npm install -g @aws/agentcore" in result.stdout
    assert not re.search(r"bedrock[-_.]agentcore[-_.]cli", result.stdout, re.I)


@pytest.mark.parametrize("execute", [False, True])
def test_strands_installation_keeps_python_dependencies_and_uses_npm(
    tmp_path: Path, execute: bool
) -> None:
    log = tmp_path / "commands"
    for command in ("pip", "npm"):
        stub = tmp_path / command
        stub.write_text(f'#!/bin/sh\nprintf "{command} %s\\n" "$*" >> "$COMMAND_LOG"\n')
        stub.chmod(0o755)
    prerequisite = _script("strands").split("# Step 2:", 1)[0]
    result = subprocess.run(
        ["/bin/bash", "-c", prerequisite, "probe", *(["--execute"] if execute else [])],
        env={"PATH": str(tmp_path), "COMMAND_LOG": str(log)},
        text=True,
        capture_output=True,
        check=True,
    )
    assert not re.search(r"bedrock[-_.]agentcore[-_.]cli", result.stdout, re.I)
    if execute:
        assert log.read_text().splitlines() == [
            "pip install strands-agents strands-agents-tools boto3",
            "npm install -g @aws/agentcore",
        ]
    else:
        assert not log.exists()
        assert "[DRY-RUN] npm install -g @aws/agentcore" in result.stdout
