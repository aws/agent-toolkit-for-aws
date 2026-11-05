import re
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SKILLS = PLUGIN_ROOT / "skills"


def read(relative_path: str) -> str:
    return (SKILLS / relative_path).read_text(encoding="utf-8")


def normalized(text: str) -> str:
    return " ".join(text.split())


def test_gcp_advertises_live_and_usage_discovery_before_terraform_scan() -> None:
    skill = read("gcp-to-aws/SKILL.md")
    discover = read("gcp-to-aws/references/phases/discover/discover.md")

    assert "Terraform is optional" in skill.split("---", 2)[1]

    orientation = discover.index("**Before you send or upload files:**")
    terraform_scan = discover.index("**1a. Check for Terraform files:**")

    assert orientation < terraform_scan
    assert "Terraform is optional" in discover[orientation:terraform_scan]
    assert "authenticated `gcloud` CLI" in discover[orientation:terraform_scan]
    assert "OpenAI, OpenRouter, or Anthropic" in discover[orientation:terraform_scan]
    assert "combine sources" in discover[orientation:terraform_scan]


def test_azure_advertises_all_discovery_sources_before_source_actions() -> None:
    discover = read("azure-to-aws/references/phases/discover/discover.md")

    orientation = discover.index("**Discovery orientation (fresh runs only):**")
    rdfa_action = discover.index("### RDfA detection, guidance, and preparation")

    assert orientation < rdfa_action
    block = discover[orientation:rdfa_action]
    assert "Terraform is optional" in block
    assert "authenticated `az` CLI" in block
    assert "Resource Discovery for Azure (RDfA)" in block
    assert "OpenAI, OpenRouter, or Anthropic" in block


def test_heroku_advertises_live_discovery_before_workspace_scan() -> None:
    discover = read("heroku-to-aws/references/phases/discover/discover.md")

    orientation = discover.index("**Fresh runs only:**")
    source_scan = discover.index("**When to offer capture:**")

    assert orientation < source_scan
    block = discover[orientation:source_scan]
    assert "Terraform is optional" in block
    assert "authenticated Heroku CLI" in block
    assert "resources outside Terraform" in block


def test_llm_migration_advertises_usage_apis_before_requesting_source() -> None:
    skill = read("llm-to-bedrock/SKILL.md")

    notice = skill.index("Before using a path from `$ARGUMENTS` or asking for one")
    source_question = skill.index('"Where is your source code? Enter a local path or GitHub URL."')

    assert notice < source_question
    block = skill[notice:source_question]
    assert "OpenAI, OpenRouter, and direct Anthropic" in block
    assert "provider-specific consent screen" in block
    assert "identify call sites" in block


def test_named_ai_provider_is_enough_to_offer_usage_discovery() -> None:
    gcp = read("gcp-to-aws/references/phases/discover/discover.md")
    azure = read("azure-to-aws/references/phases/discover/discover.md")

    for discover in (gcp, azure):
        text = normalized(discover)
        assert "migration request names direct OpenAI" in text
        assert "migration request names OpenRouter" in text
        assert "migration request names direct Anthropic/Claude API use" in text


def test_gcp_billing_guidance_keeps_live_discovery_visible() -> None:
    paths = (
        "gcp-to-aws/references/phases/discover/discover-app-code.md",
        "gcp-to-aws/references/phases/design/design-billing.md",
        "gcp-to-aws/references/phases/estimate/estimate-billing.md",
        "gcp-to-aws/references/phases/generate/generate-billing.md",
        "gcp-to-aws/references/phases/generate/generate-artifacts-billing.md",
    )

    for path in paths:
        content = read(path)
        assert "live `gcloud` discovery" in content or "live gcloud discovery" in content


def test_changed_skill_descriptions_fit_repository_spec_limit() -> None:
    for skill in ("gcp-to-aws", "azure-to-aws", "heroku-to-aws", "llm-to-bedrock"):
        skill_file = SKILLS / skill / "SKILL.md"
        match = re.search(r'^description: "(.*)"$', skill_file.read_text(), re.MULTILINE)
        assert match is not None, f"missing single-line description in {skill_file}"
        assert len(match.group(1)) <= 1024, (
            f"{skill_file} description is {len(match.group(1))} chars"
        )
