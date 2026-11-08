"""Tests for iam_policy.py — scoped IAM policy generation."""
import json
import subprocess  # nosec B404 — test-only, inputs are hardcoded literals
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from iam_policy import (
    default_project_arn,
    foundation_model_arn,
    generate_policy,
    is_gpt6_cris_model,
    is_gpt54_55_cris_model,
    is_mantle_model,
    is_runtime_openai_cris_model,
    mantle_project_arn,
    inference_profile_arn,
    is_inference_profile,
    parse_targets,
    requires_default_project_grant,
)

REGION = "us-east-1"
ACCOUNT = "123456789012"


class TestIsInferenceProfile:
    def test_geo_prefix_us(self):
        assert is_inference_profile("us.anthropic.claude-sonnet-5")

    def test_geo_prefix_eu(self):
        assert is_inference_profile("eu.anthropic.claude-haiku-4-5-20251001-v1:0")

    def test_no_prefix(self):
        assert not is_inference_profile("anthropic.claude-haiku-4-5-20251001-v1:0")

    def test_amazon_model(self):
        assert not is_inference_profile("amazon.nova-lite-v1:0")


class TestArnGeneration:
    def test_foundation_model_arn(self):
        arn = foundation_model_arn("anthropic.claude-haiku-4-5-20251001-v1:0")
        assert arn == "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"

    def test_inference_profile_arn(self):
        arn = inference_profile_arn("us.anthropic.claude-sonnet-5", REGION, ACCOUNT)
        assert arn == f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/us.anthropic.claude-sonnet-5"


class TestGeneratePolicy:
    def test_single_foundation_model(self):
        policy = generate_policy(["anthropic.claude-haiku-4-5-20251001-v1:0"], REGION, ACCOUNT)
        assert policy["Version"] == "2012-10-17"
        stmt = policy["Statement"][0]
        assert stmt["Effect"] == "Allow"
        assert "bedrock:InvokeModel" in stmt["Action"]
        assert "bedrock:InvokeModelWithResponseStream" in stmt["Action"]
        assert len(stmt["Resource"]) == 1
        assert "foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0" in stmt["Resource"][0]

    def test_inference_profile_generates_dual_arns(self):
        policy = generate_policy(["us.anthropic.claude-sonnet-5"], REGION, ACCOUNT)
        resources = policy["Statement"][0]["Resource"]
        assert len(resources) == 2
        has_foundation = any("foundation-model/" in r for r in resources)
        has_profile = any("inference-profile/" in r for r in resources)
        assert has_foundation
        assert has_profile

    def test_mixed_models(self):
        models = [
            "us.anthropic.claude-sonnet-5",
            "amazon.nova-lite-v1:0",
        ]
        policy = generate_policy(models, REGION, ACCOUNT)
        resources = policy["Statement"][0]["Resource"]
        assert any("nova-lite" in r for r in resources)
        assert any("inference-profile/" in r for r in resources)

    def test_deduplicates_models(self):
        models = ["amazon.nova-lite-v1:0", "amazon.nova-lite-v1:0"]
        policy = generate_policy(models, REGION, ACCOUNT)
        resources = policy["Statement"][0]["Resource"]
        assert len(resources) == 1

    def test_empty_models(self):
        policy = generate_policy([], REGION, ACCOUNT)
        assert policy["Statement"][0]["Resource"] == []


