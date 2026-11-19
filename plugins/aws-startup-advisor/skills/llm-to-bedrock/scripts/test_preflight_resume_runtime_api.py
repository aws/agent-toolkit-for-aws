"""PR 585 review round 2, finding 3 — B4's saved-API reuse must check identity first.

The old recovery guidance read the previous design's saved `resolved_runtime_api` before C0
compared `assess_design_sha256`, so a cached `messages` answer could send a new GPT row to the
Anthropic endpoint and a stale `responses` answer could override a Chat Completions source.
`resume_runtime_api` reuses the saved answer only when it exists AND the saved design sha256
and (source, target) row identity still match; anything else forces re-resolution BEFORE the
probes.
"""
import hashlib
import json

import preflight_bedrock as p

DESIGN_SHA = "a" * 64
GPT_ROWS = [{"source_model_id": "gpt-5.6-sol", "aws_model_id": "us.openai.gpt-5.6-sol",
             "migration_path": "runtime_openai_cris"}]
CLAUDE_ROWS = [{"source_model_id": "claude-sonnet-4-5", "aws_model_id": "global.anthropic.claude-sonnet-5",
                "migration_path": "runtime_messages"}]


def _saved(api, sha=DESIGN_SHA, rows=GPT_ROWS):
    return {"resolved_runtime_api": api, "assess_design_sha256": sha,
            "target_models": [{"source_model": r["source_model_id"], "aws_model_id": r["aws_model_id"],
                               "use_case": "chat"} for r in rows]}


def test_unchanged_identity_reuses_the_saved_answer_without_asking():
    verdict = p.resume_runtime_api(_saved("chat_completions"), DESIGN_SHA, GPT_ROWS)
    assert verdict == {"ok": True, "reason": "saved_identity_match", "resolved_runtime_api": "chat_completions",
                       "detail": "Saved design, source and target identity match; reuse without asking."}


def test_cached_messages_answer_is_not_reused_for_a_new_gpt_row():
    # The reviewer's first case: the previous design was a Claude Messages plan; the design
    # now holds a GPT row with no API. The saved `messages` must not reach the GPT probe.
    saved = _saved("messages", rows=CLAUDE_ROWS)
    verdict = p.resume_runtime_api(saved, "b" * 64, GPT_ROWS)
    assert verdict["ok"] is False and verdict["reason"] == "saved_identity_mismatch"
    assert "resolved_runtime_api" not in verdict
    assert any(m.startswith("assess_design_sha256") for m in verdict["mismatches"])
    assert any(m.startswith("target_models") for m in verdict["mismatches"])


def test_stale_responses_answer_is_not_reused_when_only_the_design_changed():
    # The reviewer's second case: same target id, but the design (and so the source's API)
    # changed — a stale `responses` must not override a Chat Completions source.
    verdict = p.resume_runtime_api(_saved("responses"), "c" * 64, GPT_ROWS)
    assert verdict["ok"] is False and verdict["reason"] == "saved_identity_mismatch"
    assert verdict["mismatches"] == [f"assess_design_sha256 saved={DESIGN_SHA!r} current={'c' * 64!r}"]


def test_changed_target_id_alone_forces_re_resolution():
    terra_rows = [{**GPT_ROWS[0], "aws_model_id": "us.openai.gpt-5.6-terra"}]
    verdict = p.resume_runtime_api(_saved("responses"), DESIGN_SHA, terra_rows)
    assert verdict["ok"] is False and len(verdict["mismatches"]) == 1
    assert verdict["mismatches"][0].startswith("target_models ")


def test_changed_source_model_alone_forces_re_resolution():
    rows = [{**GPT_ROWS[0], "source_model_id": "gpt-5.5"}]
    assert p.resume_runtime_api(_saved("responses"), DESIGN_SHA, rows)["reason"] == "saved_identity_mismatch"


def test_missing_context_or_missing_field_never_reuses():
    assert p.resume_runtime_api(None, DESIGN_SHA, GPT_ROWS)["reason"] == "no_saved_context"
    assert p.resume_runtime_api({}, DESIGN_SHA, GPT_ROWS)["reason"] == "no_saved_context"
    saved = _saved("responses")
    del saved["resolved_runtime_api"]
    assert p.resume_runtime_api(saved, DESIGN_SHA, GPT_ROWS)["reason"] == "no_saved_runtime_api"


def test_design_row_identity_accepts_both_source_key_spellings():
    assert p.design_row_identity(GPT_ROWS) == p.design_row_identity(
        [{"source_model": "gpt-5.6-sol", "aws_model_id": "us.openai.gpt-5.6-sol"}])


def _write_design(tmp_path, rows):
    design = tmp_path / "aws-design-ai.json"
    design.write_text(json.dumps({"ai_architecture": {"bedrock_models": rows}}))
    return design, hashlib.sha256(design.read_bytes()).hexdigest()


def test_cli_match_exits_zero_and_prints_the_saved_api(tmp_path, capsys):
    design, sha = _write_design(tmp_path, GPT_ROWS)
    ctx = tmp_path / "run-context.json"
    ctx.write_text(json.dumps(_saved("chat_completions", sha=sha)))
    rc = p.main(["--resume-runtime-api", str(ctx), "--design", str(design)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["ok"] is True and out["resolved_runtime_api"] == "chat_completions"


def test_cli_identity_mismatch_exits_one_before_any_probe(tmp_path, capsys, monkeypatch):
    import boto3
    monkeypatch.setattr(boto3, "client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("probed")))
    design, _ = _write_design(tmp_path, GPT_ROWS)
    ctx = tmp_path / "run-context.json"
    ctx.write_text(json.dumps(_saved("messages", sha="0" * 64, rows=CLAUDE_ROWS)))
    rc = p.main(["--resume-runtime-api", str(ctx), "--design", str(design)])
    out = json.loads(capsys.readouterr().out)
    assert rc == 1 and out["reason"] == "saved_identity_mismatch"
    assert "resolved_runtime_api" not in out


def test_cli_without_a_saved_context_exits_one(tmp_path, capsys):
    design, _ = _write_design(tmp_path, GPT_ROWS)
    rc = p.main(["--resume-runtime-api", str(tmp_path / "missing.json"), "--design", str(design)])
    assert rc == 1 and json.loads(capsys.readouterr().out)["reason"] == "no_saved_context"
