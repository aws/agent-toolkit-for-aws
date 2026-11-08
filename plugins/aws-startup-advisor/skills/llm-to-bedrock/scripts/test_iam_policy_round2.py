"""PR 585 review round 2 — iam_policy.py helper behaviour.

Finding 1: the report's §6.4 recipe re-read `aws-design-ai.json`'s ORIGINAL ids, so a C4
target change (Sol → Terra, recorded in `resolved_model_overrides` and carried by the
validated analysis `target_models`) emitted Sol's permissions and omitted Terra's profile.
`validated_target_pairs` joins each row's API to the final validated mapping.

Finding 2: a source app that keeps `client.responses.retrieve(id)` needs `bedrock:GetInvoke`
on `project/default` — retrieving / canceling / deleting a stored response authorizes
`bedrock:GetInvoke` / `CancelInvoke` / `DeleteInvoke` on the project, separately from the
`bedrock:InvokeModel` creation needs (public basis, read 2026-11-08:
https://docs.aws.amazon.com/bedrock/latest/userguide/inference-responses-api.html,
"Permissions"). Converse, Anthropic Messages and Chat Completions rows never get them.
"""
import json
import subprocess  # nosec B404 — test-only, inputs are hardcoded literals
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from iam_policy import (  # noqa: E402
    STORED_RESPONSE_OPS,
    default_project_arn,
    generate_policy,
    inference_profile_arn,
    parse_stored_response_ops,
    parse_targets,
    target_apis_by_id,
    validated_target_pairs,
)

REGION = "us-east-1"
ACCOUNT = "123456789012"
PROJECT = default_project_arn(REGION, ACCOUNT)
SOL, TERRA = "us.openai.gpt-5.6-sol", "us.openai.gpt-5.6-terra"
CLAUDE = "global.anthropic.claude-sonnet-5"
EMBED = "amazon.titan-embed-text-v2:0"


def _sids(pol):
    return [s["Sid"] for s in pol["Statement"]]


def _stmt(pol, sid):
    return {s["Sid"]: s for s in pol["Statement"]}[sid]


# --- Finding 1: validated mapping wins over the design row's original id ---

