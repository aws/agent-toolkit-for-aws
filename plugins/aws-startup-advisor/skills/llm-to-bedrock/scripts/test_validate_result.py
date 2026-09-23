# test_validate_result.py
# Contract tests per design §8: golden payloads from the agent docs must
# validate; every documented-mandatory field is enforced; control states are
# per-schema; the run-context comparison is field-wise with redaction.
import copy
import json
import pathlib

import pytest

import validate_result as vr

SCHEMAS = pathlib.Path(__file__).parent / "schemas"


def schema(name):
    return json.loads((SCHEMAS / f"{name}.json").read_text())


def validate(name, data):
    return vr.jsonschema.Draft202012Validator(schema(name)).is_valid(data)


# ---------- golden payloads (verbatim shapes from the agent docs) ----------

GOLDEN_ANALYSIS = {
    "summary": "LangChain + langchain-openai detected. 2 files need modification.",
    "source_code_path": "/repo", "migration_plan_path": "/repo/.migration/0610-1200",
    "app_language": "Python", "ai_framework": "LangChain",
    "ai_framework_version": "langchain==0.1.14", "source_provider": "openai",
    "source_models": ["gpt-4o"],
    "target_models": ["gpt-4o -> us.anthropic.claude-sonnet-4-6"],
    "same_model_family": False, "bedrock_provider_available": True,
    "prompt_locations": ["app.py:42 : SYSTEM_PROMPT constant"],
    "prompt_patterns": "hardcoded",
    "special_patterns": {"streaming": True, "function_calling": False,
                         "embeddings": False, "vision": False},
    "code_change_sites": 2,
    "files_to_modify": ["app.py: replace ChatOpenAI with ChatBedrockConverse"],
    "dependencies_to_replace": ["langchain-openai -> langchain-aws"],
    "log_files_found": "none", "errors": "none", "behavior_deltas": [],
    "source_baseline_available": False,
}

GOLDEN_INGESTION = {
    "summary": "Built golden dataset with 9 cases from the code template.",
    "golden_dataset_path": "/repo/.saws-migrate/golden-dataset/prompts.jsonl",
    "prompt_template_path": "/repo/.saws-migrate/golden-dataset/templates/prompt_template.txt",
    "total_golden_cases": 9, "golden_from_logs": 0, "golden_from_user": 0,
    "golden_from_code_confirmed": 9, "vision_test_images": 0, "log_format": "none",
    "coverage_level": "code-confirmed", "use_case_type": "text-only",
    "gaps": ["No production traffic data"], "pii_detected": False,
    "pii_action": "not-applicable", "errors": "none",
}

GOLDEN_INGESTION_ZERO = {**GOLDEN_INGESTION,
    "summary": "No LLM call sites — zero golden cases.",
    "golden_dataset_path": "", "prompt_template_path": "", "total_golden_cases": 0,
    "golden_from_code_confirmed": 0, "coverage_level": "none",
    "use_case_type": "unknown",
    "gaps": ["No LLM call sites in source"]}

GOLDEN_EVAL = {
    "eval_report_path": "/repo/.saws-migrate/eval-results/",
    "pass_rate": 0.89, "total_cases": 9, "failures": 1,
    "notes": "live_source_baseline_used_model: \n1 prompt needs manual review.",
    "live_source_baseline": True, "judge_model": "claude-opus-4-8",
    "source_baseline_quality": "good",
}

GOLDEN_EVAL_ZERO = {**GOLDEN_EVAL, "pass_rate": 1.0, "total_cases": 0,
    "failures": 0, "notes": "no_golden_cases: true",
    "live_source_baseline": False, "source_baseline_quality": "unknown"}

SHA = "a" * 40

GOLDEN_REWRITE = {
    "branch_name": "bedrock-migration",
    "files_changed": ["app.py", "pyproject.toml"],
    "dependencies_updated": ["langchain-openai -> langchain-aws"],
    "notes": "5 tests generated, 5/5 passing in clean checkout.",
    "behavior_delta_decisions": [
        {"delta_type": "temperature-range-mismatch", "location": "app.py:95",
         "resolution_chosen": "range_narrowed_1", "source": "user_question"}
    ],
    "baseline_parent_sha": SHA, "branch_tip_sha": "b" * 40,
}

