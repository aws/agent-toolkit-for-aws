"""Exercise generated CLI 1.0.1 workflows without installation or AWS calls."""
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = PLUGIN_ROOT / "skills/gcp-to-aws/references/phases/generate/generate-artifacts-ai.md"


def _script(name: str) -> str:
    section = REFERENCE.read_text().split(
        f"**Artifact 2: `ai-migration/deploy_{name}.sh`**", 1
    )[1]
    return section.split("```bash\n", 1)[1].split("\n```", 1)[0]


# Implements only documented command boundaries, not AWS behavior. In particular,
# create makes an EMPTY child project, and add runtime creates NO implementation.
CLI_STUB = r'''
import json, os, pathlib, sys
args = sys.argv[1:]
cwd = pathlib.Path.cwd()
with open(os.environ["COMMAND_LOG"], "a") as log:
    log.write(json.dumps({"args": args, "cwd": str(cwd)}) + "\n")
if os.environ.get("FAIL_COMMAND") == args[0]:
    sys.exit(23)

def options(tokens, allowed, switches=()):
    result = {}
    while tokens:
        key = tokens.pop(0)
        assert key in allowed, f"Unsupported option: {key}"
        result[key] = True if key in switches else tokens.pop(0)
    return result

if args[0] == "create":
    opts = options(args[1:], {"--name", "--skip-git", "--skip-install"}, {"--skip-git", "--skip-install"})
    project = cwd / opts["--name"]
    project.mkdir()
    (project / "agentcore").mkdir()
    (project / "agentcore/agentcore.json").write_text("{}")
else:
    assert (cwd / "agentcore/agentcore.json").is_file(), "Not inside the created project"
    state_file = cwd / "registered.json"
    if args[:2] == ["add", "harness"]:
        opts = options(args[2:], {"--name", "--model", "--system-prompt", "--tools", "--authorizer-type"})
        assert opts["--authorizer-type"] == "AWS_IAM"
        model = json.loads(opts["--model"])
        assert model["provider"] == "bedrock" and model["modelId"]
        assert isinstance(json.loads(opts["--tools"]), list)
        state_file.write_text(json.dumps({"kind": "harness", "options": opts}))
    elif args[:2] == ["add", "runtime"]:
        opts = options(args[2:], {"--name", "--language", "--protocol", "--authorizer-type"})
        assert opts["--authorizer-type"] == "AWS_IAM"
        assert opts["--language"] == "python" and opts.get("--protocol", "HTTP") == "HTTP"
        (cwd / "app" / opts["--name"]).mkdir(parents=True)
        state_file.write_text(json.dumps({"kind": "runtime", "options": opts}))
    elif args[0] == "deploy":
        opts = options(args[1:], {"--region"})
        assert opts["--region"] == "us-east-1"
        state = json.loads(state_file.read_text())
        if state["kind"] == "runtime":
            app = cwd / "app" / state["options"]["--name"]
            for filename in ("main.py", "strands_agents.py", "pyproject.toml"):
                assert (app / filename).is_file(), f"Missing runtime source: {filename}"
            assert 'entrypoint = "main.py"' in (app / "pyproject.toml").read_text()
        (cwd / "deployed").touch()
    elif args[0] == "invoke":
        opts = options(args[1:], {"--harness", "--runtime", "--region", "--prompt", "--payload"})
        assert (cwd / "deployed").exists()
        state = json.loads(state_file.read_text())
        assert opts["--" + state["kind"]] == state["options"]["--name"]
        if state["kind"] == "harness":
            assert opts["--prompt"]
        else:
            assert json.loads(opts["--payload"])["prompt"]
    else:
        raise AssertionError(f"Unexpected command: {args}")
'''


