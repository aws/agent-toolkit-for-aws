from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent
GCP = PLUGIN / "skills/gcp-to-aws"
BMA = PLUGIN / "skills/bedrock-migration-assessment"
SCRIPT = GCP / "scripts/bma-route-classifier.py"
PATTERNS = GCP / "references/runtime/bma-input-patterns.json"
MANIFEST = GCP / "references/runtime/bma-bootstrap-manifest.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_hash(root: Path) -> str:
    value = hashlib.sha256()
    if not root.exists():
        return value.hexdigest()
    for path in sorted(root.rglob("*")):
        if path.is_file() and not path.is_symlink():
            value.update(path.relative_to(root).as_posix().encode())
            value.update(path.read_bytes())
    return value.hexdigest()


def invoke(project: Path, provider: str = "none", resume: Path | None = None,
           bma: Path | None = None, gcp: Path = GCP, sandbox: bool = False,
           expected_manifest_sha: str | None = None) -> tuple[subprocess.CompletedProcess, dict, list[str], dict]:
    script = gcp / "scripts/bma-route-classifier.py"
    patterns = gcp / "references/runtime/bma-input-patterns.json"
    manifest = gcp / "references/runtime/bma-bootstrap-manifest.json"
    argv = [sys.executable, "-B", str(script), "classify", "--project-root", str(project),
            "--patterns", str(patterns), "--bootstrap-manifest", str(manifest),
            "--expected-bootstrap-manifest-sha256", expected_manifest_sha or sha(manifest), "--provider-intent", provider]
    if resume:
        argv += ["--resume-dir", str(resume)]
    if bma:
        argv += ["--bma-base", str(bma)]
    roots = {"project": project, "run": resume or project / ".migration", "gcp": gcp, "bma": bma or BMA}
    before = {name: tree_hash(root) for name, root in roots.items()}
    command = argv
    if sandbox and sys.platform == "darwin" and shutil.which("sandbox-exec"):
        command = ["sandbox-exec", "-p", "(version 1)(allow default)(deny file-write*)", *argv]
    completed = subprocess.run(command, text=True, capture_output=True,
                               env={"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"})
    after = {name: tree_hash(root) for name, root in roots.items()}
    return completed, json.loads(completed.stdout), argv, {"before": before, "after": after}


def paired(project: Path, provider: str = "none", resume: Path | None = None) -> tuple[dict, dict]:
    first, first_value, first_argv, first_hashes = invoke(project, provider, resume, sandbox=True)
    assert first.returncode == 0, first.stderr
    assert first_value["AI_CANDIDATE"] is True
    assert "--bma-base" not in first_argv
    assert not any("/skills/bedrock-migration-assessment/" in row["path"] for row in first_value["audit"])
    assert first_value["mutation_count"] == 0
    assert first_hashes["before"] == first_hashes["after"]
    second, second_value, second_argv, second_hashes = invoke(project, provider, resume, BMA, sandbox=True)
    assert second.returncode == 0, second.stderr
    assert second_argv[-2:] == ["--bma-base", str(BMA)]
    assert second_value["exact_sibling"] == str(BMA.resolve())
    assert second_value["closure_entries"] == 66
    assert second_value["closure_audit_complete"] is True
    closure = json.loads((BMA / "references/runtime/closure.json").read_text())
    expected = [("lstat", str((BMA / "SKILL.md").resolve())), ("read", str((BMA / "SKILL.md").resolve())),
                ("lstat", str((BMA / "references/runtime/closure.json").resolve())),
                ("read", str((BMA / "references/runtime/closure.json").resolve()))]
    for entry in closure["entries"]:
        member = str((BMA / entry["destination"]).resolve())
        expected.extend((("lstat", member), ("read", member)))
    actual = [(row["op"], row["path"]) for row in second_value["audit"] if row["path"].startswith(str(BMA.resolve()))]
    assert actual == expected
    assert second_value["mutation_count"] == 0
    assert second_hashes["before"] == second_hashes["after"]
    return first_value, second_value