GOLDEN_DELTA_DECISIONS = [
    {"delta_type": "temperature-range-mismatch", "location": "app.py:95",
     "resolution_chosen": "range_narrowed_1", "source": "user_question"},
]


@pytest.mark.parametrize("name,payload", [
    ("analysis", GOLDEN_ANALYSIS),
    ("ingestion", GOLDEN_INGESTION),
    ("ingestion", GOLDEN_INGESTION_ZERO),
    ("eval", GOLDEN_EVAL),
    ("eval", GOLDEN_EVAL_ZERO),
    ("rewrite", GOLDEN_REWRITE),
    ("delta-decisions", GOLDEN_DELTA_DECISIONS),
    ("delta-decisions", []),
])
def test_golden_payloads_validate(name, payload):
    assert validate(name, payload), f"golden {name} payload must validate"


# ---------- required enforcement (parameterized over each schema's required) ----------

def required_fields(name):
    s = schema(name)
    branch = s["oneOf"][0] if "oneOf" in s else s
    return branch["required"]

GOLDENS = {"analysis": GOLDEN_ANALYSIS, "ingestion": GOLDEN_INGESTION,
           "eval": GOLDEN_EVAL, "rewrite": GOLDEN_REWRITE}


@pytest.mark.parametrize("name", list(GOLDENS))
def test_empty_object_fails(name):
    assert not validate(name, {})


@pytest.mark.parametrize("name,field", [
    (name, field) for name in GOLDENS for field in required_fields(name)
])
def test_each_required_field_enforced(name, field):
    # Regression for the dropped-`required` bug AND the loose-JS gaps:
    # evaluator missing live_source_baseline/judge_model/source_baseline_quality,
    # analyzer missing any typed field, must all be rejected.
    payload = copy.deepcopy(GOLDENS[name])
    del payload[field]
    assert not validate(name, payload), f"{name} without {field} must fail"


def test_special_patterns_requires_all_four_booleans():
    payload = copy.deepcopy(GOLDEN_ANALYSIS)
    del payload["special_patterns"]["vision"]
    assert not validate("analysis", payload)


# ---------- control states (per schema) ----------

@pytest.mark.parametrize("name,reason", [
    ("analysis", "model_access"), ("analysis", "model_unresolvable"),
    ("analysis", "assess_output_missing"),
    ("eval", "model_access"), ("eval", "source_key_auth"), ("eval", "model_unresolvable"),
    ("rewrite", "model_access"), ("rewrite", "source_key_auth"), ("rewrite", "model_unresolvable"),
])
def test_blocked_reasons_in_own_schema(name, reason):
    assert validate(name, {"blocked": {"reason": reason, "detail": "x"}})


@pytest.mark.parametrize("name,reason", [
    ("eval", "assess_output_missing"),   # analyzer-only reason
    ("rewrite", "assess_output_missing"),
    ("analysis", "source_key_auth"),     # eval/rewrite-only reason
])
def test_blocked_reason_from_other_schema_fails(name, reason):
    assert not validate(name, {"blocked": {"reason": reason, "detail": "x"}})


def test_ingestion_has_no_blocked_branch():
    assert not validate("ingestion", {"blocked": {"reason": "model_access", "detail": "x"}})


def test_blocked_without_detail_fails():
    assert not validate("analysis", {"blocked": {"reason": "model_access"}})


def test_payload_mixed_with_blocked_fails():
    payload = {**GOLDEN_EVAL, "blocked": {"reason": "model_access", "detail": "x"}}
    assert not validate("eval", payload)


def test_partial_only_in_eval():
    partial = {"partial": {"completed": 7, "total": 20, "reason": "throttled"}}
    assert validate("eval", partial)
    assert not validate("analysis", partial)
    assert not validate("rewrite", partial)
    assert not validate("ingestion", partial)