@pytest.fixture
def generated(tmp_path):
    source = tmp_path / "artifacts with spaces"
    source.mkdir()
    config = {
        "name": "assistant",
        "model": {"provider": "bedrock", "modelId": "test-model"},
        "systemPrompt": "Don't execute $(touch injected) or `touch injected2`.\nKeep this newline.\n",
        "tools": [{"type": "remote_mcp", "name": "research", "config": {
            "remoteMcp": {"url": "https://example.com/mcp?a=b&c=d"}
        }}],
    }
    (source / "harness.json").write_text(json.dumps(config))
    for name in ("harness", "strands"):
        text = _script(name)
        for token, value in {
            "{target_region from preferences.json}": "us-east-1",
            "{target_region}": "us-east-1", "{agent_id}": "assistant",
            "{harness_config.name}": "assistant",
            "{harness_config.model_id}": "test-model", "{agent_count}": "1",
        }.items():
            text = text.replace(token, value)
        (source / f"deploy_{name}.sh").write_text(text)
    (source / "strands_agents.py").write_text('def invoke(prompt):\n    return "migrated:" + prompt\n')
    text = REFERENCE.read_text().split("**Runtime files:", 1)[-1]
    (source / "main.py").write_text(text.split("```python\n", 1)[1].split("\n```", 1)[0])
    (source / "pyproject.toml").write_text(text.split("```toml\n", 1)[1].split("\n```", 1)[0])
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name, target in {"python3": sys.executable, "dirname": "/usr/bin/dirname", "cp": "/bin/cp"}.items():
        (binaries / name).symlink_to(target)
    log = tmp_path / "commands.jsonl"
    for name, body in {
        "agentcore": CLI_STUB,
        "npm": 'import os,sys\nassert sys.argv[1:] == ["install", "-g", "@aws/agentcore"]\nopen(os.environ["INSTALL_LOG"], "a").write("npm\\n")\n',
    }.items():
        executable = binaries / name
        executable.write_text(f"#!{sys.executable}\n{body}")
        executable.chmod(0o755)
    return source, config, {
        "PATH": str(binaries), "COMMAND_LOG": str(log),
        "INSTALL_LOG": str(tmp_path / "installs"),
    }


def _run(generated, name, execute=True):
    source, _, env = generated
    return subprocess.run(
        ["/bin/bash", str(source / f"deploy_{name}.sh"), *(["--execute"] if execute else [])],
        cwd=source.parent, env=env, text=True, capture_output=True,
    )


@pytest.mark.parametrize("name", ["harness", "strands"])
def test_generated_shell_syntax(name):
    subprocess.run(["/bin/bash", "-n"], input=_script(name), text=True, check=True)


@pytest.mark.parametrize("name", ["harness", "strands"])
def test_dry_run_has_no_installs_or_project_side_effects(generated, name):
    source, _, env = generated
    result = _run(generated, name, execute=False)
    assert result.returncode == 0, result.stderr
    assert not Path(env["COMMAND_LOG"]).exists()
    assert not Path(env["INSTALL_LOG"]).exists()
    assert not list(source.glob("*/agentcore"))
    assert "no project was created or deployed" in result.stdout


def test_harness_preserves_json_and_prompt_as_arguments(generated):
    source, config, env = generated
    result = _run(generated, "harness")
    assert result.returncode == 0, result.stderr
    project = source / "migration"
    state = json.loads((project / "registered.json").read_text())["options"]
    assert json.loads(state["--model"]) == config["model"]
    assert json.loads(state["--tools"]) == config["tools"]
    assert state["--system-prompt"] == config["systemPrompt"]
    assert not list(source.rglob("injected*"))
    calls = [json.loads(line) for line in Path(env["COMMAND_LOG"]).read_text().splitlines()]
    assert [call["args"][0] for call in calls] == ["create", "add", "deploy", "invoke"]
    assert all(call["cwd"] == str(project) for call in calls[1:])


def test_strands_registers_and_deploys_generated_code(generated):
    source, _, env = generated
    result = _run(generated, "strands")
    assert result.returncode == 0, result.stderr
    project = source / "assistant_strands"
    for name in ("main.py", "strands_agents.py", "pyproject.toml"):
        assert (project / "app/assistant" / name).read_bytes() == (source / name).read_bytes()
    manifest = (source / "pyproject.toml").read_text()
    for dependency in ("bedrock-agentcore", "aws-opentelemetry-distro", "strands-agents", "strands-agents-tools", "boto3"):
        assert f'"{dependency}"' in manifest
    calls = [json.loads(line) for line in Path(env["COMMAND_LOG"]).read_text().splitlines()]
    assert [call["args"][0] for call in calls] == ["create", "add", "deploy", "invoke"]
    assert all(call["cwd"] == str(project) for call in calls[1:])


