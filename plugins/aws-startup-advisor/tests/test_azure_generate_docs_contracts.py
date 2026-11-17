"""Guard: azure-to-aws Generate writes a database migration runbook keyed to `data.db_cutover`.

Q-D2 is confirmed at the Decision gate (estimate-assemble.md Step 3b) and Generate refuses
to start with it unconfirmed. These tests pin the consumer: the MIGRATION_GUIDE section that
holds one branch per answer, the explicit "not covered" note for other engines, the rule that
replication is operator-run, and the wording that Generate emits dry-run-by-default migration scripts.
"""
from __future__ import annotations

from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILL = PLUGIN_ROOT / "skills" / "azure-to-aws"
DOCS = SKILL / "references" / "phases" / "generate" / "generate-artifacts-docs.md"
GENERATE = SKILL / "references" / "phases" / "generate" / "generate.md"
SKILL_MD = SKILL / "SKILL.md"
ESTIMATE = SKILL / "references" / "phases" / "estimate" / "estimate.md"
ESTIMATE_ASSEMBLE = SKILL / "references" / "phases" / "estimate" / "estimate-assemble.md"
DECISION_CORE = SKILL / "references" / "shared" / "report-decision-core.md"


def _read(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def test_database_migration_subsection_has_both_branches_keyed_to_db_cutover() -> None:
    text = _read(DOCS)
    assert "Database migration" in text
    assert "`data.db_cutover`" in text
    assert "### Branch: `dump_restore`" in text
    assert "### Branch: `dms`" in text
    # The branch is chosen from the confirmed answer, never re-derived from size.
    assert "Do not re-derive the answer from database size" in text


def test_dump_restore_branch_covers_freeze_verify_and_rollback() -> None:
    text = _read(DOCS)
    branch = text.split("### Branch: `dump_restore`", 1)[1].split("### Branch: `dms`", 1)[0]
    for needle in ("Freeze writes", "Dump.", "Restore.", "Verify.", "Rollback.", "proportional to database size"):
        assert needle in branch, needle
    assert "row counts" in branch and "checksums" in branch and "invariants" in branch


def test_dms_branch_lists_source_prerequisites_and_is_operator_run() -> None:
    text = _read(DOCS)
    branch = text.split("### Branch: `dms`", 1)[1].split("### Not covered by this runbook", 1)[0]
    for needle in (
        "`wal_level`",
        "`max_replication_slots`",
        "`max_wal_senders`",
        "`REPLICATION`",
        "binary logging",
        "`binlog_expire_logs_seconds`",
        "full load plus CDC",
        "CDC latency",
    ):
        assert needle in branch, needle
    # No tested replication workflow exists; the guide must say the operator runs it.
    assert "run by the operator in AWS DMS" in text
    assert "no tested replication workflow" in branch


def test_other_engines_get_an_explicit_not_covered_note() -> None:
    text = _read(DOCS)
    assert "### Not covered by this runbook" in text
    note = text.split("### Not covered by this runbook", 1)[1].split("## Step 2", 1)[0]
    for engine in ("Azure SQL Database", "Cosmos DB", "SQL Managed Instance"):
        assert engine in note, engine
    assert "is not covered by this runbook" in note


def test_database_runbook_has_no_replication_script_or_untested_flag() -> None:
    text = _read(DOCS)
    section = text.split("## Step 1a:", 1)[1].split("## Step 1b:", 1)[0]
    assert "runs no database command" in section
    assert "contains no replication step" in section
    assert "--final-sync" not in section


def test_generate_skill_text_matches_the_scripts_that_are_now_emitted() -> None:
    skill = _read(SKILL_MD)
    generate = _read(GENERATE)
    assert "Terraform, migration scripts (dry-run by default), docs, and the report are produced" in skill
    assert "no migration scripts yet" not in skill and "no migration scripts yet" not in generate
    assert "Emit the Terraform, the scripts, the docs, and the report. Scripts are written, never run." in generate
    assert "phases/generate/generate-artifacts-scripts.md" in generate
    # Old promise-without-scripts wording must not come back.
    assert "Terraform, docs, and the report are produced only after" not in skill
    assert "Emit the Terraform, the docs, and the report (no migration scripts yet)" not in generate
    # The decision gate and the decision report speak for the same Generate phase, so they
    # must name what Generate really produces: Terraform, migration scripts, the guide, the report.
    gate = _read(ESTIMATE_ASSEMBLE)
    assert (
        "[C] Generate the migration artifacts — Terraform, migration scripts (operator-run, dry-run by default), "
        "the migration guide, and the report"
    ) in gate
    assert "[C] Generate the migration artifacts — Terraform, the migration guide, and the report" not in gate
    estimate = _read(ESTIMATE)
    assert estimate.count("generate the Terraform, migration scripts, and the migration guide") == 2
    assert "generate the Terraform and the migration guide" not in estimate
    core = _read(DECISION_CORE)
    assert "generate the Terraform, migration scripts, and the migration guide" in core
    assert "migration scripts you run yourself and that are dry-run by default" in core
    assert "generate the Terraform and the migration guide" not in core


def test_generate_postconditions_still_require_a_verification_section() -> None:
    generate = _read(GENERATE)
    assert "MIGRATION_GUIDE.md has Prerequisites and Verification sections" in generate
    docs = _read(DOCS)
    assert "**Verification**" in docs and "Prerequisites" in docs