def test_rewrite_missing_sha_fields_fails():
    for field in ("baseline_parent_sha", "branch_tip_sha"):
        payload = copy.deepcopy(GOLDEN_REWRITE)
        del payload[field]
        assert not validate("rewrite", payload)


def test_delta_decisions_entry_missing_resolution_fails():
    bad = [{"delta_type": "x", "location": "a.py:1", "source": "user_question"}]
    assert not validate("delta-decisions", bad)
    assert not validate("delta-decisions", {"not": "an array"})


# ---------- CLI behavior ----------

def write(tmp_path, name, data):
    f = tmp_path / name
    f.write_text(json.dumps(data))
    return str(f)


def test_cli_control_lines(tmp_path, capsys):
    assert vr.main(["--schema", "eval", write(tmp_path, "ok.json", GOLDEN_EVAL)]) == 0
    assert "RESULT=valid CONTROL=ok" in capsys.readouterr().out

    blocked = {"blocked": {"reason": "model_access", "detail": "enable in console"}}
    assert vr.main(["--schema", "eval", write(tmp_path, "b.json", blocked)]) == 0
    assert "CONTROL=blocked REASON=model_access" in capsys.readouterr().out

    partial = {"partial": {"completed": 7, "total": 20, "reason": "throttled"}}
    assert vr.main(["--schema", "eval", write(tmp_path, "p.json", partial)]) == 0
    assert "CONTROL=partial COMPLETED=7 TOTAL=20" in capsys.readouterr().out


def test_cli_invalid_reports_field_paths(tmp_path, capsys):
    payload = copy.deepcopy(GOLDEN_EVAL)
    del payload["judge_model"]
    assert vr.main(["--schema", "eval", write(tmp_path, "bad.json", payload)]) == 1
    out = capsys.readouterr().out
    assert "RESULT=invalid" in out
    assert "judge_model" in out


def test_cli_missing_file_exits_2(capsys):
    assert vr.main(["--schema", "eval", "/nonexistent/x.json"]) == 2


def test_cli_delta_decisions_always_control_ok(tmp_path, capsys):
    assert vr.main(["--schema", "delta-decisions", write(tmp_path, "d.json", [])]) == 0
    assert "CONTROL=ok" in capsys.readouterr().out


# ---------- run-context comparison ----------

RUN_CONTEXT = {
    "repo_root": "/repo", "migration_dir": "/repo/.migration/0610-1200",
    "region": "us-east-1", "aws_profile": "", "aws_account": "123456789012",
    "repo_head_sha": SHA, "repo_branch": "main", "repo_dirty_sha256": "",
    "target_models": [{"source_model": "gpt-4o",
                       "aws_model_id": "us.anthropic.claude-sonnet-4-6",
                       "use_case": "primary"}],
    "resolved_model_overrides": {},
    "source_provider": "openai", "source_baseline_available": True,
    "source_key_sha256": "c" * 64,
    "log_files": [{"path": "logs/traces.jsonl", "sha256": "d" * 64}],
    "max_golden_cases": 200, "assess_design_sha256": "e" * 64,
    "report_date_suffix": "2026-06-10",
    "schema_version": 1, "plugin_version": "1.0.1",
}


def test_run_context_identical_matches(tmp_path, capsys):
    s = write(tmp_path, "saved.json", RUN_CONTEXT)
    c = write(tmp_path, "current.json", RUN_CONTEXT)
    assert vr.main(["--check-run-context", s, "--current", c]) == 0
    assert "RUN_CONTEXT=match" in capsys.readouterr().out


MUTATIONS = {
    "region": "eu-west-1", "aws_profile": "prod", "aws_account": "999999999999",
    "migration_dir": "/repo/.migration/0611-0900", "repo_head_sha": "f" * 40,
    "repo_branch": "develop", "repo_dirty_sha256": "1" * 64,
    "source_provider": "google", "source_key_sha256": "0" * 64,
    "max_golden_cases": 50, "assess_design_sha256": "2" * 64,
    "schema_version": 2, "plugin_version": "1.0.2",
}


