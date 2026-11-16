"""Guards for the three PR 583 review findings on the GPT-5.4 / GPT-5.5 runtime path.

Public model cards (read 2026-11-07):
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html
  https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-55.html

1. IAM: on bedrock-runtime the identity "also needs bedrock:InvokeModel on your
   account's default project (arn:aws:bedrock:{region}:{account-id}:project/default)
   in addition to the inference profile". The setup recipes must say so for the
   GPT-5.5 / GPT-5.4 CRIS ids, not only for GPT-6.
2. Application inference profiles are "Converse API only; not supported with
   Responses or Chat Completions APIs". A Design that selects runtime_openai_cris
   for that need must carry required_client_api: "converse" and surface a
   conflicting Responses-only need as an explicit decision.
3. The cards publish commercial In-Region prices only. No file may infer a Geo or
   Global CRIS price (or a premium / savings percentage) for GPT-5.4 / GPT-5.5 from
   the In-Region row; an In-Region proxy is an unverified planning assumption.
"""
from __future__ import annotations

import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SKILLS = PLUGIN_ROOT / "skills"
AGENTS = PLUGIN_ROOT / "agents"

GCP_GENERATE_AI = SKILLS / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-ai.md"
GCP_GENERATE_ARTIFACTS = SKILLS / "gcp-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md"
AZURE_GENERATE_ARTIFACTS = SKILLS / "azure-to-aws" / "references" / "phases" / "generate" / "generate-artifacts-ai.md"
GCP_DESIGN_AI = SKILLS / "gcp-to-aws" / "references" / "phases" / "design" / "design-ai.md"
AZURE_DESIGN_AI = SKILLS / "azure-to-aws" / "references" / "phases" / "design" / "design-ai.md"
AZURE_SCHEMA = SKILLS / "azure-to-aws" / "references" / "shared" / "schema-design-aws-ai.md"
REPORT_GENERATOR = AGENTS / "llm2bedrock-report-generator.md"

CANONICAL_GUIDE = SKILLS / "shared" / "ai" / "ai-openai-to-bedrock.md"
VENDORED_GUIDES = [
    SKILLS / "gcp-to-aws" / "references" / "vendored" / "ai" / "ai-openai-to-bedrock.md",
    SKILLS / "azure-to-aws" / "references" / "vendored" / "ai" / "ai-openai-to-bedrock.md",
]
FACT_BASES = [
    SKILLS / "gcp-to-aws" / "references" / "shared" / "openai-on-bedrock.md",
    SKILLS / "azure-to-aws" / "references" / "shared" / "openai-on-bedrock.md",
]

_GPT_54_55 = re.compile(r"GPT-5\.[45]|gpt-5\.[45]", re.IGNORECASE)


def _windows(text: str, pattern: re.Pattern[str], radius: int = 700) -> list[str]:
    return [text[max(0, m.start() - radius): m.end() + radius] for m in pattern.finditer(text)]


# --- Finding 1: default-project grant reaches the GPT-5.5 / GPT-5.4 CRIS ids ---

def test_setup_recipes_grant_project_default_for_gpt54_55_cris_ids() -> None:
    for path in (GCP_GENERATE_AI, GCP_GENERATE_ARTIFACTS, AZURE_GENERATE_ARTIFACTS, REPORT_GENERATOR):
        text = path.read_text()
        windows = _windows(text, re.compile(r"project/default"))
        assert windows, f"{path}: no project/default grant sentence"
        assert any(_GPT_54_55.search(w) and "global.openai.gpt-5." in w for w in windows), (
            f"{path}: the project/default grant must name the GPT-5.5 / GPT-5.4 "
            "us./global. CRIS ids, not only GPT-6"
        )
        # The grant is still a runtime-CRIS grant: the recipe must not hand it to bare mantle ids.
        assert not re.search(r"bare `?openai\.gpt-5\.[45]`?[^.]*(gets|needs|requires) (the )?project/default", text), path


def test_no_recipe_still_scopes_project_default_to_gpt6_only() -> None:
    gpt6_only = re.compile(r"For (a )?GPT-6 CRIS( id)?, (also )?grant `bedrock:InvokeModel` on `arn:aws:bedrock:\{region\}:\{account\}:project/default`\.")
    for path in (GCP_GENERATE_AI, GCP_GENERATE_ARTIFACTS):
        assert not gpt6_only.search(path.read_text()), f"{path}: project/default grant is still GPT-6-only"


# --- Finding 2: application inference profiles force required_client_api: "converse" ---

_CONVERSE_FIELD = re.compile(r"required_client_api(`)?:?\s*`?\"?converse\"?")


def test_design_rule_requires_converse_for_application_profiles_on_gpt54_55() -> None:
    for path in (GCP_DESIGN_AI, AZURE_DESIGN_AI, AZURE_SCHEMA):
        text = path.read_text()
        windows = [w for w in _windows(text, re.compile(r"application inference profiles", re.IGNORECASE))
                   if _GPT_54_55.search(w) and _CONVERSE_FIELD.search(w)]
        assert windows, (
            f"{path}: no rule ties application inference profiles on GPT-5.5 / GPT-5.4 "
            "to required_client_api: \"converse\""
        )
        joined = " ".join(" ".join(w.split()) for w in windows)
        assert re.search(r"Converse(-| )only|Converse API only", joined), path
        # Generate's absent-field default and the unsupported-pair omission are the failure mode.
        assert re.search(r"absent", joined), f"{path}: must forbid leaving required_client_api absent"
        # A conflicting Responses-only need is a decision, not a silent drop.
        assert re.search(r"explicit (design )?decision", joined), path
        assert re.search(r"silent", joined), path
        assert re.search(r"structured outputs", joined), path


