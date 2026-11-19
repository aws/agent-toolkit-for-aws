"""Beanstalk Cluster mode is documented as informational only in heroku-to-aws.
The skill designs and prices Beanstalk Standard (EC2). These checks keep the note
from turning into an unpriced compute target by accident.
"""
from __future__ import annotations
from pathlib import Path
PLUGIN_ROOT = Path(__file__).resolve().parent.parent
PHASES = PLUGIN_ROOT / "skills" / "heroku-to-aws" / "references" / "phases"
INTERVIEW = PHASES / "clarify" / "clarify-interview.md"
SHEET = PHASES / "workshop" / "workshop-sheet.md"
ASSEMBLE = PHASES / "clarify" / "clarify-assemble.md"
def test_cluster_note_is_informational_and_names_the_cost_and_fit_limits() -> None:
    text = INTERVIEW.read_text(encoding="utf-8")
    note = text[text.index("**Beanstalk Cluster note (informational only):**"):text.index("#### Q12d")]
    assert "not a `compute_target` value" in note
    assert "prices Standard (EC2) environments only" in note
    assert "Do not change any answer, field or option" in note
    for point in ("can mean two\n  clusters", "NAT", "Local disk is lost", "match the environment's `arch`"):
        assert point in note or point.replace("match", "must match") in note, point
    assert "Terraform generation" in note
def test_cluster_mode_is_not_added_as_a_compute_target_value() -> None:
    for path in (INTERVIEW, SHEET, ASSEMBLE):
        text = path.read_text(encoding="utf-8")
        assert '"elastic_beanstalk_cluster"' not in text, path
        assert "elastic-beanstalk-cluster" not in text, path
    assert "keep `elastic_beanstalk`" in SHEET.read_text(encoding="utf-8")

def test_cluster_note_has_one_deterministic_predicate_with_boundary_cases() -> None:
    text = INTERVIEW.read_text(encoding="utf-8")
    note = text[text.index("**Beanstalk Cluster note (informational only):**"):text.index("#### Q12d")]
    flat = " ".join(note.split())
    assert "resolves three or more non-release formations to `elastic_beanstalk`" in flat
    assert "whatever the number of Heroku apps" in flat
    assert "Do not add it for a single app" not in flat
    assert "one app with `web`, `worker` and `clock` all on EB counts 3 and shows it" in flat
    assert "three EB formations plus one user-selected Fargate formation counts 3 and shows it" in flat
    assert "two EB formations count 2 and do not" in flat
    assert "an all-Fargate or EKS plan counts 0 and does not" in flat
    assert "AWS recommends separate subnets" not in flat
    assert "common reason to use different subnet sets" in flat
