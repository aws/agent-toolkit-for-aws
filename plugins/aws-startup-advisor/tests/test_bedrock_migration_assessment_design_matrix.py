"""The Design model-choice matrix: coverage of every Clarify value, targets that still exist, and inputs plan accepts."""
from __future__ import annotations

import importlib.util
import itertools
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bma_design_matrix as matrix  # noqa: E402

BMA = matrix.PLUGIN_ROOT / "skills" / "bedrock-migration-assessment"
VENDORED = BMA / "references" / "vendored" / "ai"
DESIGN_DOC = (BMA / "references/phases/design/design-ai.md").read_text(encoding="utf-8")


def _module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, BMA / "scripts" / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


DESIGN = _module("bma_design_ai_matrix", "design-ai.py")
MATRIX = matrix.load()
ROWS = MATRIX["rows"]
SOURCES = MATRIX["sources"]
PAIRWISE_DIMS = ("source", "ai_priority", "ai_latency", "ai_complexity", "ai_token_volume", "ai_vision")
DECIDED_BY = {"capability", "critical_feature", "same_model", "priority", "two_options"}


def _tables(text: str) -> list[list[dict[str, str]]]:
    tables, header, rows = [], None, []
    for line in text.splitlines() + [""]:
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if header is None:
                header = cells
            elif not set("".join(cells)) <= set("-: "):
                rows.append(dict(zip(header, cells)))
        elif header is not None:
            tables.append(rows)
            header, rows = None, []
    return tables


def _cache_statuses() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    by_id: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    for table in _tables((VENDORED / "bedrock-pricing-cache.md").read_text(encoding="utf-8")):
        for row in table:
            if "Status" not in row:
                continue
            by_name.setdefault(row.get("Model", ""), []).append(row["Status"])
            if row.get("Model ID", "—") not in ("—", ""):
                by_id.setdefault(matrix.base_id(row["Model ID"]), []).append(row["Status"])
    return by_id, by_name


def _capability_table() -> dict[str, dict[str, str]]:
    text = (VENDORED / "ai-model-lifecycle.md").read_text(encoding="utf-8")
    section = text[text.index("## Capability Constraints"):text.index("## Legacy / EOL Models")]
    table = next(t for t in _tables(section) if t and "Image input" in t[0])
    return {re.search(r"`([^`]+)`", r["Model ID"]).group(1): r for r in table}


def _pref(row: dict, key: str) -> str:
    return row["source"] if key == "source" else row["preferences"][key]


def _pairwise_rows() -> list[dict]:
    return [r for r in ROWS if r["group"] == "pairwise"]


def _excluded(pair: dict[str, str]) -> bool:
    return any(all(pair.get(k) == v for k, v in rule["when"].items()) for rule in MATRIX["excluded_pairs"])


# --------------------------------------------------------------------------- shape

def test_rows_have_unique_ids_and_known_sources_and_deciders() -> None:
    assert len({r["id"] for r in ROWS}) == len(ROWS)
    for row in ROWS:
        assert row["source"] in SOURCES and row["decided_by"] in DECIDED_BY and row["allowed"] and row["basis"], row["id"]


@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_row_preferences_use_only_pinned_values(row) -> None:
    assert set(row["preferences"]) == set(DESIGN.PREFERENCE_VALUES), row["id"]
    for key, value in row["preferences"].items():
        assert value in DESIGN.PREFERENCE_VALUES[key], (row["id"], key, value)


def test_fixtures_readme_counts_match_the_matrix() -> None:
    readme = (matrix.FIXTURES / "README.md").read_text(encoding="utf-8")
    entry = next(line for line in readme.splitlines() if line.startswith("- `bma-design-model-matrix/`"))
    counts = {g: sum(r["group"] == g for r in ROWS) for g in ("pairwise", "critical_feature", "capability")}
    assert f"The {counts['pairwise']} `pairwise` rows" in entry and f"{counts['critical_feature']} rows cover each" in entry
    assert f"{counts['capability']} cover the non-text" in entry


# --------------------------------------------------------------------------- coverage

@pytest.mark.parametrize("key", list(DESIGN.PREFERENCE_VALUES))
def test_every_pinned_value_appears_in_a_row(key) -> None:
    assert {r["preferences"][key] for r in ROWS} == set(DESIGN.PREFERENCE_VALUES[key])


def test_every_pair_of_pairwise_values_is_covered_unless_excluded() -> None:
    domains = {"source": sorted({r["source"] for r in _pairwise_rows()}),
               **{k: DESIGN.PREFERENCE_VALUES[k] for k in PAIRWISE_DIMS[1:]}}
    assert set(domains["source"]) == {k for k, s in SOURCES.items() if s["capability"] == "text_generation"}
    seen = {(a, _pref(r, a), b, _pref(r, b)) for r in _pairwise_rows() for a, b in itertools.combinations(PAIRWISE_DIMS, 2)}
    missing = [(a, x, b, y) for a, b in itertools.combinations(PAIRWISE_DIMS, 2) for x in domains[a] for y in domains[b]
               if (a, x, b, y) not in seen and not _excluded({a: x, b: y})]
    assert not missing, missing[:10]


def test_excluded_pairs_never_appear_and_each_gives_a_reason() -> None:
    for rule in MATRIX["excluded_pairs"]:
        assert rule["reason"] and not [r["id"] for r in ROWS if all(_pref(r, k) == v for k, v in rule["when"].items())]


def test_pairwise_rows_have_no_critical_feature() -> None:
    assert {r["preferences"]["ai_critical_feature"] for r in _pairwise_rows()} == {"none"}