@pytest.mark.parametrize("field", list(MUTATIONS))
def test_single_field_mismatch_named(tmp_path, capsys, field):
    cur = copy.deepcopy(RUN_CONTEXT)
    cur[field] = MUTATIONS[field]
    s = write(tmp_path, "saved.json", RUN_CONTEXT)
    c = write(tmp_path, "current.json", cur)
    assert vr.main(["--check-run-context", s, "--current", c]) == 1
    out = capsys.readouterr().out
    assert "RUN_CONTEXT=mismatch" in out
    assert f"MISMATCH $.{field}" in out


def test_nested_mismatch_reported(tmp_path, capsys):
    cur = copy.deepcopy(RUN_CONTEXT)
    cur["log_files"][0]["sha256"] = "9" * 64
    s = write(tmp_path, "s.json", RUN_CONTEXT)
    c = write(tmp_path, "c.json", cur)
    assert vr.main(["--check-run-context", s, "--current", c]) == 1
    assert "log_files" in capsys.readouterr().out


def test_key_hash_mismatch_never_prints_hashes(tmp_path, capsys):
    cur = copy.deepcopy(RUN_CONTEXT)
    cur["source_key_sha256"] = "0" * 64
    s = write(tmp_path, "s.json", RUN_CONTEXT)
    c = write(tmp_path, "c.json", cur)
    vr.main(["--check-run-context", s, "--current", c])
    out = capsys.readouterr().out
    assert "MISMATCH $.source_key_sha256 differs" in out
    assert "c" * 64 not in out and "0" * 64 not in out


def test_report_date_suffix_excluded_from_comparison(tmp_path, capsys):
    cur = copy.deepcopy(RUN_CONTEXT)
    cur["report_date_suffix"] = "2026-06-11"
    s = write(tmp_path, "s.json", RUN_CONTEXT)
    c = write(tmp_path, "c.json", cur)
    assert vr.main(["--check-run-context", s, "--current", c]) == 0


def test_unknown_extra_key_is_mismatch(tmp_path, capsys):
    cur = copy.deepcopy(RUN_CONTEXT)
    cur["future_field"] = "surprise"
    s = write(tmp_path, "s.json", RUN_CONTEXT)
    c = write(tmp_path, "c.json", cur)
    assert vr.main(["--check-run-context", s, "--current", c]) == 1
    assert "future_field" in capsys.readouterr().out


def test_run_context_missing_file_exits_2(tmp_path, capsys):
    c = write(tmp_path, "c.json", RUN_CONTEXT)
    assert vr.main(["--check-run-context", "/nonexistent.json", "--current", c]) == 2


def test_analysis_valid_without_optional_fields():
    assert validate("analysis", GOLDEN_ANALYSIS)


def test_empty_object_mismatch_detected(tmp_path, capsys):
    """Empty dict in saved vs absent key in current must be a mismatch."""
    saved = copy.deepcopy(RUN_CONTEXT)
    saved["resolved_model_overrides"] = {}
    cur = copy.deepcopy(RUN_CONTEXT)
    cur.pop("resolved_model_overrides", None)
    s = write(tmp_path, "s.json", saved)
    c = write(tmp_path, "c.json", cur)
    assert vr.main(["--check-run-context", s, "--current", c]) == 1
    assert "resolved_model_overrides" in capsys.readouterr().out


def test_empty_array_mismatch_detected(tmp_path, capsys):
    """Empty list in saved vs absent key in current must be a mismatch."""
    saved = copy.deepcopy(RUN_CONTEXT)
    saved["log_files"] = []
    cur = copy.deepcopy(RUN_CONTEXT)
    cur.pop("log_files", None)
    s = write(tmp_path, "s.json", saved)
    c = write(tmp_path, "c.json", cur)
    assert vr.main(["--check-run-context", s, "--current", c]) == 1
    assert "log_files" in capsys.readouterr().out