TERRAFORM_FILES = ["main.tf", "main.tf.json", "terraform.tfvars", "prod.auto.tfvars", "terraform.tfstate", ".terraform.lock.hcl"]
BILLING_FILES = ["billing.csv", "billing.json", "monthly-cost.csv", "monthly-cost.json", "usage.csv", "usage.json"]
SOURCE_FILES = ["app.py", "app.js", "app.ts", "app.jsx", "app.tsx", "app.go", "App.java", "App.scala", "App.kt", "app.rs"]
MANIFEST_FILES = ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile", "package.json", "package-lock.json", "yarn.lock", "go.mod", "go.sum", "pom.xml", "build.gradle"]
PROVIDERS = ["openai", "anthropic", "openrouter", "anthropic,openai", "anthropic,openrouter", "openai,openrouter", "anthropic,openai,openrouter"]
DURABLE_FILES = ["ai-workload-profile.json", "openai-usage-profile.json", "anthropic-usage-profile.json", "openrouter-usage-profile.json", "aws-design-ai.json", "estimation-ai.json", "generation-ai.json"]


@pytest.mark.parametrize("name", TERRAFORM_FILES)
def test_every_terraform_pattern_is_pure_infrastructure_without_bma(tmp_path: Path, name: str) -> None:
    project = tmp_path / "project"; target = project / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text("{}\n" if name.endswith(".json") else "# fixture\n")
    completed, value, argv, hashes = invoke(project, sandbox=True)
    assert completed.returncode == 0 and value["PURE_INFRASTRUCTURE"] is True
    assert value["AI_CANDIDATE"] is False and "--bma-base" not in argv
    assert not any(row["path"].startswith(str(BMA.resolve())) for row in value["audit"])
    assert hashes["before"] == hashes["after"] and value["mutation_count"] == 0


@pytest.mark.parametrize("name", BILLING_FILES)
def test_every_billing_pattern_is_pure_infrastructure_without_bma(tmp_path: Path, name: str) -> None:
    project = tmp_path / "project"; project.mkdir(); (project / name).write_text("{}\n")
    completed, value, _, hashes = invoke(project, sandbox=True)
    assert completed.returncode == 0 and value["PURE_INFRASTRUCTURE"] is True
    assert value["AI_CANDIDATE"] is False
    assert not any(row["path"].startswith(str(BMA.resolve())) for row in value["audit"])
    assert hashes["before"] == hashes["after"] and value["mutation_count"] == 0


@pytest.mark.parametrize("provider", ["", "none,openai", "openai,openai", "openrouter,openai", "unknown", "openai,"])
def test_invalid_provider_forms_fail_before_inventory(tmp_path: Path, provider: str) -> None:
    project = tmp_path / "project"; project.mkdir()
    completed, value, _, hashes = invoke(project, provider=provider, sandbox=True)
    assert completed.returncode == 2 and value["reason"] == "provider_intent_invalid"
    assert not any(row["op"] == "walk" for row in value["audit"])
    assert not any(row["path"].startswith(str(BMA.resolve())) for row in value["audit"])
    assert hashes["before"] == hashes["after"]


@pytest.mark.parametrize("terraform", [
    'resource "google_bigquery_dataset" "x" {}',
    'resource "google_bigquery_ml_model" "x" {}',
])
def test_bigquery_weak_and_ordinary_are_not_ai_candidates(tmp_path: Path, terraform: str) -> None:
    project = tmp_path / "project"; project.mkdir(); (project / "main.tf").write_text(terraform)
    completed, value, _, hashes = invoke(project, sandbox=True)
    assert completed.returncode == 0
    assert value["VERTEX_STRONG_CANDIDATE"] is False and value["AI_CANDIDATE"] is False
    assert value["PURE_INFRASTRUCTURE"] is True and hashes["before"] == hashes["after"]