@pytest.mark.parametrize("length,accepted", [(22, True), (23, False)])
def test_harness_combined_name_limit(generated, length, accepted):
    source, config, env = generated
    config["name"] = "a" * length
    (source / "harness.json").write_text(json.dumps(config))
    result = _run(generated, "harness")
    assert (result.returncode == 0) == accepted, result.stderr
    if not accepted:
        assert "exceeds 40 characters" in result.stderr
        assert not Path(env["COMMAND_LOG"]).exists()


def test_runtime_entrypoint_invokes_migrated_callable_without_import_inference(generated):
    source, _, _ = generated
    # Load only the generated wrapper with fake SDK and migrated modules.
    import types
    sdk = types.ModuleType("bedrock_agentcore.runtime")
    calls = []
    class App:
        def entrypoint(self, function):
            return function
        def run(self):
            raise AssertionError("Must not start a server on import")
    sdk.BedrockAgentCoreApp = App
    agent = types.ModuleType("strands_agents")
    agent.invoke = lambda prompt: calls.append(prompt) or "result"
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, "bedrock_agentcore", types.ModuleType("bedrock_agentcore"))
        patch.setitem(sys.modules, "bedrock_agentcore.runtime", sdk)
        patch.setitem(sys.modules, "strands_agents", agent)
        namespace = {"__name__": "generated_runtime"}
        exec(compile((source / "main.py").read_text(), "main.py", "exec"), namespace)
        assert calls == []
        assert namespace["handle"]({"prompt": "test"}) == {"result": "result"}
        assert calls == ["test"]

def test_generated_agent_factory_does_not_share_conversation_state():
    import types
    text = REFERENCE.read_text().split("## Step 3E:", 1)[1]
    code = text.split("```python\n", 1)[1].split("\n```", 1)[0]
    for token, value in {
        "{agent_name}": "assistant", "{agent_id}": "assistant",
        "{tool_name}": "lookup", "{params}": "query: str",
        "{tool_list}": "lookup", "{system_prompt}": "Help the user",
        "{agents[0].model_id}": "test-model", "{target_region}": "us-east-1",
    }.items():
        code = code.replace(token, value)
    sdk = types.ModuleType("strands")
    models = types.ModuleType("strands.models")
    instances = []
    class Agent:
        def __init__(self, **kwargs):
            self.history = []
            instances.append(self)
        def __call__(self, prompt):
            self.history.append(prompt)
            return prompt
    sdk.Agent = Agent
    sdk.tool = lambda function: function
    models.BedrockModel = lambda **kwargs: object()
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, "strands", sdk)
        patch.setitem(sys.modules, "strands.models", models)
        namespace = {"__name__": "generated_agents"}
        exec(compile(code, "strands_agents.py", "exec"), namespace)
        assert instances == []
        namespace["create_assistant"]()("first request")
        namespace["create_assistant"]()("second request")
        assert [agent.history for agent in instances] == [["first request"], ["second request"]]


@pytest.mark.parametrize("name", ["harness", "strands"])
@pytest.mark.parametrize("command", ["create", "add", "deploy"])
def test_command_failure_stops_before_invocation(generated, name, command):
    generated[2]["FAIL_COMMAND"] = command
    result = _run(generated, name)
    assert result.returncode == 23
    calls = Path(generated[2]["COMMAND_LOG"]).read_text()
    assert '"invoke"' not in calls
    assert "Deployment and test invocation completed" not in result.stdout


@pytest.mark.parametrize("execute", [False, True])
def test_missing_harness_cli_keeps_recommendation_and_failure(generated, execute):
    (Path(generated[2]["PATH"]) / "agentcore").unlink()
    result = _run(generated, "harness", execute)
    assert result.returncode == (1 if execute else 0), result.stderr
    assert "npm install -g @aws/agentcore" in result.stdout
    assert not re.search(r"bedrock[-_.]agentcore[-_.]cli", result.stdout, re.I)