class TestCLI:
    def test_stdout_output(self):
        result = subprocess.run(  # nosec B603
            [
                sys.executable, str(Path(__file__).parent / "iam_policy.py"),
                "--models", "amazon.nova-lite-v1:0",
                "--region", REGION,
                "--account-id", ACCOUNT,
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        policy = json.loads(result.stdout)
        assert policy["Statement"][0]["Sid"] == "BedrockInvokeModelScoped"

    def test_file_output(self, tmp_path):
        out = tmp_path / "policy.json"
        result = subprocess.run(  # nosec B603
            [
                sys.executable, str(Path(__file__).parent / "iam_policy.py"),
                "--models", "us.anthropic.claude-sonnet-5,amazon.nova-lite-v1:0",
                "--region", REGION,
                "--account-id", ACCOUNT,
                "--output", str(out),
            ],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        policy = json.loads(out.read_text())
        assert len(policy["Statement"][0]["Resource"]) == 3


def test_mantle_model_detection_excludes_gpt_oss():
    assert is_mantle_model("openai.gpt-5.6-terra") is True
    assert is_mantle_model("openai.gpt-5.5") is True
    assert is_mantle_model("openai.gpt-oss-120b-1:0") is False
    assert is_mantle_model("anthropic.claude-sonnet-4-6") is False


def test_is_mantle_model_gpt54_55_cris_ids_are_runtime_not_mantle():
    # GPT-5.4 / GPT-5.5 model cards (read 2026-11-06) list us./global. CRIS ids on
    # bedrock-runtime: the bare id needs bedrock-mantle:* actions, the prefixed id
    # needs bedrock:InvokeModel against the inference-profile ARN.
    assert is_mantle_model("openai.gpt-5.4") is True
    assert is_mantle_model("openai.gpt-5.5") is True
    assert is_mantle_model("us.openai.gpt-5.4") is False
    assert is_mantle_model("global.openai.gpt-5.4") is False
    assert is_mantle_model("us.openai.gpt-5.5") is False
    assert is_mantle_model("global.openai.gpt-5.5") is False


def test_is_mantle_model_matches_bare_gpt6_ids():
    assert is_mantle_model("openai.gpt-6-astra") is True
    assert is_mantle_model("openai.gpt-6-sol") is True
    assert is_mantle_model("openai.gpt-6-luna") is True
    assert is_mantle_model("openai.gpt-6.1-sol") is True
    assert is_mantle_model("us.openai.gpt-6-sol") is False
    assert is_mantle_model("openai.gpt-oss-120b-1:0") is False


def test_generate_policy_grants_mantle_actions_for_bare_gpt6():
    # A bare GPT-6 id must get the same mantle-only treatment as bare GPT-5.x —
    # no InvokeModel statement (there is no foundation-model ARN for it) and a
    # BedrockMantleInference statement granting bedrock-mantle:* actions.
    pol = generate_policy(["openai.gpt-6-sol"], "us-east-1", "123456789012")
    sids = {s["Sid"] for s in pol["Statement"]}
    assert "BedrockMantleInference" in sids
    assert "BedrockInvokeModelScoped" not in sids


def test_mantle_target_gets_mantle_actions_not_invoke_model():
    # Regression: the generated policy emitted only bedrock:InvokeModel against a
    # foundation-model ARN, which cannot authorize a mantle call — the migrated app
    # would deploy and immediately fail authorization.
    pol = generate_policy(["openai.gpt-5.6-terra"], "us-east-1", "111122223333")
    sids = {s["Sid"] for s in pol["Statement"]}
    assert "BedrockMantleInference" in sids
    assert "BedrockMantleCallWithBearerToken" in sids
    # An all-mantle run must NOT emit an InvokeModel statement with an empty
    # Resource list — that is an invalid IAM policy.
    assert "BedrockInvokeModelScoped" not in sids
    for s in pol["Statement"]:
        assert s.get("Resource"), s["Sid"]


def test_mantle_bearer_token_is_scoped_to_star():
    # AWS does not support narrowing CallWithBearerToken; it must be "*".
    pol = generate_policy(["openai.gpt-5.5"], "us-east-1", "111122223333")
    bearer = [s for s in pol["Statement"] if s["Sid"] == "BedrockMantleCallWithBearerToken"][0]
    assert bearer["Resource"] == "*"
    assert bearer["Action"] == ["bedrock-mantle:CallWithBearerToken"]


def test_mantle_inference_scoped_to_account_and_region():
    pol = generate_policy(["openai.gpt-5.5"], "us-west-2", "999988887777")
    inf = [s for s in pol["Statement"] if s["Sid"] == "BedrockMantleInference"][0]
    assert inf["Resource"] == "arn:aws:bedrock-mantle:us-west-2:999988887777:project/*"


def test_mixed_targets_emit_both_runtime_and_mantle_statements():
    pol = generate_policy(
        ["openai.gpt-5.6-luna", "us.anthropic.claude-sonnet-4-6"], "us-east-1", "111122223333")
    sids = [s["Sid"] for s in pol["Statement"]]
    assert "BedrockInvokeModelScoped" in sids
    assert "BedrockMantleInference" in sids
    invoke = [s for s in pol["Statement"] if s["Sid"] == "BedrockInvokeModelScoped"][0]
    # The mantle model must not leak into the InvokeModel resource list.
    assert not any("gpt-5" in r for r in invoke["Resource"])


def test_gpt_oss_stays_on_the_runtime_path():
    pol = generate_policy(["openai.gpt-oss-120b-1:0"], "us-east-1", "111122223333")
    sids = {s["Sid"] for s in pol["Statement"]}
    assert sids == {"BedrockInvokeModelScoped"}


def test_astra_bare_id_grants_mantle_project_and_bearer_actions():
    assert is_mantle_model("openai.gpt-6-astra")
    statements = {s["Sid"]: s for s in
                  generate_policy(["openai.gpt-6-astra"], "us-west-2", ACCOUNT)["Statement"]}
    assert set(statements) == {"BedrockMantleInference", "BedrockMantleCallWithBearerToken"}
    assert statements["BedrockMantleInference"]["Resource"] == (
        f"arn:aws:bedrock-mantle:us-west-2:{ACCOUNT}:project/*")
    assert "bedrock-mantle:CreateInference" in statements["BedrockMantleInference"]["Action"]
    assert statements["BedrockMantleCallWithBearerToken"]["Resource"] == "*"


@pytest.mark.parametrize("prefix", ["us", "global"])
def test_astra_cris_id_grants_runtime_foundation_and_profile_arns(prefix):
    mid = f"{prefix}.openai.gpt-6-astra"
    assert not is_mantle_model(mid)
    statements = generate_policy([mid], "us-west-2", ACCOUNT)["Statement"]
    assert len(statements) == 2
    assert statements[0]["Action"] == ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    assert set(statements[0]["Resource"]) == {
        "arn:aws:bedrock:*::foundation-model/openai.gpt-6-astra",
        f"arn:aws:bedrock:us-west-2:{ACCOUNT}:inference-profile/{mid}",
        f"arn:aws:bedrock:us-west-2:{ACCOUNT}:project/default",
    }
    # Invoking through a CRIS profile also needs GetInferenceProfile on the profile only
    # (inference-profiles-prereq.html, read 2026-11-07).
    assert statements[1]["Sid"] == "BedrockGetInferenceProfile"
    assert statements[1]["Action"] == ["bedrock:GetInferenceProfile"]
    assert statements[1]["Resource"] == [f"arn:aws:bedrock:us-west-2:{ACCOUNT}:inference-profile/{mid}"]


def test_runtime_messages_profile_gets_invoke_and_get_inference_profile():
    # A runtime_messages target (Anthropic SDK on bedrock-runtime /anthropic) is a plain
    # CRIS profile for IAM: InvokeModel* on profile + foundation model, GetInferenceProfile
    # on the profile, and no Mantle statement.
    mid = "global.anthropic.claude-sonnet-5"
    statements = generate_policy([mid], "us-west-2", ACCOUNT)["Statement"]
    assert [s["Sid"] for s in statements] == ["BedrockInvokeModelScoped", "BedrockGetInferenceProfile"]
    assert set(statements[0]["Resource"]) == {
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-5",
        f"arn:aws:bedrock:us-west-2:{ACCOUNT}:inference-profile/{mid}",
    }
    assert statements[1]["Resource"] == [f"arn:aws:bedrock:us-west-2:{ACCOUNT}:inference-profile/{mid}"]


def test_bare_foundation_model_emits_no_get_inference_profile():
    statements = generate_policy(["anthropic.claude-haiku-4-5-20251001-v1:0"], REGION, ACCOUNT)["Statement"]
    assert [s["Sid"] for s in statements] == ["BedrockInvokeModelScoped"]


class TestGpt6CrisProjectArn:
    """Finding 1: a GPT-6 CRIS id's model card 'Call the model' section grants
    InvokeModel on both the inference-profile ARN AND the default project ARN."""

    def test_is_gpt6_cris_model_matches_geo_prefixed_gpt6_ids(self):
        assert is_gpt6_cris_model("global.openai.gpt-6-sol")
        assert is_gpt6_cris_model("us.openai.gpt-6-astra")
        assert is_gpt6_cris_model("us.openai.gpt-6.1-sol")
        assert is_gpt6_cris_model("global.openai.gpt-6-luna")

    def test_is_gpt6_cris_model_excludes_bare_and_non_gpt6(self):
        assert not is_gpt6_cris_model("openai.gpt-6-sol")  # bare — mantle, not CRIS
        assert not is_gpt6_cris_model("us.anthropic.claude-sonnet-5")
        assert not is_gpt6_cris_model("us.openai.gpt-5.6-sol")

    @pytest.mark.parametrize(
        "model_id",
        [
            "global.openai.gpt-6-sol",
            "us.openai.gpt-6-astra",
            "us.openai.gpt-6.1-sol",
            "global.openai.gpt-6-luna",
        ],
    )
    def test_generate_policy_grants_project_default_for_gpt6_cris(self, model_id):
        pol = generate_policy([model_id], REGION, ACCOUNT)
        resources = pol["Statement"][0]["Resource"]
        assert default_project_arn(REGION, ACCOUNT) in resources
        assert any("inference-profile/" in r for r in resources)

    def test_non_gpt6_runtime_id_does_not_get_project_default(self):
        pol = generate_policy(["us.anthropic.claude-sonnet-5"], REGION, ACCOUNT)
        resources = pol["Statement"][0]["Resource"]
        assert default_project_arn(REGION, ACCOUNT) not in resources

    def test_bare_gpt6_mantle_id_still_yields_no_invoke_model_statement(self):
        pol = generate_policy(["openai.gpt-6-sol"], REGION, ACCOUNT)
        sids = {s["Sid"] for s in pol["Statement"]}
        assert "BedrockInvokeModelScoped" not in sids


_GPT54_55_CRIS_SHORT_IDS = [
    "us.openai.gpt-5.4",
    "global.openai.gpt-5.4",
    "us.openai.gpt-5.5",
    "global.openai.gpt-5.5",
]


class TestGpt54Gpt55CrisProjectArn:
    """PR 583 review: the GPT-5.4 / GPT-5.5 model cards (read 2026-11-07,
    https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-54.html
    and ...-gpt-55.html) say the IAM identity "also needs bedrock:InvokeModel on
    your account's default project ... in addition to the inference profile" for
    their us./global. runtime ids. The grant must cover exactly those ids."""

    @pytest.mark.parametrize("model_id", _GPT54_55_CRIS_SHORT_IDS)
    def test_predicates_match_short_ids(self, model_id):
        assert is_gpt54_55_cris_model(model_id)
        assert requires_default_project_grant(model_id)
        assert not is_gpt6_cris_model(model_id)

    @pytest.mark.parametrize("model_id", _GPT54_55_CRIS_SHORT_IDS)
    def test_predicates_match_system_profile_arns(self, model_id):
        arn = f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/{model_id}"
        assert is_gpt54_55_cris_model(arn)
        assert requires_default_project_grant(arn)

    @pytest.mark.parametrize(
        "model_id",
        [
            "openai.gpt-5.4",  # bare — mantle, not CRIS
            "openai.gpt-5.5",
            "us.anthropic.claude-sonnet-5",
            f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/us.anthropic.claude-sonnet-5",
        ],
    )
    def test_predicates_exclude_bare_mantle_and_unrelated_ids(self, model_id):
        assert not is_gpt54_55_cris_model(model_id)
        assert not requires_default_project_grant(model_id)

    @pytest.mark.parametrize(
        "model_id",
        [
            "us.openai.gpt-5.6-sol",  # GPT-5.6 cards (read 2026-11-07) DO add the grant
            "global.openai.gpt-5.6-terra",
            "us.openai.gpt-5.4-pro",  # not a published id, but the id FORM is a runtime GPT CRIS id
        ],
    )
    def test_family_predicate_excludes_other_gpt_ids_but_id_form_grant_covers_them(self, model_id):
        # The GPT-5.4 / GPT-5.5 family predicate stays exact; the default-project grant
        # is decided by id form (any runtime GPT CRIS id), not by this family predicate.
        assert not is_gpt54_55_cris_model(model_id)
        assert requires_default_project_grant(model_id)

    @pytest.mark.parametrize("model_id", _GPT54_55_CRIS_SHORT_IDS)
    def test_generate_policy_grants_project_default_for_short_id(self, model_id):
        pol = generate_policy([model_id], REGION, ACCOUNT)
        # A CRIS profile also carries the GetInferenceProfile statement (inference-profiles-prereq.html).
        assert [s["Sid"] for s in pol["Statement"]] == ["BedrockInvokeModelScoped", "BedrockGetInferenceProfile"]
        base = model_id.split(".", 1)[1]
        assert set(pol["Statement"][0]["Resource"]) == {
            f"arn:aws:bedrock:*::foundation-model/{base}",
            f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/{model_id}",
            default_project_arn(REGION, ACCOUNT),
        }

    @pytest.mark.parametrize("model_id", _GPT54_55_CRIS_SHORT_IDS)
    def test_generate_policy_grants_project_default_for_profile_arn(self, model_id):
        arn = f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/{model_id}"
        pol = generate_policy([arn], REGION, ACCOUNT)
        resources = pol["Statement"][0]["Resource"]
        assert arn in resources
        assert default_project_arn(REGION, ACCOUNT) in resources

    @pytest.mark.parametrize("model_id", ["openai.gpt-5.4", "openai.gpt-5.5"])
    def test_bare_mantle_id_gets_mantle_statements_and_no_project_default(self, model_id):
        pol = generate_policy([model_id], REGION, ACCOUNT)
        sids = {s["Sid"] for s in pol["Statement"]}
        assert "BedrockInvokeModelScoped" not in sids
        assert "BedrockMantleInference" in sids
        assert default_project_arn(REGION, ACCOUNT) not in json.dumps(pol)

    @pytest.mark.parametrize(
        "model_id",
        ["us.anthropic.claude-sonnet-5", "global.anthropic.claude-opus-5-5", "us.amazon.nova-pro-v1:0"],
    )
    def test_unrelated_runtime_ids_do_not_get_project_default(self, model_id):
        pol = generate_policy([model_id], REGION, ACCOUNT)
        resources = pol["Statement"][0]["Resource"]
        assert default_project_arn(REGION, ACCOUNT) not in resources
        assert len(resources) == 2

    def test_mixed_run_adds_project_default_once(self):
        pol = generate_policy(
            ["us.openai.gpt-5.4", "us.anthropic.claude-sonnet-5"], REGION, ACCOUNT
        )
        resources = pol["Statement"][0]["Resource"]
        assert resources.count(default_project_arn(REGION, ACCOUNT)) == 1


# Every runtime OpenAI-compatible target, by id form (PR 585 review, finding 1).
# Public basis, read 2026-11-07: inference-responses-api.html ("Permissions": a
# Responses request authorizes bedrock:InvokeModel on the inference target AND on
# the account's default project) and the GPT-5.6 Sol / Terra / Luna cards, which
# attach the same note to their runtime CRIS ids (in. exists for Terra and Luna).
_RUNTIME_GPT_CRIS_IDS = [
    "us.openai.gpt-5.6-sol",
    "global.openai.gpt-5.6-sol",
    "us.openai.gpt-5.6-terra",
    "in.openai.gpt-5.6-terra",
    "global.openai.gpt-5.6-terra",
    "us.openai.gpt-5.6-luna",
    "in.openai.gpt-5.6-luna",
    "global.openai.gpt-5.6-luna",
    "us.openai.gpt-6-astra",
    "global.openai.gpt-6-sol",
    "us.openai.gpt-6.1-sol",
    "us.openai.gpt-5.4",
    "global.openai.gpt-5.5",
    f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/in.openai.gpt-5.6-terra",
    f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/global.openai.gpt-5.6-sol",
    f"arn:aws:bedrock:{REGION}:{ACCOUNT}:inference-profile/us.openai.gpt-5.5",
]


class TestDefaultProjectGrantByIdFormAndApi:
    def _invoke_resources(self, pol):
        return {s["Sid"]: s for s in pol["Statement"]}["BedrockInvokeModelScoped"]["Resource"]

    @pytest.mark.parametrize("model_id", _RUNTIME_GPT_CRIS_IDS)
    def test_runtime_gpt_cris_id_form_is_recognized(self, model_id):
        assert is_inference_profile(model_id)
        assert is_runtime_openai_cris_model(model_id)
        assert not is_mantle_model(model_id)

    @pytest.mark.parametrize("model_id", _RUNTIME_GPT_CRIS_IDS)
    @pytest.mark.parametrize("runtime_api", [None, "responses", "chat_completions"])
    def test_responses_and_chat_targets_emit_project_default(self, model_id, runtime_api):
        pol = generate_policy([model_id], REGION, ACCOUNT, runtime_api=runtime_api)
        resources = self._invoke_resources(pol)
        short = model_id.rsplit("/", 1)[-1]
        base = short.split(".", 1)[1]
        assert set(resources) == {
            f"arn:aws:bedrock:*::foundation-model/{base}",
            inference_profile_arn(model_id, REGION, ACCOUNT),
            default_project_arn(REGION, ACCOUNT),
        }
        assert [s["Sid"] for s in pol["Statement"]] == ["BedrockInvokeModelScoped", "BedrockGetInferenceProfile"]

    @pytest.mark.parametrize("model_id", ["us.openai.gpt-6-astra", "in.openai.gpt-5.6-terra", "us.openai.gpt-5.4"])
    def test_converse_only_route_emits_no_project_default(self, model_id):
        # inference-prereq.html (read 2026-11-07): Converse through a profile needs
        # bedrock:InvokeModel* on the target + bedrock:GetInferenceProfile; the project
        # authorization belongs to Responses creation.
        pol = generate_policy([model_id], REGION, ACCOUNT, runtime_api="converse")
        resources = self._invoke_resources(pol)
        assert default_project_arn(REGION, ACCOUNT) not in resources
        assert len(resources) == 2
        assert not requires_default_project_grant(model_id, "converse")

    @pytest.mark.parametrize("model_id", ["openai.gpt-5.6-terra", "openai.gpt-5.6-sol", "openai.gpt-6-sol", "openai.gpt-5.5"])
    @pytest.mark.parametrize("runtime_api", [None, "responses", "chat_completions"])
    def test_bare_mantle_id_never_gets_project_default(self, model_id, runtime_api):
        assert not is_runtime_openai_cris_model(model_id)
        pol = generate_policy([model_id], REGION, ACCOUNT, runtime_api=runtime_api)
        sids = {s["Sid"] for s in pol["Statement"]}
        assert "BedrockInvokeModelScoped" not in sids
        assert "BedrockMantleInference" in sids
        assert default_project_arn(REGION, ACCOUNT) not in json.dumps(pol)

    @pytest.mark.parametrize("model_id", [
        "global.anthropic.claude-sonnet-5",
        "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        "anthropic.claude-opus-5-5",  # runtime in-region form (eu-west-2)
        "openai.gpt-oss-120b-1:0",
        "us.amazon.nova-lite-v1:0",
    ])
    @pytest.mark.parametrize("runtime_api", [None, "responses", "chat_completions", "messages", "converse"])
    def test_anthropic_oss_and_other_runtime_ids_never_get_project_default(self, model_id, runtime_api):
        assert not is_runtime_openai_cris_model(model_id)
        pol = generate_policy([model_id], "eu-west-2", ACCOUNT, runtime_api=runtime_api)
        assert default_project_arn("eu-west-2", ACCOUNT) not in self._invoke_resources(pol)

    def test_mixed_messages_plan_with_gpt_secondary_grants_project_once(self):
        # Chat/Responses decides the grant per policy call; the Anthropic primary never
        # contributes it and the single GPT target adds it exactly once.
        pol = generate_policy(["global.anthropic.claude-sonnet-5", "us.openai.gpt-5.6-sol"],
                              REGION, ACCOUNT, runtime_api="chat_completions")
        resources = self._invoke_resources(pol)
        assert resources.count(default_project_arn(REGION, ACCOUNT)) == 1
        assert "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-5" in resources

    def test_unknown_runtime_api_is_rejected(self):
        with pytest.raises(ValueError, match="Unknown runtime API"):
            generate_policy(["us.openai.gpt-5.6-sol"], REGION, ACCOUNT, runtime_api="invoke")

    def test_us_gov_partition_project_arn(self):
        pol = generate_policy(["us-gov.openai.gpt-5.6-terra"], "us-gov-west-1", ACCOUNT, runtime_api="responses")
        resources = self._invoke_resources(pol)
        assert f"arn:aws-us-gov:bedrock:us-gov-west-1:{ACCOUNT}:project/default" in resources
        assert f"arn:aws-us-gov:bedrock:us-gov-west-1:{ACCOUNT}:inference-profile/us-gov.openai.gpt-5.6-terra" in resources

    @pytest.mark.parametrize("runtime_api,expected", [
        ("responses", True), ("chat_completions", True), ("converse", False),
    ])
    def test_cli_runtime_api_flag_controls_project_default(self, runtime_api, expected):
        result = subprocess.run(  # nosec B603
            [sys.executable, str(Path(__file__).parent / "iam_policy.py"),
             "--models", "global.openai.gpt-5.6-sol", "--region", REGION, "--account-id", ACCOUNT,
             "--runtime-api", runtime_api],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        policy = json.loads(result.stdout)
        assert (default_project_arn(REGION, ACCOUNT) in policy["Statement"][0]["Resource"]) is expected


class TestMantleMessagesLaneIsRefused:
    """PR 585 review, finding 3: a `mantle_messages` plan (Workspaces selector) has no
    execution lane here, and a bare Sonnet id on that path must not receive runtime
    `bedrock:InvokeModel*` from the id-only helper."""

    def test_generate_policy_raises_for_mantle_messages_path(self):
        with pytest.raises(ValueError, match="mantle_messages.*deferred execution lane"):
            generate_policy(["anthropic.claude-sonnet-5"], REGION, ACCOUNT,
                            runtime_api="messages", migration_path="mantle_messages")

    def test_runtime_messages_path_still_emits_runtime_policy(self):
        pol = generate_policy(["global.anthropic.claude-sonnet-5"], REGION, ACCOUNT,
                              runtime_api="messages", migration_path="runtime_messages")
        assert [s["Sid"] for s in pol["Statement"]] == ["BedrockInvokeModelScoped", "BedrockGetInferenceProfile"]

    def test_cli_mantle_messages_exits_with_structured_reason(self):
        result = subprocess.run(  # nosec B603
            [sys.executable, str(Path(__file__).parent / "iam_policy.py"),
             "--models", "anthropic.claude-sonnet-5", "--region", REGION, "--account-id", ACCOUNT,
             "--runtime-api", "messages", "--migration-path", "mantle_messages"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        out = json.loads(result.stdout)
        assert out["ok"] is False
        assert out["reason"] == "unsupported_lane"
        assert out["lane"] == "mantle_messages"
        assert "workspaces" in out["detail"]
        assert "bedrock:InvokeModel" not in result.stdout.replace(out["detail"], "")


class TestPerRowTargetApis:
    """PR 585 review round 1, B1: the §6.4 recipe used to pass the primary's single
    `--runtime-api` for every id, so a runtime_messages plan with a GPT Chat/Responses
    secondary lost that secondary's default-project grant. `--target ID=API` carries
    each row's own API, exactly like preflight."""

    CLAUDE = "global.anthropic.claude-sonnet-5"
    GPT = "us.openai.gpt-6-astra"
    NOVA = "us.amazon.nova-lite-v1:0"
    EMBED = "amazon.titan-embed-text-v2:0"

    def _invoke_resources(self, pol):
        return {s["Sid"]: s for s in pol["Statement"]}["BedrockInvokeModelScoped"]["Resource"]

    def test_plan_wide_messages_api_is_the_regression_the_per_row_form_fixes(self):
        # The reviewer's spot-check: one plan-wide `messages` drops the GPT secondary's grant.
        pol = generate_policy([self.CLAUDE, self.GPT], REGION, ACCOUNT,
                              runtime_api="messages", migration_path="runtime_messages")
        assert default_project_arn(REGION, ACCOUNT) not in self._invoke_resources(pol)

    def test_claude_messages_plus_gpt_chat_grants_project_default_exactly_once(self):
        pol = generate_policy([self.CLAUDE, self.GPT], REGION, ACCOUNT,
                              migration_path="runtime_messages",
                              target_apis={self.CLAUDE: "messages", self.GPT: "chat_completions"})
        resources = self._invoke_resources(pol)
        assert resources.count(default_project_arn(REGION, ACCOUNT)) == 1
        assert "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-5" in resources
        assert inference_profile_arn(self.GPT, REGION, ACCOUNT) in resources
        assert [s["Sid"] for s in pol["Statement"]] == ["BedrockInvokeModelScoped", "BedrockGetInferenceProfile"]

    @pytest.mark.parametrize("gpt_api", ["responses", "chat_completions"])
    def test_gpt_secondary_grant_follows_its_own_row_api(self, gpt_api):
        pol = generate_policy([self.CLAUDE, "in.openai.gpt-5.6-terra"], REGION, ACCOUNT,
                              target_apis={self.CLAUDE: "messages", "in.openai.gpt-5.6-terra": gpt_api})
        assert default_project_arn(REGION, ACCOUNT) in self._invoke_resources(pol)

    def test_claude_messages_plus_nova_converse_plus_embeddings_emits_no_project_default(self):
        pol = generate_policy([self.CLAUDE, self.NOVA, self.EMBED], REGION, ACCOUNT,
                              migration_path="runtime_messages",
                              target_apis={self.CLAUDE: "messages", self.NOVA: "converse", self.EMBED: "invoke"})
        resources = self._invoke_resources(pol)
        assert default_project_arn(REGION, ACCOUNT) not in resources
        assert f"arn:aws:bedrock:*::foundation-model/{self.EMBED}" in resources

    def test_gpt_row_on_converse_beside_a_gpt_row_on_chat_grants_once(self):
        # Per-row decision, not per-family: the same policy call grants the Chat row and
        # withholds for the Converse row; one project ARN results.
        chat, conv = "us.openai.gpt-5.4", "global.openai.gpt-5.5"
        pol = generate_policy([chat, conv], REGION, ACCOUNT,
                              target_apis={chat: "chat_completions", conv: "converse"})
        assert self._invoke_resources(pol).count(default_project_arn(REGION, ACCOUNT)) == 1
        assert requires_default_project_grant(chat, "chat_completions")
        assert not requires_default_project_grant(conv, "converse")

    def test_row_api_overrides_plan_wide_runtime_api(self):
        pol = generate_policy([self.CLAUDE, self.GPT], REGION, ACCOUNT, runtime_api="messages",
                              target_apis={self.GPT: "chat_completions"})
        assert default_project_arn(REGION, ACCOUNT) in self._invoke_resources(pol)

    def test_unknown_row_api_fails_closed(self):
        with pytest.raises(ValueError, match="Unknown runtime API 'grpc'"):
            generate_policy([self.GPT], REGION, ACCOUNT, target_apis={self.GPT: "grpc"})

    def test_parse_targets_builds_pairs_from_repeated_and_comma_joined_specs(self):
        assert parse_targets([f"{self.CLAUDE}=messages", f"{self.GPT}=chat_completions,{self.EMBED}=invoke"]) == [
            (self.CLAUDE, "messages"), (self.GPT, "chat_completions"), (self.EMBED, "invoke"),
        ]

    @pytest.mark.parametrize("spec", ["us.openai.gpt-6-astra", "us.openai.gpt-6-astra=", "us.openai.gpt-6-astra=grpc"])
    def test_parse_targets_fails_closed_on_missing_or_unknown_api(self, spec):
        with pytest.raises(ValueError, match="Every --target must be"):
            parse_targets([spec])

    def test_cli_target_pairs_grant_the_gpt_secondary_under_a_messages_primary(self):
        result = subprocess.run(  # nosec B603
            [sys.executable, str(Path(__file__).parent / "iam_policy.py"),
             "--target", f"{self.CLAUDE}=messages", "--target", f"{self.GPT}=chat_completions",
             "--region", REGION, "--account-id", ACCOUNT, "--migration-path", "runtime_messages"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        policy = json.loads(result.stdout)
        assert policy["Statement"][0]["Resource"].count(default_project_arn(REGION, ACCOUNT)) == 1

    def test_cli_target_with_unknown_api_exits_with_unknown_runtime_api(self):
        result = subprocess.run(  # nosec B603
            [sys.executable, str(Path(__file__).parent / "iam_policy.py"),
             "--target", f"{self.CLAUDE}=messages", "--target", self.GPT,
             "--region", REGION, "--account-id", ACCOUNT],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        out = json.loads(result.stdout)
        assert out["ok"] is False and out["reason"] == "unknown_runtime_api"
        assert "<missing>" in out["detail"]
        assert "Statement" not in result.stdout

    def test_cli_models_and_target_are_mutually_exclusive(self):
        result = subprocess.run(  # nosec B603
            [sys.executable, str(Path(__file__).parent / "iam_policy.py"),
             "--models", self.GPT, "--target", f"{self.GPT}=responses",
             "--region", REGION, "--account-id", ACCOUNT],
            capture_output=True, text=True,
        )
        assert result.returncode == 2
        assert "not allowed with" in result.stderr