@pytest.mark.parametrize("name", SOURCE_FILES + MANIFEST_FILES)
def test_every_source_and_manifest_without_ai_signals_is_not_a_candidate(tmp_path: Path, name: str) -> None:
    # Review 5620455181 (vagmur-aws, comment 4353203462): source presence alone must not route to BMA.
    project = tmp_path / "project"; project.mkdir(); (project / name).write_text("x\n")
    completed, value, _, hashes = invoke(project, sandbox=True)
    assert completed.returncode == 0, completed.stderr
    assert value["SOURCE_CONTAINING"] is True
    assert value["AI_SIGNAL_CANDIDATE"] is False and value["ai_signal_files"] == []
    assert value["AI_CANDIDATE"] is False and value["PURE_INFRASTRUCTURE"] is False
    assert not any("/skills/bedrock-migration-assessment/" in row["path"] for row in value["audit"])
    assert hashes["before"] == hashes["after"]


@pytest.mark.parametrize("name", SOURCE_FILES + MANIFEST_FILES)
def test_every_source_and_manifest_with_ai_signal_has_paired_preflight(tmp_path: Path, name: str) -> None:
    project = tmp_path / "project"; project.mkdir()
    (project / name).write_text("openai\n" if name in MANIFEST_FILES else "import openai\n")
    first, _ = paired(project)
    assert first["SOURCE_CONTAINING"] is True
    assert first["AI_SIGNAL_CANDIDATE"] is True and first["ai_signal_files"] == [name]


def _reviewer_layout(project: Path) -> None:
    (project / "infra").mkdir(parents=True); (project / "scripts").mkdir()
    (project / "infra/main.tf").write_text('resource "google_compute_instance" "x" {}\n')
    (project / "scripts/cleanup.py").write_text('print("rotate logs")\n')


def test_reviewer_repro_infra_plus_plain_script_is_pure_infrastructure(tmp_path: Path) -> None:
    # Exact repro from PR #483 comment 4353203462.
    project = tmp_path / "project"; _reviewer_layout(project)
    completed, value, _, hashes = invoke(project, sandbox=True)
    assert completed.returncode == 0, completed.stderr
    assert value["AI_CANDIDATE"] is False and value["PURE_INFRASTRUCTURE"] is True
    assert value["SOURCE_CONTAINING"] is True and value["AI_SIGNAL_CANDIDATE"] is False
    assert not any("/skills/bedrock-migration-assessment/" in row["path"] for row in value["audit"])
    assert hashes["before"] == hashes["after"]
    denied, denied_value, _, _ = invoke(project, bma=BMA)
    assert denied.returncode == 2 and denied_value["reason"] == "bma_preflight_not_authorized_for_non_candidate"
    # With only gcp-to-aws installed (sibling absent) the run still classifies and never needs BMA.
    gcp = tmp_path / "skills/gcp-to-aws"; shutil.copytree(GCP, gcp)
    assert not (tmp_path / "skills/bedrock-migration-assessment").exists()
    alone, alone_value, _, _ = invoke(project, gcp=gcp, sandbox=True)
    assert alone.returncode == 0, alone.stderr
    assert alone_value["AI_CANDIDATE"] is False and alone_value["PURE_INFRASTRUCTURE"] is True
    assert not any("/bedrock-migration-assessment/" in row["path"] for row in alone_value["audit"])


def test_reviewer_repro_plus_openai_import_is_candidate(tmp_path: Path) -> None:
    project = tmp_path / "project"; _reviewer_layout(project)
    (project / "scripts/ask.py").write_text("import openai\nclient = openai.OpenAI()\n")
    first, _ = paired(project)
    assert first["PURE_INFRASTRUCTURE"] is False
    assert first["ai_signal_files"] == ["scripts/ask.py"]