class TestValidatedTargetPairs:
    DESIGN_ROWS = [
        {"source_model_id": "gpt-5.6-sol", "aws_model_id": SOL, "required_client_api": "responses"},
        {"source_model_id": "text-embedding-3-small", "aws_model_id": EMBED, "required_client_api": "invoke"},
    ]

    def test_c4_target_change_emits_the_new_profile_and_not_the_old(self):
        # The reviewer's case: C4 changed Sol → Terra; aws-design-ai.json still says Sol.
        validated = [f"gpt-5.6-sol -> {TERRA}", f"text-embedding-3-small -> {EMBED}"]
        pairs = validated_target_pairs(self.DESIGN_ROWS, validated)
        assert pairs == [(TERRA, "responses"), (EMBED, "invoke")]
        pol = generate_policy([m for m, _ in pairs], REGION, ACCOUNT, target_apis=target_apis_by_id(pairs))
        resources = _stmt(pol, "BedrockInvokeModelScoped")["Resource"]
        assert inference_profile_arn(TERRA, REGION, ACCOUNT) in resources
        assert "arn:aws:bedrock:*::foundation-model/openai.gpt-5.6-terra" in resources
        assert PROJECT in resources, "the Terra Responses row keeps the default-project grant"
        assert not any("gpt-5.6-sol" in r for r in resources), "the original Sol id must not be granted"
        assert _stmt(pol, "BedrockGetInferenceProfile")["Resource"] == [inference_profile_arn(TERRA, REGION, ACCOUNT)]

    def test_unchanged_mapping_reproduces_the_design_rows(self):
        validated = {"gpt-5.6-sol": SOL, "text-embedding-3-small": EMBED}
        assert validated_target_pairs(self.DESIGN_ROWS, validated) == [(SOL, "responses"), (EMBED, "invoke")]

    def test_primary_api_fills_only_the_primary_row_without_an_api(self):
        rows = [{"source_model": "gpt-5.6-sol", "aws_model_id": SOL},
                {"source_model": "claude-sonnet-4-5", "aws_model_id": CLAUDE, "required_client_api": "messages"}]
        pairs = validated_target_pairs(rows, [f"gpt-5.6-sol -> {TERRA}", f"claude-sonnet-4-5 -> {CLAUDE}"],
                                       primary_model_id=TERRA, primary_api="chat_completions")
        assert pairs == [(TERRA, "chat_completions"), (CLAUDE, "messages")]

    def test_non_primary_row_without_an_api_fails_closed(self):
        rows = [{"source_model": "gpt-5.6-sol", "aws_model_id": SOL, "required_client_api": "responses"},
                {"source_model": "claude-sonnet-4-5", "aws_model_id": CLAUDE}]
        with pytest.raises(ValueError, match="records no required_client_api"):
            validated_target_pairs(rows, [f"gpt-5.6-sol -> {SOL}", f"claude-sonnet-4-5 -> {CLAUDE}"],
                                   primary_model_id=SOL, primary_api="responses")

    def test_row_without_a_validated_entry_fails_closed_instead_of_using_the_design_id(self):
        with pytest.raises(ValueError, match="no entry in the validated target mapping"):
            validated_target_pairs(self.DESIGN_ROWS, [f"gpt-5.6-sol -> {TERRA}"])

    def test_malformed_mapping_entry_is_rejected(self):
        with pytest.raises(ValueError, match="is not '<source-model> -> <bedrock-model>'"):
            validated_target_pairs(self.DESIGN_ROWS[:1], ["gpt-5.6-sol"])

    def test_pairs_round_trip_through_the_cli_target_form(self):
        pairs = validated_target_pairs(self.DESIGN_ROWS, [f"gpt-5.6-sol -> {TERRA}", f"text-embedding-3-small -> {EMBED}"])
        assert parse_targets([f"{m}={a}" for m, a in pairs]) == pairs


# --- Finding 2: retained stored-response ops get project-scoped GetInvoke / CancelInvoke / DeleteInvoke ---

