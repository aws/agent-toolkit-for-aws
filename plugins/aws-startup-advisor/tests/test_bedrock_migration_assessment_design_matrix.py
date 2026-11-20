"""The Design model-choice matrix: coverage of every Clarify value, targets that still exist, and inputs plan accepts."""
from __future__ import annotations

import copy
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


INPUT_COLUMNS = {"vision": "Image input", "audio": "Audio input"}
INPUT_WORDS = {"vision": "image", "audio": "audio"}


def _sections(text: str) -> dict[str, str]:
    heads = [(m.start(), len(m.group(1)), m.group(2).strip()) for m in re.finditer(r"^(#+) (.+)$", text, re.M)]
    found = {}
    for i, (start, level, title) in enumerate(heads):
        end = next((s for s, lv, _ in heads[i + 1:] if lv <= level), len(text))
        found[title] = " ".join(text[start:end].split())
    return found


def _input_violations(rows: list[dict]) -> list[tuple]:
    caps, evidence = _capability_table(), {(e["model"], e["modality"]): e for e in MATRIX["input_evidence"]}
    bad = []
    for row in rows:
        modality = row["preferences"]["ai_vision"]
        if modality not in INPUT_COLUMNS:
            continue
        for target in row["allowed"]:
            entry = evidence.get((target, modality))
            if caps.get(target, {}).get(INPUT_COLUMNS[modality]) == "yes":
                continue
            if caps.get(target, {}).get(INPUT_COLUMNS[modality]) == "no" or not entry:
                bad.append((row["id"], target, "no Capability Constraints yes and no input_evidence entry"))
            elif entry["probe"] and {"model": target, "modality": modality} not in row.get("probes", []):
                bad.append((row["id"], target, f"input_evidence says to probe {modality}; list it in probes"))
    return bad


def test_no_row_allows_a_model_that_cannot_take_its_input() -> None:
    assert not _input_violations(ROWS)


@pytest.mark.parametrize(("row_id", "target"), [("pair-04", "amazon.titan-embed-text-v2:0"), ("pair-04", "amazon.nova-micro-v1:0"),
                                                ("pair-03", "anthropic.claude-sonnet-5"), ("pair-15", "openai.gpt-5.4"),
                                                ("pair-03", "openai.gpt-5.6-terra")])
def test_the_input_check_rejects_a_target_with_no_input_evidence(row_id, target) -> None:
    row = copy.deepcopy(next(r for r in ROWS if r["id"] == row_id))
    row["allowed"].append(target)
    assert [v[:2] for v in _input_violations([row])] == [(row_id, target)]


def test_the_input_check_accepts_a_capability_constraints_yes() -> None:
    row = copy.deepcopy(next(r for r in ROWS if r["id"] == "pair-15"))
    row["allowed"].append("openai.gpt-6.1-terra")
    assert not _input_violations([row])


def test_the_input_check_requires_the_probe_on_a_probe_only_target() -> None:
    row = copy.deepcopy(next(r for r in ROWS if r["id"] == "pair-03"))
    assert row["probes"] and not _input_violations([row])
    row.pop("probes")
    assert _input_violations([row]) == [("pair-03", "openai.gpt-5.5", "input_evidence says to probe audio; list it in probes")]


@pytest.mark.parametrize("entry", MATRIX["input_evidence"], ids=[f"{e['model']}-{e['modality']}" for e in MATRIX["input_evidence"]])
def test_each_input_evidence_entry_quotes_its_guide(entry) -> None:
    section = _sections((VENDORED / entry["file"]).read_text(encoding="utf-8")).get(entry["section"], "")
    assert " ".join(entry["quote"].split()) in section, entry
    assert entry["names"] in entry["quote"] and INPUT_WORDS[entry["modality"]] in entry["quote"].lower()
    assert ("probe" in entry["quote"]) is entry["probe"]
    family = re.escape(entry["names"].lower().replace(" ", "-")).replace(r"\.x", r"\.\d+")
    assert re.search(rf"\.{family}(\b|-|:)", entry["model"]), entry
    assert entry["model"] not in _capability_table() or _capability_table()[entry["model"]][INPUT_COLUMNS[entry["modality"]]] != "no"