def test_region_only_cris_move_keeps_responses_default() -> None:
    for path in (GCP_DESIGN_AI, AZURE_DESIGN_AI, AZURE_SCHEMA):
        text = path.read_text()
        assert re.search(r"default[^.]*region-only|region-only[^.]*default", text), (
            f"{path}: the responses default for a region-only CRIS move must remain"
        )


def test_design_checklists_assert_the_application_profile_rule() -> None:
    for path in (GCP_DESIGN_AI, AZURE_SCHEMA):
        text = path.read_text()
        checklist = text[text.index("## Validation Checklist"):]
        item = [w for w in _windows(checklist, re.compile(r"application inference profiles"), 500)
                if _CONVERSE_FIELD.search(w) and _GPT_54_55.search(w)]
        assert item, f"{path}: Validation Checklist has no application-profile → converse item"
        assert "explicit decision" in " ".join(item), path


# --- Finding 3: no Geo/Global CRIS price inferred from the In-Region row ---

_INFERRED_CRIS_PRICE = re.compile(
    r"(every inference option|until a Global rate is published|on every inference option)",
    re.IGNORECASE,
)


def test_the_1_10x_geo_rate_names_gpt56_not_the_gpt5x_family() -> None:
    """The GPT-5.4 and GPT-5.5 cards publish no Geo or Global price. A GPT-5.x
    In-Region-and-Geo 1.10x bullet would price those CRIS ids at the In-Region rate.
    """
    for path in [CANONICAL_GUIDE, *VENDORED_GUIDES, *FACT_BASES]:
        text = path.read_text()
        assert "GPT-5.x In-Region and Geo" not in text, path
        assert "GPT-5.6 In-Region and Geo" in text, path


CLARIFY_AI_ONLY = [
    SKILLS / "gcp-to-aws" / "references" / "phases" / "clarify" / "clarify-ai-only.md",
    SKILLS / "azure-to-aws" / "references" / "phases" / "clarify" / "clarify-ai-only.md",
    SKILLS / "bedrock-migration-assessment" / "references" / "phases" / "clarify" / "clarify-ai-only.md",
]


def test_clarify_ai_only_scopes_the_gpt54_55_premium_to_in_region() -> None:
    for path in CLARIFY_AI_ONLY:
        rows = [
            line for line in path.read_text().splitlines()
            if re.match(r"\| GPT-5\.5\s+\|", line) or re.match(r"\| GPT-5\.4\s+\|", line)
        ]
        assert len(rows) == 2, f"{path}: expected two GPT-5.5 / GPT-5.4 rows, got {rows}"
        for line in rows:
            assert "In-Region (mantle)" in line, line
            assert "no Geo or Global price published" in line, line


def test_no_file_infers_a_cris_price_for_gpt54_55_from_in_region() -> None:
    offenders = {}
    for path in [CANONICAL_GUIDE, *VENDORED_GUIDES, *FACT_BASES, REPORT_GENERATOR]:
        text = path.read_text()
        hits = [m.group(0) for m in _INFERRED_CRIS_PRICE.finditer(text)
                if _GPT_54_55.search(text[max(0, m.start() - 400): m.end() + 400])]
        if hits:
            offenders[str(path.relative_to(PLUGIN_ROOT))] = hits
    assert not offenders, f"GPT-5.5 / GPT-5.4 CRIS price inferred from the In-Region row: {offenders}"


def test_premium_is_scoped_to_commercial_in_region_and_proxy_is_labelled() -> None:
    for path in [CANONICAL_GUIDE, *VENDORED_GUIDES, *FACT_BASES, REPORT_GENERATOR]:
        text = path.read_text()
        windows = [" ".join(w.split()) for w in _windows(text, re.compile(r"In-Region\s+pric(?:es?|ing)\s+(?:only|include)", re.IGNORECASE))
                   if _GPT_54_55.search(w)]
        assert windows, f"{path}: no GPT-5.5 / GPT-5.4 In-Region-only pricing statement"
        joined = " ".join(windows)
        assert re.search(r"commercial In-Region", joined, re.IGNORECASE), path
        assert re.search(r"Geo( \(`us\.`\))? or Global CRIS price|Geo/Global (rate|price|rows)", joined), path
        assert "unverified planning assumption" in joined, path
        assert re.search(r"(no|not .*?)(verified )?(premium or savings|premium|savings) percentage", joined), (
            f"{path}: a CRIS plan with only card prices must yield no verified premium/savings percentage"
        )
        assert re.search(r"unavailable", joined), f"{path}: must allow reporting the comparison unavailable"


def test_tier0_table_scopes_gpt54_55_premium_to_in_region() -> None:
    for path in [CANONICAL_GUIDE, *VENDORED_GUIDES]:
        rows = [
            line for line in path.read_text().splitlines()
            if (line.startswith("| GPT-5.5 ") or line.startswith("| GPT-5.4 ")) and "strong_migrate" in line
        ]
        assert len(rows) == 2, f"{path}: expected the two Tier 0 GPT-5.5 / GPT-5.4 rows, got {rows}"
        for line in rows:
            assert "In-Region only" in line and "no Geo/Global price published" in line, line


def test_vendored_guides_match_canonical() -> None:
    for vendored in VENDORED_GUIDES:
        assert vendored.read_bytes() == CANONICAL_GUIDE.read_bytes(), vendored