class TestStoredResponseOps:
    def test_retained_retrieve_adds_get_invoke_on_the_default_project_only(self):
        pol = generate_policy([SOL], REGION, ACCOUNT, target_apis={SOL: "responses"},
                              stored_response_ops=["retrieve"])
        assert _sids(pol) == ["BedrockInvokeModelScoped", "BedrockGetInferenceProfile", "BedrockStoredResponseOps"]
        stmt = _stmt(pol, "BedrockStoredResponseOps")
        assert stmt["Action"] == ["bedrock:GetInvoke"]
        assert stmt["Resource"] == [PROJECT]
        # Creation still authorizes InvokeModel on the target AND the project.
        assert PROJECT in _stmt(pol, "BedrockInvokeModelScoped")["Resource"]

    def test_only_the_retained_ops_are_granted(self):
        pol = generate_policy([SOL], REGION, ACCOUNT, target_apis={SOL: "responses"},
                              stored_response_ops=["retrieve", "delete"])
        assert _stmt(pol, "BedrockStoredResponseOps")["Action"] == ["bedrock:DeleteInvoke", "bedrock:GetInvoke"]
        full = generate_policy([SOL], REGION, ACCOUNT, target_apis={SOL: "responses"},
                               stored_response_ops=["retrieve", "cancel", "delete"])
        assert _stmt(full, "BedrockStoredResponseOps")["Action"] == sorted(STORED_RESPONSE_OPS.values())

    def test_no_ops_means_no_stored_response_statement(self):
        pol = generate_policy([SOL], REGION, ACCOUNT, target_apis={SOL: "responses"})
        assert "BedrockStoredResponseOps" not in _sids(pol)
        assert not any("GetInvoke" in a for s in pol["Statement"] for a in s["Action"])

    @pytest.mark.parametrize("target_apis,ids", [
        ({CLAUDE: "messages"}, [CLAUDE]),
        ({"us.amazon.nova-lite-v1:0": "converse"}, ["us.amazon.nova-lite-v1:0"]),
        ({SOL: "converse"}, [SOL]),
        ({SOL: "chat_completions"}, [SOL]),
        ({CLAUDE: "messages", EMBED: "invoke"}, [CLAUDE, EMBED]),
    ])
    def test_converse_messages_chat_and_embedding_rows_never_get_the_grant(self, target_apis, ids):
        with pytest.raises(ValueError, match="stored-response ops .* no --target row is a runtime GPT CRIS id on the `responses` API"):
            generate_policy(ids, REGION, ACCOUNT, target_apis=target_apis, stored_response_ops=["retrieve"])

    def test_mixed_plan_grants_once_for_the_responses_row_beside_a_messages_primary(self):
        pol = generate_policy([CLAUDE, SOL], REGION, ACCOUNT, migration_path="runtime_messages",
                              target_apis={CLAUDE: "messages", SOL: "responses"}, stored_response_ops=["retrieve"])
        assert _stmt(pol, "BedrockStoredResponseOps") == {
            "Sid": "BedrockStoredResponseOps", "Effect": "Allow",
            "Action": ["bedrock:GetInvoke"], "Resource": [PROJECT]}

    def test_bare_mantle_id_on_responses_never_gets_runtime_get_invoke(self):
        with pytest.raises(ValueError, match="stored-response ops"):
            generate_policy(["openai.gpt-5.6-sol"], REGION, ACCOUNT, target_apis={"openai.gpt-5.6-sol": "responses"},
                            stored_response_ops=["retrieve"])

    def test_legacy_models_form_needs_an_explicit_responses_api(self):
        pol = generate_policy([SOL], REGION, ACCOUNT, runtime_api="responses", stored_response_ops=["retrieve"])
        assert _stmt(pol, "BedrockStoredResponseOps")["Action"] == ["bedrock:GetInvoke"]
        with pytest.raises(ValueError, match="stored-response ops"):
            generate_policy([SOL], REGION, ACCOUNT, stored_response_ops=["retrieve"])  # id-only: API unknown

    def test_unknown_op_fails_closed(self):
        with pytest.raises(ValueError, match="Unknown stored-response op 'list'"):
            generate_policy([SOL], REGION, ACCOUNT, target_apis={SOL: "responses"}, stored_response_ops=["list"])
        with pytest.raises(ValueError, match="Every --stored-response-ops value must be"):
            parse_stored_response_ops(["retrieve,list"])

    def test_parse_stored_response_ops_dedupes_and_keeps_order(self):
        assert parse_stored_response_ops(["retrieve,cancel", "retrieve", " delete "]) == ["retrieve", "cancel", "delete"]
        assert parse_stored_response_ops([]) == []

    def _cli(self, *extra):
        return subprocess.run(  # nosec B603
            [sys.executable, str(Path(__file__).parent / "iam_policy.py"),
             "--region", REGION, "--account-id", ACCOUNT, *extra],
            capture_output=True, text=True)

    def test_cli_stored_response_ops_emit_the_statement_for_a_responses_row(self):
        result = self._cli("--target", f"{SOL}=responses", "--stored-response-ops", "retrieve,cancel")
        assert result.returncode == 0, result.stderr
        stmt = _stmt(json.loads(result.stdout), "BedrockStoredResponseOps")
        assert stmt["Action"] == ["bedrock:CancelInvoke", "bedrock:GetInvoke"] and stmt["Resource"] == [PROJECT]

    def test_cli_refuses_stored_response_ops_for_a_converse_plan(self):
        result = self._cli("--target", f"{SOL}=converse", "--stored-response-ops", "retrieve")
        assert result.returncode == 1
        out = json.loads(result.stdout)
        assert out["ok"] is False and out["reason"] == "stored_response_ops_no_responses_row"
        assert "Statement" not in result.stdout

    def test_cli_refuses_an_unknown_op(self):
        result = self._cli("--target", f"{SOL}=responses", "--stored-response-ops", "list")
        assert result.returncode == 1
        assert json.loads(result.stdout)["reason"] == "unknown_stored_response_op"
