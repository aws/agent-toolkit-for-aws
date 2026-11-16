"""The ai_token_volume tier table is defined once, and bedrock-migration-assessment's Q7 matches it."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BMA = PLUGIN_ROOT / "skills" / "bedrock-migration-assessment"
SHARED = PLUGIN_ROOT / "skills/shared/ai/token-volume-tiers.json"
TIERS = json.loads(SHARED.read_text(encoding="utf-8"))
CLARIFY = (BMA / "references/phases/clarify/clarify-ai-only.md").read_text(encoding="utf-8")
Q7 = CLARIFY[CLARIFY.index("## Q7 "):CLARIFY.index("## Q8 ")]


def tier_of(tokens: int) -> str:
    """The tier whose half-open range contains a token count."""
    return next(t["value"] for t in TIERS["tiers"] if t["min_tokens"] <= tokens and (t["max_tokens"] is None or tokens < t["max_tokens"]))


def test_tiers_cover_every_count_once() -> None:
    tiers = TIERS["tiers"]
    assert tiers[0]["min_tokens"] == 0 and tiers[-1]["max_tokens"] is None
    assert all(a["max_tokens"] == b["min_tokens"] for a, b in zip(tiers, tiers[1:]))
    assert all(t["max_tokens"] is None or t["min_tokens"] < t["max_tokens"] for t in tiers)
    assert [t["q7_option"] for t in tiers] == [1, 2, 3, 4] and TIERS["dont_know"]["q7_option"] == 5
    assert TIERS["dont_know"]["default"] in {t["value"] for t in tiers}
    assert 0 < TIERS["input_share"] < 1


@pytest.mark.parametrize(("tokens", "tier"), [(0, "low"), (999_999, "low"), (1_000_000, "medium"), (9_999_999, "medium"),
                                              (10_000_000, "high"), (99_999_999, "high"), (100_000_000, "very_high"), (10**12, "very_high")])
def test_each_boundary_belongs_to_exactly_one_tier(tokens, tier) -> None:
    assert tier_of(tokens) == tier
    assert sum(t["min_tokens"] <= tokens and (t["max_tokens"] is None or tokens < t["max_tokens"]) for t in TIERS["tiers"]) == 1


def test_q7_options_and_values_match_the_table() -> None:
    options = re.search(r"^> (1\\\).*)$", Q7, re.M).group(1)
    labels = [label.strip() for label in re.split(r"\d\\\)", options) if label.strip(" |")]
    labels = [label.strip(" |") for label in labels]
    assert labels == [t["label"] for t in TIERS["tiers"]] + [TIERS["dont_know"]["label"]]
    mapping = dict(re.findall(r"(\d) → `\"([a-z_]+)\"`", Q7[Q7.index("Interpret → `ai_token_volume`"):]))
    assert mapping == {str(t["q7_option"]): t["value"] for t in TIERS["tiers"]}
    default = re.search(r"Default: (\d) → `\"([a-z_]+)\"`", Q7).groups()
    assert default == (str(next(t["q7_option"] for t in TIERS["tiers"] if t["value"] == TIERS["dont_know"]["default"])), TIERS["dont_know"]["default"])


def stated_range(label: str) -> tuple[int, int | None]:
    """The half-open token range [low, high) a Q7 label states; '<' and 'under' are exclusive, 'or more' inclusive."""
    million = 1_000_000
    below = re.fullmatch(r"< (\d+)M tokens", label)
    if below:
        return 0, int(below.group(1)) * million
    span = re.fullmatch(r"(\d+)M to under (\d+)M", label)
    if span:
        return int(span.group(1)) * million, int(span.group(2)) * million
    above = re.fullmatch(r"(\d+)M or more", label)
    if above:
        return int(above.group(1)) * million, None
    strict = re.fullmatch(r"> (\d+)M", label)
    if strict:
        return int(strict.group(1)) * million + 1, None
    raise AssertionError(f"label does not state its bounds: {label!r}")


def test_each_label_states_the_table_bounds() -> None:
    for tier in TIERS["tiers"]:
        assert stated_range(tier["label"]) == (tier["min_tokens"], tier["max_tokens"])


@pytest.mark.parametrize("label", ["> 100M", "> 10M"])
def test_a_strict_lower_bound_does_not_match_an_inclusive_tier(label) -> None:
    assert stated_range(label)[0] not in {t["min_tokens"] for t in TIERS["tiers"]}


@pytest.mark.parametrize("tokens", [0, 999_999, 1_000_000, 9_999_999, 10_000_000, 99_999_999, 100_000_000, 10**12])
def test_every_boundary_matches_one_displayed_label_and_its_tier(tokens) -> None:
    matches = [t["value"] for t in TIERS["tiers"]
               if stated_range(t["label"])[0] <= tokens and (stated_range(t["label"])[1] is None or tokens < stated_range(t["label"])[1])]
    assert matches == [tier_of(tokens)]


def test_gcp_q7_shows_the_same_labels_and_auto_resolve_bands() -> None:
    gcp = (PLUGIN_ROOT / "skills/gcp-to-aws/references/phases/clarify/clarify-ai-only.md").read_text(encoding="utf-8")
    gcp_q7 = gcp[gcp.index("## Q7 "):gcp.index("## Q8 ")]
    options = re.search(r"^> (1\\\).*)$", gcp_q7, re.M).group(1)
    assert options == re.search(r"^> (1\\\).*)$", Q7, re.M).group(1)
    for tier in TIERS["tiers"]:
        assert f'{tier["label"].removesuffix(" tokens")} → `"{tier["value"]}"`' in gcp_q7


def test_q7_places_a_measured_total_with_the_table_bounds() -> None:
    assert "references/vendored/ai/token-volume-tiers.json" in Q7 and "`min_tokens` inclusive, `max_tokens` exclusive" in Q7
    assert "Q7 also reads this skill's `references/vendored/ai/token-volume-tiers.json`" in CLARIFY
    vendored = BMA / "references/vendored/ai/token-volume-tiers.json"
    assert vendored.read_bytes() == SHARED.read_bytes()