def test_every_probe_a_row_lists_has_probe_evidence() -> None:
    probes = {(e["model"], e["modality"]) for e in MATRIX["input_evidence"] if e["probe"]}
    for row in ROWS:
        for probe in row.get("probes", []):
            assert (probe["model"], probe["modality"]) in probes and probe["modality"] == row["preferences"]["ai_vision"], row["id"]
            assert probe["model"] in row["allowed"], row["id"]


def _design_step2_item(number: int) -> str:
    step2 = DESIGN_DOC[DESIGN_DOC.index("## Step 2:"):DESIGN_DOC.index("## Step 3:")]
    found = re.search(rf"^{number}\. (.*)$", step2, re.MULTILINE)
    assert found, f"design-ai.md Step 2 has no item {number}"
    return found.group(1)


def test_design_tells_design_to_record_every_probe_the_matrix_requires() -> None:
    # The matrix accepts a probe-only target on condition that Design names the probe, so the rule must be in the doc Design reads.
    assert "design-ai.md Step 2 item 6" in MATRIX["input_evidence_note"]
    item = _design_step2_item(6)
    assert "probe" in item and "`capability_gaps[]`" in item and "before cutover" in item
    for entry in (e for e in MATRIX["input_evidence"] if e["probe"]):
        assert entry["names"] in item and INPUT_WORDS[entry["modality"]] in item.lower(), entry
        assert f"`{entry['file']}` {entry['section']}" in item, entry


def test_vision_rows_exclude_nova_micro() -> None:
    rows = [r for r in ROWS if r["preferences"]["ai_vision"] == "vision"]
    assert rows and not [r["id"] for r in rows if "amazon.nova-micro-v1:0" in r["allowed"]]


def _size(cell: str) -> float:
    found = re.match(r"≤?\s*(\d+(?:\.\d+)?)\s*([KM])", cell.strip())
    return float(found.group(1)) * (1e6 if found.group(2) == "M" else 1e3) if found else 0.0


def _pricing_tables() -> list[list[dict[str, str]]]:
    return _tables((VENDORED / "bedrock-pricing-cache.md").read_text(encoding="utf-8"))


def _context_windows() -> dict[str, float]:
    windows = {model_id: _size(row["Context window"]) for model_id, row in _capability_table().items()}
    for row in (r for t in _pricing_tables() for r in t if "Context" in r and r.get("Model ID", "—") not in ("—", "")):
        tier = re.search(r"(\d+(?:\.\d+)?[KM])[ -]tier", row.get("Status", ""))
        model_id = matrix.base_id(row["Model ID"])
        windows[model_id] = max(windows.get(model_id, 0.0), _size(row["Context"]), _size(tier.group(1)) if tier else 0.0)
    return windows


def _cache_read_models() -> set[str]:
    tables, ids, found = _pricing_tables(), {}, set()
    for row in (r for t in tables for r in t if r.get("Model ID", "—") not in ("—", "") and "Model" in r):
        ids.setdefault(row["Model"].removeprefix("Amazon "), set()).add(matrix.base_id(row["Model ID"]))
    for row in (r for t in tables for r in t):
        for header, cell in row.items():
            if "cache read" in header.lower():
                rate = cell
            elif "cache-read" in header:
                parts, values = re.search(r"\((.*)\)", header).group(1).split("·"), cell.split("·")
                rate = values[[p.strip() for p in parts].index("cache-read")] if len(values) == len(parts) else ""
            else:
                continue
            number = re.match(r"\s*(\d*\.?\d+)", rate)
            if number and float(number.group(1)) > 0:
                found |= ids.get(row.get("Model", "").removeprefix("Amazon "), set())
    text = (VENDORED / "bedrock-pricing-cache.md").read_text(encoding="utf-8")
    for section in re.split(r"^### ", text, flags=re.M):
        discount = re.search(r"\*\*Cache read \([^)]+\):\*\*.*?(\d+)% below\*\* the on-demand input price", section)
        if not discount or not 0 < int(discount.group(1)) < 100:
            continue
        priced = set()
        for row in (r for t in _tables(section) for r in t):
            price = next((c for h, c in row.items() if h in ("Input $/1M", "Text in", "On-demand in")), "")
            if re.match(r"\s*\d*\.?\d+", price) and float(price) > 0:
                priced |= ids.get(row.get("Model", "").removeprefix("Amazon "), set())
        assert priced, f"no priced model id for {discount.group(0)}"
        found |= priced
    return found