@pytest.mark.parametrize("name,content", [
    ("client.ts", 'const url = "https://api.openai.com/v1/chat/completions";\n'),
    ("settings.py", 'key = os.environ["ANTHROPIC_API_KEY"]\n'),
    ("model.js", 'const model = "claude-3-5-sonnet";\n'),
    ("requirements.txt", "anthropic==0.40.0\n"),
    ("package.json", '{"dependencies": {"openai": "^4.0.0"}}\n'),
    ("main.go", 'import "cloud.google.com/go/aiplatform/apiv1"\n'),
    ("App.java", "import com.google.cloud.aiplatform.v1.PredictionServiceClient;\n"),
    ("vertex.py", "from google.cloud import aiplatform\naiplatform.init(project=PROJECT)\n"),
    ("vertex_alias.py", "from google.cloud import storage, aiplatform as aip\n"),
    ("ocr.py", "from google.cloud import vision\n"),
    ("multi.py", "from google.cloud import (\n    storage,\n    aiplatform,\n)\n"),
    # Review 5661016215 (comment 4384076088): current Google GenAI SDK, one case per form.
    ("genai.py", "from google import genai\nclient = genai.Client()\n"),
    ("genai_dotted.py", "import google.genai\n"),
    ("chat.ts", 'import { GoogleGenAI } from "@google/genai";\n'),
    ("requirements.txt", "google-genai==1.2.0\n"),
    ("package.json", '{"dependencies": {"@google/genai": "^1.0.0"}}\n'),
], ids=["endpoint", "env-var", "model-prefix", "dependency-requirements", "dependency-package-json", "go-import", "java-import",
        "python-from-package-import", "python-from-package-import-alias", "python-from-package-import-vision",
        "python-from-package-import-parenthesised", "python-from-google-import-genai", "python-import-google-genai",
        "ts-google-genai-import", "dependency-google-genai-pip", "dependency-google-genai-npm"])
def test_each_ai_signal_family_is_candidate(tmp_path: Path, name: str, content: str) -> None:
    project = tmp_path / "project"; project.mkdir(); (project / name).write_text(content)
    first, _ = paired(project)
    assert first["ai_signal_files"] == [name]


@pytest.mark.parametrize("name,content", [
    ("cleanup.py", 'print("rotate logs")\n'),
    ("notes.py", '# we considered openai and anthropic but use neither\n'),
    ("util.js", 'const anthropic_like = 1; // myopenai\n'),
    ("requirements.txt", "requests==2.32.0\nnumpy\n"),
    ("tags.ts", 'const gpt = "gpt"; const o3 = "o3";\n'),
    ("blob.py", "from google.cloud import storage\nfrom google import cloud\n"),
    ("auth.py", "from google import auth\n"),
], ids=["reviewer-script", "prose-mentions", "identifier-substring", "plain-manifest", "bare-words", "non-ai-google-cloud-import",
        "non-ai-google-import"])
def test_non_ai_source_content_is_not_a_signal(tmp_path: Path, name: str, content: str) -> None:
    project = tmp_path / "project"; project.mkdir(); (project / name).write_text(content)
    completed, value, _, _ = invoke(project)
    assert completed.returncode == 0 and value["AI_SIGNAL_CANDIDATE"] is False and value["AI_CANDIDATE"] is False