def test_each_critical_feature_has_a_row_with_a_conflicting_priority() -> None:
    rows = [r for r in ROWS if r["group"] == "critical_feature" and r["decided_by"] != "same_model"]
    features = [r["preferences"]["ai_critical_feature"] for r in rows]
    assert sorted(features) == sorted(set(DESIGN.PREFERENCE_VALUES["ai_critical_feature"]) - {"none"})
    assert all(r["preferences"]["ai_priority"] != "balanced" for r in rows)


def test_a_feature_the_same_model_serves_keeps_the_same_model() -> None:
    rows = [r for r in ROWS if r["group"] == "critical_feature" and r["decided_by"] == "same_model"]
    assert rows and all(r["allowed"] == [SOURCES[r["source"]]["same_model"]] for r in rows)


def test_every_non_text_capability_has_a_row() -> None:
    caps = {SOURCES[r["source"]]["capability"] for r in ROWS if r["decided_by"] == "capability"}
    assert caps == {"embedding", "image_generation", "speech_to_text", "text_to_speech"}


# --------------------------------------------------------------------------- the expected targets

def test_a_same_model_source_keeps_its_model_for_every_priority() -> None:
    for row in ROWS:
        same = SOURCES[row["source"]]["same_model"]
        if same and row["preferences"]["ai_critical_feature"] == "none":
            assert row["decided_by"] == "same_model" and row["allowed"] == [same], row["id"]
    priorities = {(r["source"], r["preferences"]["ai_priority"]) for r in _pairwise_rows() if SOURCES[r["source"]]["same_model"]}
    assert {p for _, p in priorities} == set(DESIGN.PREFERENCE_VALUES["ai_priority"])


def test_a_source_with_no_bedrock_equivalent_never_expects_one_model_only_from_a_priority() -> None:
    for row in _pairwise_rows():
        if not SOURCES[row["source"]]["same_model"]:
            assert row["decided_by"] in ("priority", "two_options") and len(row["allowed"]) >= 2, row["id"]


@pytest.mark.parametrize("target", sorted({a for r in ROWS for a in r["allowed"] if not a.startswith("service:")}))
def test_every_allowed_target_is_an_active_unrestricted_cache_row(target) -> None:
    by_id, by_name = _cache_statuses()
    statuses = by_name.get(MATRIX["wildcard_targets"][target], []) if target.endswith("*") else by_id.get(target, [])
    assert statuses, f"{target} is not in bedrock-pricing-cache.md"
    assert all(s.startswith("active") for s in statuses), (target, statuses)


def test_service_targets_are_the_ones_design_names() -> None:
    services = {a for r in ROWS for a in r["allowed"] if a.startswith("service:")}
    assert services == {f"service:{s}" for s in DESIGN.SPEECH_SERVICES.values()}


@pytest.mark.parametrize(("pref", "column"), [("vision", "Image input"), ("audio", "Audio input")])
def test_no_row_allows_a_model_that_cannot_take_its_input(pref, column) -> None:
    caps = _capability_table()
    bad = [(r["id"], a) for r in ROWS if r["preferences"]["ai_vision"] == pref for a in r["allowed"]
           if caps.get(a, {}).get(column) == "no"]
    assert not bad


def test_vision_rows_exclude_nova_micro() -> None:
    rows = [r for r in ROWS if r["preferences"]["ai_vision"] == "vision"]
    assert rows and not [r["id"] for r in rows if "amazon.nova-micro-v1:0" in r["allowed"]]


def test_capability_rows_follow_design_step_2_item_1() -> None:
    item = DESIGN_DOC[DESIGN_DOC.index("1. **By capability:**"):DESIGN_DOC.index("2. **Text models")]
    names = {"amazon.titan-embed-text-v2:0": "Amazon Titan Text Embeddings V2", "service:transcribe": "Amazon Transcribe",
             "service:polly": "Amazon Polly", "stability.stable-image-core-v1:1": "Stable Image Core",
             "stability.stable-image-ultra-v1:1": "Ultra"}
    for row in (r for r in ROWS if r["decided_by"] == "capability"):
        assert all(names[a] in item for a in row["allowed"]), row["id"]


@pytest.mark.parametrize(("allowed", "target", "ok"), [
    (["anthropic.claude-sonnet-5"], "us.anthropic.claude-sonnet-5", True),
    (["anthropic.claude-sonnet-5"], "global.anthropic.claude-sonnet-5-5", False),
    (["amazon.nova-2-sonic*"], "amazon.nova-2-sonic-v1:0", True),
    (["amazon.nova-2-sonic*"], "amazon.nova-2-lite-v1:0", False),
    (["service:polly"], "service:polly", True),
    (["service:polly"], "service:transcribe", False)])
def test_target_matching_strips_only_the_cris_prefix(allowed, target, ok) -> None:
    assert matrix.matches(allowed, target) is ok


# --------------------------------------------------------------------------- the inputs are real

@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_each_row_builds_a_profile_and_preferences_that_plan_accepts(row) -> None:
    profile, prefs = matrix.build_profile(SOURCES[row["source"]]), matrix.build_preferences(row)
    DESIGN.validator.validate_profile(profile)
    plan = DESIGN.build_plan(profile, prefs)
    assert [(r["model_id"], r["capability"]) for r in plan["rows"]] == [(SOURCES[row["source"]]["model"],
                                                                       SOURCES[row["source"]]["capability"])]
    assert all(plan["constraints"][k]["value"] == v for k, v in row["preferences"].items())
    assert plan["rows"][0]["mantle"]["lane"] == "runtime"
    high = row["preferences"]["ai_token_volume"] in ("high", "very_high")
    assert plan["tiered_strategy_required"] is high and (plan["quota_risk_floor"] == "high") is high