ULTRA_LONG_CONTEXT = 300_000  # Clarify Q10 "Ultra-long context (> 300K tokens)"
KB_SENTENCE = re.compile(r"Choose (.+?) via Converse when the workload needs Knowledge Bases")
FAMILY_PREFIXES = {"Claude": "anthropic.claude-", "Nova": "amazon.nova-"}


def _knowledge_base_line() -> tuple[int, list[str]]:
    lines = (VENDORED / "ai-openai-to-bedrock.md").read_text(encoding="utf-8").splitlines()
    number, found = next((i + 1, KB_SENTENCE.search(line)) for i, line in enumerate(lines) if KB_SENTENCE.search(line))
    return number, [name.strip() for name in found.group(1).split("/")]


def _knowledge_base_models() -> set[str]:
    prefixes = tuple(FAMILY_PREFIXES[name] for name in _knowledge_base_line()[1])
    return {m for m in _cache_statuses()[0] if m.startswith(prefixes)}


def _rag_violations(rows: list[dict]) -> list[tuple]:
    served = _knowledge_base_models()
    return [(r["id"], a) for r in rows if r["preferences"]["ai_critical_feature"] == "rag" for a in r["allowed"] if a not in served]


FEATURE_SERVERS = {
    "prompt_caching": _cache_read_models,
    "ultra_long_context": lambda: {m for m, w in _context_windows().items() if w > ULTRA_LONG_CONTEXT},
    "image_generation": lambda: {m for m, r in _capability_table().items() if r["Image input"] == "yes"},
    "rag": _knowledge_base_models,
}
FEATURE_ROWS = [r for r in ROWS if r["group"] == "critical_feature" and r["decided_by"] == "critical_feature"
                and r["preferences"]["ai_critical_feature"] in FEATURE_SERVERS]


@pytest.mark.parametrize("row", FEATURE_ROWS, ids=[r["id"] for r in FEATURE_ROWS])
def test_a_feature_row_allows_every_candidate_of_its_source_and_priority_that_serves_the_feature(row) -> None:
    priority = row["preferences"]["ai_priority"]
    pool = {a for r in _pairwise_rows() if r["source"] == row["source"] and r["preferences"]["ai_priority"] == priority
            for a in r["allowed"]}
    serving = pool & FEATURE_SERVERS[row["preferences"]["ai_critical_feature"]]()
    assert serving, row["id"]
    assert not sorted(serving - set(row["allowed"])), (row["id"], sorted(serving - set(row["allowed"])))


def test_rag_rows_allow_only_the_families_the_openai_guide_names_for_knowledge_bases() -> None:
    number, families = _knowledge_base_line()
    assert set(families) == {"Claude", "Nova"} and not [m for m in _knowledge_base_models() if m.startswith("openai.")]
    rows = [r for r in ROWS if r["preferences"]["ai_critical_feature"] == "rag"]
    assert rows and not _rag_violations(rows)
    for row in rows:
        assert row["decided_by"] == "critical_feature" and f"(line {number})" in row["basis"], row["id"]
        assert "schema-design-aws-ai.md" in row["basis"] and "model_change true" in row["basis"], row["id"]


@pytest.mark.parametrize("target", ["openai.gpt-5.6-terra", "openai.gpt-5.5", "deepseek.v3-v1:0"])
def test_a_rag_row_allowing_a_model_outside_claude_and_nova_fails(target) -> None:
    row = copy.deepcopy(next(r for r in ROWS if r["id"] == "feature-rag"))
    row["allowed"].append(target)
    assert _rag_violations([row]) == [("feature-rag", target)]


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
