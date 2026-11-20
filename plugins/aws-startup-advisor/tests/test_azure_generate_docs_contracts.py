"""Guard: azure-to-aws Generate writes a database migration runbook keyed to `data.db_cutover`.

Q-D2 is confirmed at the Decision gate (estimate-assemble.md Step 3b) and Generate refuses
to start with it unconfirmed. These tests pin the consumer: the MIGRATION_GUIDE section that
holds one branch per answer, the explicit "not covered" note for other engines, the rule that
replication is operator-run, and the wording that Generate emits no migration scripts today.
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


def test_database_runbook_adds_no_scripts_or_untested_commands_claim() -> None:
    text = _read(DOCS)
    section = text.split("## Step 1a:", 1)[1].split("## Step 2", 1)[0]
    assert "writes no database migration script" in section
    assert "--final-sync" not in section


def test_generate_skill_text_does_not_promise_migration_scripts() -> None:
    skill = _read(SKILL_MD)
    generate = _read(GENERATE)
    assert "Terraform, migration scripts, and docs are produced" not in skill
    assert "Terraform configurations, migration scripts, and documentation" not in skill
    assert "Terraform, docs, and the report are produced only after the user chooses Execute" in skill
    assert "no database or VM migration scripts yet" in skill
    assert "AI track also writes its Bedrock migration scripts" in skill
    assert "Emit the Terraform, the scripts, the docs, and the report" not in generate
    assert "Emit the Terraform, the docs, and the report (no database or VM migration scripts yet" in generate
    assert "(no migration scripts yet)" not in generate and "(no migration scripts yet)" not in skill
    assert "`generate-artifacts-ai.md` still writes its Bedrock migration scripts" in generate
    assert "explicitly asked for the Terraform and migration guide this turn" not in generate
    assert "asked for Terraform/migration scripts" not in generate
    # The decision gate and the decision report speak for the same Generate phase, so
    # they must not offer migration scripts either.
    gate = _read(ESTIMATE_ASSEMBLE)
    assert "[C] Generate the migration artifacts — Terraform, migration scripts, and docs" not in gate
    assert "[C] Generate the migration artifacts — Terraform, the migration guide, and the report" in gate
    # A mixed run also runs generate-artifacts-ai.md, so the default label says so.
    assert "append \" (plus the Bedrock migration script and A/B test harness for the AI route)\"" in gate
    # An AI-only run never writes MIGRATION_GUIDE.md, so neither close may promise it.
    estimate_text = _read(ESTIMATE)
    assert "AI-only run" in estimate_text and "no `MIGRATION_GUIDE.md` is ever written" in estimate_text
    assert "On an AI-only run (no `azure-resource-inventory.json`)" in _read(DECISION_CORE)
    for path in (ESTIMATE, DECISION_CORE):
        text = _read(path)
        assert "generate the Terraform and migration scripts" not in text
        assert "and migration scripts'" not in text
        assert "generate the Terraform and the migration guide" in text or "and the migration guide'" in text


def test_generate_postconditions_still_require_a_verification_section() -> None:
    generate = _read(GENERATE)
    assert "MIGRATION_GUIDE.md has Prerequisites and Verification sections" in generate
    docs = _read(DOCS)
    assert "**Verification**" in docs and "Prerequisites" in docs


def test_dms_task_sets_table_preparation_mode_and_checks_source_version_first() -> None:
    text = _read(DOCS)
    branch = text.split("### Branch: `dms`", 1)[1].split("### Not covered by this runbook", 1)[0]
    # The task must not keep Drop-tables-on-target after the schema was precreated.
    steps = branch.split("**AWS DMS steps", 1)[1]
    assert "**Do nothing** (`DO_NOTHING`)" in steps
    assert "`DROP_AND_CREATE`" in steps and "Do not keep **Drop tables on target**" in steps
    assert "`TRUNCATE_BEFORE_LOAD`" in steps
    assert "confirm the setting before starting the task" in steps
    # Both source checklists start with a supported-version check, before any parameter change.
    pg = branch.split("**Source prerequisites: Azure Database for PostgreSQL Flexible Server.**", 1)[1]
    pg = pg.split("**Source prerequisites: Azure Database for MySQL Flexible Server.**", 1)[0]
    assert pg.index("supported-source list") < pg.index("`wal_level`")
    assert "11.2, 12.15, 13.11, 14.8 and 15.3" in pg
    my = branch.split("**Source prerequisites: Azure Database for MySQL Flexible Server.**", 1)[1]
    my = my.split("**AWS DMS steps", 1)[0]
    assert my.index("supported-source list") < my.index("binary logging")
    assert "5.7 and 8" in my


def test_not_covered_note_is_reachable_without_a_relational_database() -> None:
    text = _read(DOCS)
    section = text.split("## Step 1a:", 1)[1].split("### Branch: `dump_restore`", 1)[0]
    assert "whenever the Azure inventory or `aws-design.json` contains a data store of any engine" in section
    assert "Write a `dump_restore` or `dms` branch only when a covered relational database is present" in section
    assert "only data stores are other engines may have no `db_cutover` answer" in section
    assert "Write this subsection only when `aws-design.json` contains a relational database" not in text


def test_dms_load_bypasses_foreign_keys_and_triggers_and_cutover_checks_them() -> None:
    text = _read(DOCS)
    steps = text.split("**AWS DMS steps", 1)[1].split("### Not covered by this runbook", 1)[0]
    step2 = steps.split("2. Create the source endpoint", 1)[1].split("3. Create the target schema", 1)[0]
    # Step 3 precreates foreign keys and triggers, so the target endpoint must bypass them for the load.
    assert "afterConnectScript=SET session_replication_role='replica'" in step2
    assert "Initstmt=SET FOREIGN_KEY_CHECKS=0;" in step2
    assert "child rows can arrive before their parents" in step2
    step3 = steps.split("3. Create the target schema", 1)[1].split("4. Create a database migration task", 1)[0]
    assert "carries the foreign keys and triggers; keep them" in step3
    # MySQL has no session setting that skips triggers: the schema is created without them and they are restored at cutover.
    assert "mysqldump --no-data --skip-triggers" in step3
    assert "`FOREIGN_KEY_CHECKS=0` does not stop triggers" in step3
    assert "mysqldump --no-create-info --no-data --triggers" in step3
    # Step 8 must agree with step 3: nothing is dropped, so it checks them instead of "fixing triggers".
    step8 = steps.split("8. **Cut over.**", 1)[1].split("9. **Roll back.**", 1)[0]
    assert "stop the task so no DMS session remains" in step8
    assert "`pg_constraint`" in step8 and "`information_schema.REFERENTIAL_CONSTRAINTS`" in step8
    # MySQL triggers are created after the task stops and before the switch; the catalog queries are an existence check only.
    assert "On a MySQL target, create the triggers now from the DDL saved in step 3, before the switch" in step8
    assert "`information_schema.TRIGGERS`" in step8
    assert "That is an existence check only" in step8
    assert "`convalidated = true` does not show that the loaded rows satisfy the constraints" in step8
    assert "orphaned child rows" in step8
    assert "sequence values, triggers, secondary indexes" not in step8
