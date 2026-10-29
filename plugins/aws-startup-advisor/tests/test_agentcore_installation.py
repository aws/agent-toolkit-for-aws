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
import json, os, pathlib, re, sys
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
    # ProjectNameSchema and reserved dependency names at CLI e2f59dad.
    assert re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,22}", opts["--name"])
    reserved = """
    anthropic autogen autogenagentchat autogenext bedrock bedrockagentcore
    crewai crewaitools googleadk googlegenerativeai langchain langchainanthropic
    langchainaws langchaingooglegenai langchainmcpadapters langchainopenai
    langgraph mcp openai openaiagents strands strandsagents strandsagentstools
    agui aguistrands aguilanggraph aguiadk aguiprotocol vercelai aisdk
    httpx pytest pytestasyncio pythondotenv tiktoken hatchling setuptools wheel
    awsopentelemetrydistro boto3 botocore test tests src lib dist build env venv site pip uv
    """.split()
    assert opts["--name"].lower() not in reserved
    project = cwd / opts["--name"]
    project.mkdir()
    (project / "agentcore").mkdir()
    (project / "agentcore/agentcore.json").write_text(json.dumps({"name": opts["--name"]}))
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
        assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", opts["--name"])
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
def generated(tmp_path, request):
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
            "{target_region}": "us-east-1", "{agent_id}": getattr(request, "param", "assistant"),
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
    npm_root = tmp_path / "npm global modules"
    entry = npm_root / "@aws/agentcore/dist/index.js"
    entry.parent.mkdir(parents=True)
    entry.write_text(CLI_STUB)
    for name, body in {
        "agentcore": CLI_STUB,
        "node": 'import os,sys\nos.execv(sys.executable, [sys.executable, *sys.argv[1:]])\n',
        "npm": '''import os,sys
args = sys.argv[1:]
if args == ["root", "-g"]:
    print(os.environ["NPM_ROOT"])
elif args == ["ls", "-g", "--depth=0", "@aws/agentcore"]:
    sys.exit(1 if os.environ.get("MISSING_NPM_CLI") else 0)
else:
    assert args == ["install", "-g", "@aws/agentcore"]
    open(os.environ["INSTALL_LOG"], "a").write("npm\\n")
''',
    }.items():
        executable = binaries / name
        executable.write_text(f"#!{sys.executable}\n{body}")
        executable.chmod(0o755)
    return source, config, {
        "PATH": str(binaries), "COMMAND_LOG": str(log),
        "INSTALL_LOG": str(tmp_path / "installs"),
        "NPM_ROOT": str(npm_root),
        "PROJECT_NAME": "CustomerA",
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
    project = source / env["PROJECT_NAME"]
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
    project = source / env["PROJECT_NAME"]
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


@pytest.mark.parametrize("harness_length,accepted", [(8, True), (9, False)])
def test_harness_budget_uses_selected_project_name(generated, harness_length, accepted):
    source, config, env = generated
    env["PROJECT_NAME"] = "P" + "x" * 22
    config["name"] = "a" * harness_length
    (source / "harness.json").write_text(json.dumps(config))
    result = _run(generated, "harness")
    assert (result.returncode == 0) == accepted, result.stderr
    if not accepted:
        assert "exceeds 40 characters" in result.stderr
        assert not Path(env["COMMAND_LOG"]).exists()


@pytest.mark.parametrize("generated", ["research-agent", "Research-Agent_2", "a" * 48], indirect=True)
def test_strands_source_id_maps_to_valid_runtime_name(generated, request):
    source, _, env = generated
    result = _run(generated, "strands")
    assert result.returncode == 0, result.stderr
    runtime_name = request.node.callspec.params["generated"].replace("-", "_")
    project = source / env["PROJECT_NAME"]
    state = json.loads((project / "registered.json").read_text())
    assert state["options"]["--name"] == runtime_name
    assert (project / "app" / runtime_name / "main.py").is_file()
    calls = [json.loads(line) for line in Path(env["COMMAND_LOG"]).read_text().splitlines()]
    assert calls[-1]["args"][calls[-1]["args"].index("--runtime") + 1] == runtime_name


@pytest.mark.parametrize("generated", ["", "9agent", "a" * 49, "agent/path"], indirect=True)
def test_invalid_runtime_name_stops_before_install_or_create(generated):
    result = _run(generated, "strands")
    assert result.returncode != 0
    assert "Runtime name" in result.stderr
    assert not Path(generated[2]["COMMAND_LOG"]).exists()
    assert not Path(generated[2]["INSTALL_LOG"]).exists()


@pytest.mark.parametrize("name", ["bad_name", "a" * 24, "9project", "strands"])
def test_cli_stub_rejects_invalid_or_reserved_project_names(generated, name):
    source, _, env = generated
    result = subprocess.run(
        [str(Path(env["PATH"]) / "node"),
         str(Path(env["NPM_ROOT"]) / "@aws/agentcore/dist/index.js"),
         "create", "--name", name],
        cwd=source, env=env, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert not (source / name).exists()


@pytest.mark.parametrize("name", ["harness", "strands"])
@pytest.mark.parametrize("project_name", [None, "", "bad_name", "9project", "a" * 24])
def test_project_identity_is_required_and_validated_before_mutation(generated, name, project_name):
    _, _, env = generated
    if project_name is None:
        env.pop("PROJECT_NAME")
    else:
        env["PROJECT_NAME"] = project_name
    result = _run(generated, name)
    assert result.returncode != 0
    assert "PROJECT_NAME" in result.stderr
    assert not Path(env["COMMAND_LOG"]).exists()
    assert not Path(env["INSTALL_LOG"]).exists()


@pytest.mark.parametrize("name", ["harness", "strands"])
def test_independent_migrations_keep_distinct_project_identities_on_update(generated, name):
    source, _, env = generated
    for project_name in ("CustomerA", "CustomerB"):
        env["PROJECT_NAME"] = project_name
        result = _run(generated, name)
        assert result.returncode == 0, result.stderr
        project = source / project_name
        assert json.loads((project / "agentcore/agentcore.json").read_text())["name"] == project_name
        assert str(project) in result.stdout
    calls = [json.loads(line) for line in Path(env["COMMAND_LOG"]).read_text().splitlines()]
    assert {call["cwd"] for call in calls if call["args"][0] == "deploy"} == {
        str(source / "CustomerA"), str(source / "CustomerB")
    }
    # A later update runs in the retained project: it must not create a new one
    # or take its identity from a changed shell variable.
    env["PROJECT_NAME"] = "UnrelatedProject"
    result = subprocess.run(
        [str(Path(env["PATH"]) / "node"),
         str(Path(env["NPM_ROOT"]) / "@aws/agentcore/dist/index.js"),
         "deploy", "--region", "us-east-1"],
        cwd=source / "CustomerA", env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads((source / "CustomerA/agentcore/agentcore.json").read_text())["name"] == "CustomerA"
    assert not (source / "UnrelatedProject").exists()


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
        "{model_id}": "test-model", "{target_region}": "us-east-1",
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


def test_generated_factories_keep_their_own_model():
    import types
    template = REFERENCE.read_text().split("## Step 3E:", 1)[1].split("```python\n", 1)[1].split("\n```", 1)[0]
    sdk = types.ModuleType("strands")
    models = types.ModuleType("strands.models")
    sdk.Agent = lambda **kwargs: kwargs
    sdk.tool = lambda function: function
    models.BedrockModel = lambda **kwargs: kwargs["model_id"]
    namespace = {"__name__": "generated_agents"}
    with pytest.MonkeyPatch.context() as patch:
        patch.setitem(sys.modules, "strands", sdk)
        patch.setitem(sys.modules, "strands.models", models)
        for name in ("first", "second"):
            code = template
            for token, value in {
                "{agent_name}": name, "{agent_id}": name, "{model_id}": name + "-model",
                "{tool_name}": name + "_tool", "{params}": "query: str",
                "{tool_list}": name + "_tool", "{system_prompt}": "Help the user",
                "{target_region}": "us-east-1",
            }.items():
                code = code.replace(token, value)
            exec(compile(code, "strands_agents.py", "exec"), namespace)
        assert namespace["create_first"]()["model"] == "first-model"
        assert namespace["create_second"]()["model"] == "second-model"


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
    generated[2]["MISSING_NPM_CLI"] = "1"
    result = _run(generated, "harness", execute)
    assert result.returncode == (1 if execute else 0), result.stderr
    assert "npm install -g @aws/agentcore" in result.stdout
    assert not re.search(r"bedrock[-_.]agentcore[-_.]cli", result.stdout, re.I)


@pytest.mark.parametrize("name", ["harness", "strands"])
@pytest.mark.parametrize("official_present", [False, True])
def test_python_cli_on_path_cannot_shadow_npm_entrypoint(generated, name, official_present):
    source, _, env = generated
    shadow = Path(env["PATH"]) / "agentcore"
    shadow.write_text("#!/bin/sh\nexit 91\n")
    if not official_present:
        env["MISSING_NPM_CLI"] = "1"
    result = _run(generated, name)
    assert result.returncode == (0 if official_present else 1), result.stderr
    if official_present:
        calls = Path(env["COMMAND_LOG"]).read_text()
        assert '"invoke"' in calls
    else:
        assert "npm install -g @aws/agentcore" in result.stdout
        assert "pip uninstall bedrock-agentcore-starter-toolkit" in result.stdout
        assert not Path(env["COMMAND_LOG"]).exists()
        assert not list(source.glob("*/agentcore"))


def test_incremental_guidance_uses_npm_entrypoint_outside_script_shell():
    section = REFERENCE.read_text().split(
        "**Artifact 3: `ai-migration/incremental_migration.sh`**", 1
    )[1].split("## Step 3D:", 1)[0]
    commands = re.findall(r"`([^`]+)`", section)
    assert not any(command.startswith("agentcore ") for command in commands)
    for verb in ("deploy", "invoke"):
        assert any(
            command.startswith(f'node "$(npm root -g)/@aws/agentcore/dist/index.js" {verb}')
            for command in commands
        )


def test_incremental_guidance_separates_source_and_target_sessions():
    section = REFERENCE.read_text().split(
        "**Artifact 3: `ai-migration/incremental_migration.sh`**", 1
    )[1].split("## Step 3D:", 1)[0]
    assert '--session-id "$SOURCE_SESSION_ID"' in section
    assert '--session-id "$TARGET_SESSION_ID"' in section
    assert "two distinct UUIDs" in section
    assert "Session history is not transferred" in section
    canonical = PLUGIN_ROOT / "skills/shared/ai/design-ref-harness.md"
    assert "Session history is not transferred" in canonical.read_text()
    assert "against both models on same session" not in canonical.read_text()
