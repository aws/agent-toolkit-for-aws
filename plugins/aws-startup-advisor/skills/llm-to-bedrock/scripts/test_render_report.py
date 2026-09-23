# test_render_report.py
# render_report.py is a sibling in this scripts/ dir — import directly.
import render_report as rr


def real_payload():
    """The shape workflow-rewrite.js actually returns: `report` is prose."""
    return {
        "control": "ok",
        "rewrite": {
            "branch_name": "bedrock-migration",
            "files_changed": ["app.py", "pyproject.toml"],
            "notes": "5 tests generated, 5/5 passing in clean checkout.",
        },
        "report": "Report written to /repo/MIGRATION_REPORT_2026-06-10.md. Overall status: ready-to-merge.",
        "evalRes": {"pass_rate": 0.89, "total_cases": 9, "failures": 1, "notes": ""},
        "repo": "/nonexistent-repo",
        "reportDateSuffix": "2026-06-10",
    }


def test_summarize_handles_prose_report():
    out = rr.summarize(real_payload())
    assert "bedrock-migration" in out
    assert "89%" in out
    assert "2 files" in out
    assert "5/5 passing" in out


def test_summarize_zero_golden_cases_not_rendered_as_100_percent():
    p = real_payload()
    p["evalRes"] = {"pass_rate": 1.0, "total_cases": 0, "failures": 0,
                    "notes": "no_golden_cases: true\nreason: empty dataset"}
    out = rr.summarize(p)
    assert "100%" not in out
    assert "N/A" in out


def test_summarize_degenerate_payload_does_not_crash():
    out = rr.summarize({})
    assert "AI Migration Complete!" in out
    assert "(none)" in out


def test_summarize_report_as_string_does_not_crash():
    # regression: the original implementation called .get() on the prose string
    p = real_payload()
    p["report"] = "just prose"
    rr.summarize(p)


def test_summarize_omits_test_line_when_notes_unparseable():
    p = real_payload()
    p["rewrite"]["notes"] = "no test info here"
    out = rr.summarize(p)
    assert "Tests:" not in out


def test_find_report_path_prefers_suffix_match(tmp_path):
    (tmp_path / "MIGRATION_REPORT_2026-06-10.md").write_text("x")
    (tmp_path / "MIGRATION_REPORT_2026-01-01.md").write_text("y")
    p = {"repo": str(tmp_path), "reportDateSuffix": "2026-06-10"}
    assert rr.find_report_path(p).endswith("MIGRATION_REPORT_2026-06-10.md")


def test_find_report_path_falls_back_to_latest_glob(tmp_path):
    (tmp_path / "MIGRATION_REPORT_2026-01-01.md").write_text("y")
    p = {"repo": str(tmp_path), "reportDateSuffix": "2026-06-10"}
    assert rr.find_report_path(p).endswith("MIGRATION_REPORT_2026-01-01.md")


def test_find_report_path_no_repo_returns_none():
    assert rr.find_report_path({}) is None


def test_main_rejects_malformed_json(tmp_path, capsys):
    bad = tmp_path / "payload.json"
    bad.write_text("{not json")
    rc = rr.main([str(bad)])
    assert rc == 1
    assert "cannot read payload" in capsys.readouterr().err


# ---------- --phase-results mode ----------

import json


def _write_phase_results(tmp_path, rewrite=None, eval_res=None, deltas=None):
    d = tmp_path / "phase-results"
    d.mkdir()
    if rewrite is not None:
        (d / "rewrite.json").write_text(json.dumps(rewrite))
    if eval_res is not None:
        (d / "eval.json").write_text(json.dumps(eval_res))
    if deltas is not None:
        (d / "delta-decisions.json").write_text(json.dumps(deltas))
    return str(d)


def test_phase_results_mode_happy_path(tmp_path, capsys):
    d = _write_phase_results(
        tmp_path,
        rewrite={"branch_name": "bedrock-migration", "files_changed": ["a.py"],
                 "notes": "3 tests generated, 3/3 passing"},
        eval_res={"pass_rate": 0.9, "total_cases": 10, "failures": 1, "notes": ""},
        deltas=[{"delta_type": "x", "location": "a.py:1",
                 "resolution_chosen": "range_narrowed_1", "source": "user_question"}],
    )
    rc = rr.main(["--phase-results", d, "--repo", str(tmp_path),
                  "--results-dir", str(tmp_path / "out")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "bedrock-migration" in out
    assert "90%" in out
    assert "3/3 passing" in out
    assert "decisions applied: 1" in out


def test_phase_results_missing_eval_degrades(tmp_path, capsys):
    d = _write_phase_results(tmp_path, rewrite={"branch_name": "b", "files_changed": []})
    rc = rr.main(["--phase-results", d, "--repo", str(tmp_path),
                  "--results-dir", str(tmp_path / "out")])
    assert rc == 0
    assert "(unavailable)" in capsys.readouterr().out


def test_phase_results_control_state_file_not_treated_as_payload(tmp_path, capsys):
    d = _write_phase_results(
        tmp_path,
        rewrite={"branch_name": "b", "files_changed": []},
        eval_res={"partial": {"completed": 3, "total": 9, "reason": "throttled"}},
    )
    rc = rr.main(["--phase-results", d, "--repo", str(tmp_path),
                  "--results-dir", str(tmp_path / "out")])
    assert rc == 0
    assert "(unavailable)" in capsys.readouterr().out  # partial != payload


def test_partial_coverage_note_rendered(tmp_path, capsys):
    d = _write_phase_results(
        tmp_path,
        rewrite={"branch_name": "b", "files_changed": []},
        eval_res={"pass_rate": 0.8, "total_cases": 4, "failures": 1,
                  "notes": "partial_coverage: 4/9 cases (throttled)"},
    )
    rr.main(["--phase-results", d, "--repo", str(tmp_path),
             "--results-dir", str(tmp_path / "out")])
    assert "partial coverage 4/9" in capsys.readouterr().out


def test_both_modes_is_argparse_error(tmp_path):
    import pytest
    d = _write_phase_results(tmp_path, rewrite={})
    payload = tmp_path / "p.json"
    payload.write_text("{}")
    with pytest.raises(SystemExit):
        rr.main([str(payload), "--phase-results", d, "--repo", str(tmp_path)])


def test_neither_mode_is_argparse_error():
    import pytest
    with pytest.raises(SystemExit):
        rr.main([])


def test_results_dir_still_means_copy_destination(tmp_path, capsys):
    (tmp_path / "MIGRATION_REPORT_2026-06-10.md").write_text("report body")
    d = _write_phase_results(tmp_path, rewrite={"branch_name": "b", "files_changed": []},
                             eval_res={"pass_rate": 1.0, "total_cases": 1, "failures": 0, "notes": ""})
    dest = tmp_path / "copies"
    rc = rr.main(["--phase-results", d, "--repo", str(tmp_path),
                  "--date-suffix", "2026-06-10", "--results-dir", str(dest)])
    assert rc == 0
    assert (dest / "MIGRATION_REPORT_2026-06-10.md").exists()