def test_secret_excluded_files_are_never_read_for_signals(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    (project / ".env").write_text("OPENAI_API_KEY=sk-test\n"); (project / "credentials.json").write_text('{"api.openai.com": 1}\n')
    completed, value, _, _ = invoke(project)
    assert completed.returncode == 0 and value["AI_CANDIDATE"] is False and value["AI_SIGNAL_CANDIDATE"] is False
    assert not any(row["op"] == "read" and row["path"].startswith(str(project.resolve())) for row in value["audit"])


def _rewrite_copied_patterns(gcp: Path, mutate) -> str:
    patterns = gcp / "references/runtime/bma-input-patterns.json"; manifest = gcp / "references/runtime/bma-bootstrap-manifest.json"
    config = json.loads(patterns.read_text()); mutate(config); patterns.write_text(json.dumps(config, indent=2) + "\n")
    value = json.loads(manifest.read_text()); value["patterns"]["sha256"] = sha(patterns); value.pop("self_hash")
    value["self_hash"] = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    manifest.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    return sha(manifest)


@pytest.mark.parametrize("mutation", ["missing_family", "extra_family", "duplicate_token", "empty_family", "not_object", "empty_token"])
def test_patterns_ai_signals_schema_negatives(tmp_path: Path, mutation: str) -> None:
    def mutate(config: dict) -> None:
        signals = config["ai_signals"]
        if mutation == "missing_family": signals.pop("imports")
        elif mutation == "extra_family": signals["extra"] = ["x"]
        elif mutation == "duplicate_token": signals["imports"].append(signals["imports"][0])
        elif mutation == "empty_family": signals["endpoints"] = []
        elif mutation == "not_object": config["ai_signals"] = ["openai"]
        elif mutation == "empty_token": signals["env_vars"].append("")
    gcp = tmp_path / "gcp-to-aws"; shutil.copytree(GCP, gcp)
    expected = _rewrite_copied_patterns(gcp, mutate)
    project = tmp_path / "project"; project.mkdir(); (project / "app.py").write_text("import openai\n")
    completed, value, _, _ = invoke(project, gcp=gcp, expected_manifest_sha=expected, sandbox=True)
    assert completed.returncode == 2 and value["reason"] == "pattern_schema_invalid"
    assert not any(row["op"] == "walk" for row in value["audit"])


@pytest.mark.parametrize("provider", PROVIDERS)
def test_every_provider_form_has_paired_preflight(tmp_path: Path, provider: str) -> None:
    project = tmp_path / "project"; project.mkdir()
    first, _ = paired(project, provider)
    assert first["PROVIDER_USAGE_INTENT"] is True


@pytest.mark.parametrize("name", DURABLE_FILES)
def test_every_durable_artifact_has_paired_preflight(tmp_path: Path, name: str) -> None:
    project = tmp_path / "project"; run = project / ".migration/run"; run.mkdir(parents=True)
    (run / name).write_text("{}\n")
    first, _ = paired(project, resume=run)
    assert first["DURABLE_AI_ROUTE"] is True


@pytest.mark.parametrize("name,key", [("preferences-draft.json", "ai_constraints"), ("preferences-draft.json", "workloads"), ("preferences.json", "ai_constraints"), ("preferences.json", "workloads")])
def test_every_durable_preferences_reason_has_paired_preflight(tmp_path: Path, name: str, key: str) -> None:
    project = tmp_path / "project"; run = project / ".migration/run"; run.mkdir(parents=True)
    (run / name).write_text(json.dumps({key: {"x": 1} if key == "ai_constraints" else [{"x": 1}]}))
    first, _ = paired(project, resume=run)
    assert any(key in reason for reason in first["durable_reasons"])


@pytest.mark.parametrize("state", [{"active_route": "ai"}, {"current_phase": "ai_design"}])
def test_every_durable_active_state_reason_has_paired_preflight(tmp_path: Path, state: dict) -> None:
    project = tmp_path / "project"; run = project / ".migration/run"; run.mkdir(parents=True)
    (run / ".phase-status.json").write_text(json.dumps(state))
    paired(project, resume=run)


def test_corrupt_state_and_ai_directory_have_paired_preflight(tmp_path: Path) -> None:
    for suffix, setup in (("corrupt", lambda run: (run / ".phase-status.json").write_text("{")), ("directory", lambda run: (run / "ai-migration").mkdir())):
        project = tmp_path / suffix; run = project / ".migration/run"; run.mkdir(parents=True); setup(run)
        paired(project, resume=run)


def test_vertex_strong_has_paired_preflight(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir(); (project / "main.tf").write_text('resource "google_vertex_ai_endpoint" "x" {}\n')
    first, _ = paired(project)
    assert first["VERTEX_STRONG_CANDIDATE"] is True


def test_contextual_module_directory_is_inventory_only(tmp_path: Path) -> None:
    project = tmp_path / "project"; module = project / "infra/modules/network"; module.mkdir(parents=True)
    completed, value, _, hashes = invoke(project)
    assert completed.returncode == 0
    assert value["inventory"]["module_directories"] == ["infra/modules/network/"]
    assert value["AI_CANDIDATE"] is False and value["PURE_INFRASTRUCTURE"] is False
    assert hashes["before"] == hashes["after"]


def test_contextual_module_exclusions_nonmatches_and_symlink_no_follow(tmp_path: Path) -> None:
    project = tmp_path / "project"; (project / ".git/modules/ignored").mkdir(parents=True)
    (project / "modules").mkdir(); (project / "not-modules/x").mkdir(parents=True)
    external = tmp_path / "external"; (external / "nested").mkdir(parents=True)
    (project / "modules/link").symlink_to(external / "nested", target_is_directory=True)
    completed, value, _, _ = invoke(project)
    assert completed.returncode == 0
    assert value["inventory"]["module_directories"] == []
    assert not any("external" in row["path"] for row in value["audit"])


def test_noncandidate_denies_bma_capability_and_makes_zero_bma_operations(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir(); (project / "main.tf").write_text('resource "google_compute_instance" "x" {}\n')
    first, value, _, hashes = invoke(project)
    assert first.returncode == 0 and value["PURE_INFRASTRUCTURE"] is True
    assert not any("/skills/bedrock-migration-assessment/" in row["path"] for row in value["audit"])
    denied, denied_value, _, denied_hashes = invoke(project, bma=BMA)
    assert denied.returncode == 2 and denied_value["reason"] == "bma_preflight_not_authorized_for_non_candidate"
    assert not any("/skills/bedrock-migration-assessment/" in row["path"] for row in denied_value["audit"])
    assert hashes["before"] == hashes["after"] and denied_hashes["before"] == denied_hashes["after"]


def test_copied_layout_preserves_module_and_second_pass_contract(tmp_path: Path) -> None:
    skills = tmp_path / "skills"; gcp = skills / "gcp-to-aws"; bma = skills / "bedrock-migration-assessment"
    shutil.copytree(GCP, gcp); shutil.copytree(BMA, bma)
    project = tmp_path / "project"; (project / "nested/modules/m").mkdir(parents=True); (project / "app.py").write_text("import openai\n")
    first, value, _, _ = invoke(project, gcp=gcp)
    assert first.returncode == 0 and value["inventory"]["module_directories"] == ["nested/modules/m/"]
    second, value, argv, hashes = invoke(project, bma=bma, gcp=gcp)
    assert second.returncode == 0 and value["closure_entries"] == 66
    assert argv[-1] == str(bma) and hashes["before"] == hashes["after"]


@pytest.mark.parametrize("copied_layout", [False, True], ids=["plugin-layout", "copied-layout"])
def test_candidate_rejects_closure_valid_non_sibling_before_closure_access(
    tmp_path: Path, copied_layout: bool,
) -> None:
    if copied_layout:
        skills = tmp_path / "installed/skills"
        gcp = skills / "gcp-to-aws"
        expected_bma = skills / "bedrock-migration-assessment"
        shutil.copytree(GCP, gcp)
        shutil.copytree(BMA, expected_bma)
    else:
        gcp = GCP
        expected_bma = BMA
    alternate = tmp_path / "alternate/bedrock-migration-assessment"
    shutil.copytree(BMA, alternate)
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    (project / "app.py").write_text("import openai\n")

    completed, value, argv, hashes = invoke(project, bma=alternate, gcp=gcp, sandbox=True)

    assert completed.returncode == 2
    assert value["reason"] == "BEDROCK_MIGRATION_ASSESSMENT_SIBLING_MISSING"
    assert argv[-2:] == ["--bma-base", str(alternate)]
    assert not any(row["path"].startswith(str(alternate.resolve())) for row in value["audit"])
    assert not any(row["path"].startswith(str(expected_bma.resolve())) for row in value["audit"])
    assert value["mutation_count"] == 0
    assert hashes["before"] == hashes["after"]


def test_documented_bootstrap_hashes_match_generated_manifest() -> None:
    expected = sha(MANIFEST)
    for path in (GCP / "SKILL.md", GCP / "references/phases/discover/discover.md"):
        documented = [
            token.strip("`.,") for token in path.read_text().split()
            if token.strip("`.,") == expected
        ]
        assert documented == [expected], path


def test_bootstrap_outer_hash_and_payload_negatives(tmp_path: Path) -> None:
    project = tmp_path / "project"; project.mkdir()
    for expected in ("bad", "0" * 64):
        completed, value, _, hashes = invoke(project, expected_manifest_sha=expected, sandbox=True)
        assert completed.returncode == 2
        assert value["reason"] in {"bootstrap_manifest_hash_malformed", "bootstrap_manifest_hash_mismatch"}
        assert not any(row["op"] == "walk" for row in value["audit"])
        assert hashes["before"] == hashes["after"]

    gcp = tmp_path / "gcp-to-aws"; shutil.copytree(GCP, gcp)
    (gcp / "references/runtime/bma-input-patterns.json").write_text("{}\n")
    completed, value, _, hashes = invoke(project, gcp=gcp, sandbox=True)
    assert completed.returncode == 2 and value["reason"] == "bootstrap_pattern_hash_mismatch"
    assert not any(row["op"] == "walk" for row in value["audit"])
    assert hashes["before"] == hashes["after"]


def _closure_self_hash(value: dict) -> str:
    unsigned = dict(value); unsigned.pop("self_hash", None)
    return hashlib.sha256(json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@pytest.mark.parametrize("mutation", ["destination_root", "entrypoints", "logical_id", "origin", "owner", "parity", "edge", "exclusions"])
def test_complete_closure_contract_negatives(tmp_path: Path, mutation: str) -> None:
    bma = tmp_path / mutation / "bedrock-migration-assessment"; shutil.copytree(BMA, bma)
    path = bma / "references/runtime/closure.json"
    value = json.loads(path.read_text())
    if mutation == "destination_root": value["destination_root"] = "skills/wrong"
    elif mutation == "entrypoints": value["entrypoints"] = value["entrypoints"][:-1]
    elif mutation == "logical_id": value["entries"][1]["logical_id"] = value["entries"][0]["logical_id"]
    elif mutation == "origin": value["entries"][0]["origin"] = "unknown"
    elif mutation == "owner": value["entries"][0]["canonical_owner"] = "wrong"
    elif mutation == "parity": value["entries"][0]["parity"] = "byte-identical"
    elif mutation == "edge": value["entries"][0]["runtime_references"] = []
    elif mutation == "exclusions": value["runtime_exclusions"] = []
    value["self_hash"] = _closure_self_hash(value)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    completed = subprocess.run([sys.executable, "-B", str(bma / "scripts/bma-route-classifier.py"), "preflight", "--bma-base", str(bma)], text=True, capture_output=True)
    assert completed.returncode == 2
    assert json.loads(completed.stdout)["reason"] == "BMA_STANDALONE_CLOSURE_INVALID"


def test_closure_member_missing_changed_and_symlink_fail(tmp_path: Path) -> None:
    for mutation in ("missing", "changed", "symlink"):
        bma = tmp_path / mutation / "bedrock-migration-assessment"; shutil.copytree(BMA, bma)
        member = bma / "references/runtime/plugin.json"
        if mutation == "missing": member.unlink()
        elif mutation == "changed": member.write_text("{}\n")
        else:
            original = tmp_path / mutation / "plugin-real.json"; shutil.copyfile(member, original); member.unlink(); member.symlink_to(original)
        completed = subprocess.run([sys.executable, "-B", str(bma / "scripts/bma-route-classifier.py"), "preflight", "--bma-base", str(bma)], text=True, capture_output=True)
        assert completed.returncode == 2
        assert json.loads(completed.stdout)["reason"] == "BMA_STANDALONE_CLOSURE_INVALID"
