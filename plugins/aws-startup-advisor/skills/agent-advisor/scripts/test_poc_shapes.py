"""Content lock for references/decision-refs/poc-shapes.md.

The POC shapes are markdown-specified deploy contracts. These tests pin the
security- and cost-load-bearing content (create allowlists, auth modes,
fallback rules, the Temporal TLS contract) so a wording "simplification"
cannot silently turn a locked-down POC into a footgun. Matching is
whitespace-normalized throughout (markdown wraps lines).
"""
import pathlib
import re

SHAPES_MD = (pathlib.Path(__file__).parent.parent
             / "references" / "decision-refs" / "poc-shapes.md")
POC_MD = (pathlib.Path(__file__).parent.parent
          / "references" / "phases" / "poc" / "poc.md")
POC_REPORT_MD = (pathlib.Path(__file__).parent.parent
                 / "references" / "phases" / "poc" / "poc-report.md")
SKILL_MD = pathlib.Path(__file__).parent.parent / "SKILL.md"


def _norm(path):
    return re.sub(r"\s+", " ", path.read_text())


def test_files_exist():
    assert SHAPES_MD.exists(), SHAPES_MD


def test_ecs_create_allowlist_and_never_list():
    text = _norm(SHAPES_MD)
    assert "Terraform may create ONLY" in text
    assert "Terraform must NEVER create" in text
    for never in ["VPC", "subnets", "NAT gateway", "internet gateway", "ALB"]:
        assert never in text, f"ECS never-list item missing: {never!r}"
    # No-ALB smoke path: a service that deploys but can't be invoked isn't a POC.
    assert "No ALB" in text
    assert "run-task" in text or "execute-command" in text


def test_ecs_networking_never_creates_vpc():
    text = _norm(SHAPES_MD)
    assert "default VPC" in text
    assert "never create one" in text or "never create a VPC" in text.lower()


def test_eks_unique_namespace_and_no_iam():
    text = _norm(SHAPES_MD)
    assert "agent-advisor-poc-<run_id>" in text, (
        "EKS namespace must be unique per run — a fixed name like 'poc' risks "
        "deleting a user's pre-existing namespace on teardown")
    assert "Never a fixed name" in text
    assert "ClusterIP" in text
    assert "No LoadBalancer" in text
    assert "creates no IAM resources" in text


def test_eks_never_creates_cluster():
    assert "Never creates an EKS cluster" in _norm(SHAPES_MD)


def test_lambda_url_auth_is_iam_never_none():
    text = _norm(SHAPES_MD)
    assert "AWS_IAM" in text
    assert "never `NONE`" in text or "never NONE" in text, (
        "a public Bedrock-invoking Function URL is an open cost hole")


def test_microvms_disabled_fallback():
    text = _norm(SHAPES_MD)
    assert "microvms.tf.disabled" in text
    assert "MicroVMs config pending verification" in text
    assert "No deployable claim" in text


def test_temporal_tls_contract_complete():
    # All six connection vars, explicitly — the API-key-implies-TLS binary
    # broke mTLS self-hosted servers (Codex review, Critical 2).
    for var in ["TEMPORAL_ADDRESS", "TEMPORAL_NAMESPACE", "TEMPORAL_TLS",
                "TEMPORAL_API_KEY", "TEMPORAL_TLS_SERVER_NAME",
                "TEMPORAL_TLS_CA_PATH", "TEMPORAL_TLS_CERT_PATH",
                "TEMPORAL_TLS_KEY_PATH"]:
        assert var in _norm(SHAPES_MD), f"TLS contract var missing: {var}"
    assert "never inferred" in _norm(SHAPES_MD)


def test_temporal_smoke_queue_isolated():
    text = _norm(SHAPES_MD)
    assert "poc-smoke-<run_id>" in text
    assert "never the user's real queues" in text.lower() or \
        "never touched production queues" in text


def test_temporal_apply_proves_nothing():
    # terraform apply succeeding is not pickup proof — the starter's result is.
    text = _norm(SHAPES_MD)
    assert "apply alone proves nothing" in text or \
        "proves nothing by itself" in text


def test_temporal_teardown_wording():
    text = _norm(SHAPES_MD)
    assert "not deletable resources" in text
    assert "ages out" in text


def test_temporal_secrets_never_inline():
    text = _norm(SHAPES_MD)
    assert "SSM Parameter Store" in text or "SSM SecureString" in text
    assert "never inline" in text


def test_poc_md_dispatches_to_shapes():
    text = _norm(POC_MD)
    assert "poc-shapes.md" in text
    assert "Per-unit runtime dispatch" in text
    # The old skip message must be gone.
    assert "supports AgentCore only" not in text


def test_poc_plan_eks_uses_kubectl_not_terraform_runtask():
    # Codex round-4 #1: the EKS shape is kubectl apply / port-forward / kubectl delete — NOT
    # Terraform + run-task. The plan's staged steps must give EKS its own kubectl path.
    text = _norm(POC_MD)
    assert re.search(r"eks.{0,120}kubectl apply", text, re.IGNORECASE), \
        "EKS plan must deploy with kubectl apply, not terraform"
    assert re.search(r"eks.{0,80}kubectl delete", text, re.IGNORECASE), \
        "EKS rollback must be kubectl delete, not terraform destroy / agentcore destroy"


def test_poc_plan_covers_lambda_microvms():
    # Codex round-4 #4: lambda_microvms is dispatched as its own runtime, so the plan's staged
    # steps AND rollback list must include it (it was missing from both).
    text = _norm(POC_MD)
    # It appears in the staged-steps runtime list and the rollback list.
    assert text.count("lambda_microvms") >= 2, \
        "poc.md plan must cover lambda_microvms in both staged steps and rollback"


def test_poc_md_dispatches_temporal_worker_poll():
    # M2: temporal_worker_poll units dispatch to the temporal shape in poc-shapes.
    text = _norm(POC_MD)
    assert "temporal_worker_poll" in text
    assert "Temporal worker POC" in text
    assert "shape in" in text and "poc-shapes.md" in text


def test_skill_md_rows():
    # SKILL.md's execution moved from a hand-written state-machine table to the
    # interpreter-loop delegation (Routing & gates orchestration prose). The two
    # invariants this test pins are unchanged — only where they live moved.
    text = _norm(SKILL_MD)
    # The temporal branch must not be routable.
    assert "load `references/phases/temporal-worker" not in text, \
        "the temporal branch must not be routable"
    # Gate 2 / poc is not AgentCore-gated: any winning runtime gets a POC shape.
    gate2 = re.search(r"\*\*Gate 2 → `poc`\*\*(.*?)- Persisting", text)
    assert gate2, "SKILL.md must carry the Gate 2 → poc semantics"
    assert "Any winning runtime" in gate2.group(1)
    assert "== agentcore" not in gate2.group(1)


def test_poc_report_uses_v3_shell():
    # BUG-A fix: poc-report.md must reference the v3 document shell.
    text = _norm(POC_REPORT_MD)
    assert "report-shell.md" in text, "poc-report must reference report-shell.md"
    assert "SHARED_SHELL_CSS" in text or "shared shell" in text.lower(), \
        "poc-report must inline the shared shell CSS"
    assert "SHARED_SHELL_MERMAID_TAG" in text or "SRI-pinned mermaid" in text.lower(), \
        "poc-report must use the SRI-pinned mermaid script tag"
    assert ".doc-head" in text, "poc-report must use .doc-head"
    assert ".help-strip" in text or "HELP_URL" in text, \
        "poc-report must reference .help-strip or HELP_URL"


def test_poc_model_resolved_per_unit():
    # BUG-C fix: poc.md Step 2 must resolve model per-unit from design.json.units.
    text = _norm(POC_MD)
    # Step 2 mentions resolving per unit, not just design_blocks[0] / FIRST entry alone.
    assert "per unit" in text.lower() or "for each unit" in text.lower() or \
           "units[<id>]" in text or "units[<unit-id>]" in text, \
        "Step 2 must resolve model per-unit"
    # design.json is the authoritative model source (already reconciled by the plan);
    # the POC resolves each unit's model from its OWN entry.
    assert "single source of truth" in text.lower() or "authoritative" in text.lower(), \
        "Step 2 must state design.json is the authoritative model source"
    # The multi-unit dispatch in Step 3 must mention using each unit's model.
    assert "THAT unit's model" in text or "unit's model id" in text.lower(), \
        "Step 3 dispatch must use each unit's model id"


def test_poc_model_not_taken_from_first_block_for_all_units():
    # BUG-C regression (multi-unit, plan-backed): the plan-backed cross-check must NOT
    # tell the POC to read design_blocks[0] for every unit — that takes the first unit's
    # model for all units. It must match each unit's OWN block by evidence overlap.
    text = _norm(POC_MD)
    assert "NOT `design_blocks[0]`" in text or "not `design_blocks[0]`" in text.lower(), \
        "Step 2 plan-backed cross-check must warn against using design_blocks[0] for all units"
    assert "source_paths" in text and "evidence" in text, \
        "Step 2 plan-backed cross-check must match a unit to its own block by evidence overlap"


def test_poc_dispatches_on_effective_runtime_not_raw_verdict():
    # Codex P1 #1: a consolidated platform decision must actually drive the POC. The
    # dispatch resolves an "effective runtime" (platform.runtime under consolidated,
    # else the unit verdict) rather than always deploying each unit's raw split verdict.
    text = _norm(POC_MD)
    assert "effective runtime" in text.lower(), \
        "poc.md must resolve an effective runtime before dispatch"
    assert re.search(r'platform\.mode\s*==\s*"?consolidated"?', text), \
        "poc.md must key the consolidated case on platform.mode == consolidated"
    assert "platform.runtime" in text, \
        "poc.md consolidated case must deploy on platform.runtime (the superset)"


def test_poc_postcondition_dispatches_on_effective_runtime():
    # Codex round-6 #1: the _postcondition must judge the POC by effective_runtime, not the raw
    # verdict — a consolidated unit's correct ECS POC must not be failed for not matching its
    # raw split verdict (agentcore/lambda/batch).
    text = _norm(POC_MD)
    # Grab the frontmatter (between the first two --- fences).
    fm = text.split("---", 2)[1] if text.count("---") >= 2 else ""
    assert "effective_runtime" in fm, \
        "poc.md _postcondition must dispatch on effective_runtime"
    assert re.search(r"NOT the raw split verdict|not the raw.{0,20}verdict", fm, re.IGNORECASE), \
        "poc.md _postcondition must explicitly not use the raw split verdict"


def test_poc_dispatch_includes_fargate():
    # Codex P1 #2: W5/W6 produce a fargate verdict; dispatch must cover it. fargate reuses
    # the ecs shape (ECS-on-Fargate), so no separate shape is authored.
    text = _norm(POC_MD)
    assert "fargate" in text, "poc.md dispatch must include fargate"
    shapes = _norm(SHAPES_MD)
    assert re.search(r"fargate.{0,80}ecs shape|`fargate`.{0,80}ecs|ecs.{0,120}fargate",
                     shapes, re.IGNORECASE), \
        "poc-shapes.md ecs shape must state it also serves fargate verdicts"
    # Codex round-2 #4: W5 is "Fargate behind ALB" but the ecs shape has no ALB. The shape must
    # honestly scope-limit: the POC validates the container + Bedrock, NOT the ALB ingress.
    assert re.search(r"W5.{0,200}(does NOT provision an ALB|not the public ALB|without.{0,20}ALB)",
                     shapes, re.IGNORECASE | re.DOTALL), \
        "ecs shape must state the W5 ALB scope limit (POC validates container, not ALB ingress)"


def test_batch_shape_exists():
    # BUG-8 fix: batch POC shape must exist in poc-shapes.md.
    text = _norm(SHAPES_MD)
    assert "## batch" in text, "poc-shapes.md must have a ## batch section"


def test_batch_create_allowlist_and_never_list():
    text = _norm(SHAPES_MD)
    # Batch section must have create allowlist and never-list.
    assert "aws_batch_compute_environment" in text
    assert "aws_batch_job_queue" in text
    assert "aws_batch_job_definition" in text
    for never in ["VPC", "subnets", "NAT gateway", "internet gateway", "always-on compute"]:
        assert never in text, f"Batch never-list item missing: {never!r}"


def test_batch_secrets_never_inline():
    text = _norm(SHAPES_MD)
    # Batch shape must use SSM/Secrets Manager, never inline.
    assert "SSM Parameter Store" in text or "SSM SecureString" in text or "Secrets Manager" in text
    assert "never inline" in text


def test_batch_teardown_wording():
    text = _norm(SHAPES_MD)
    # Batch teardown must mention resources not deletable while jobs run.
    assert "not deletable" in text or "not deletable resources" in text
    assert "drain" in text or "ages out" in text


def test_poc_md_dispatches_batch():
    # BUG-8 fix: poc.md Step 3 dispatch must include batch.
    text = _norm(POC_MD)
    assert "batch" in text
    # The dispatch list should include batch alongside ecs/eks/lambda/lambda_microvms.
    assert "batch / ecs / eks / lambda / lambda_microvms" in text or \
           "batch/ecs/eks/lambda/lambda_microvms" in text or \
           ("batch" in text and "ecs / eks / lambda / lambda_microvms" in text), \
        "poc.md Step 3 dispatch must include batch"


def test_poc_md_multiunit_dispatch_is_unconditionally_first():
    # BUG-9 fix: Step 3 must unambiguously gate on unit count FIRST, before runtime dispatch.
    text = _norm(POC_MD)
    # Multi-unit decision must be explicit at top of Step 3.
    assert "Multi-unit system decision gate" in text or \
           "equals design.json.units[].length" in text, \
        "Step 3 must have explicit multi-unit decision gate"
    # Must state that Temporal systems with multiple units are multi-unit, not one app.
    assert "Temporal system" in text and "multi-unit" in text.lower(), \
        "Step 3 must clarify Temporal systems with >1 unit are multi-unit"
    assert "NOT one app" in text or "never one" in text, \
        "Step 3 must state multi-unit Temporal systems don't collapse to one poc/app/"
    # The agentcore branches (3-F/3-H/3a-e) are per-unit shapes, not whole-system.
    assert "PER-UNIT shape" in text or "per-unit shape" in text, \
        "Step 3 must clarify 3-F/3-H/3a-e are per-unit shapes"
    # Per-unit runtime dispatch heading must NOT say "FIRST" — only the multi-unit gate is first.
    assert "Per-unit runtime dispatch" in text, \
        "Step 3 must have 'Per-unit runtime dispatch' heading"
    # The old "RUNTIME DISPATCH FIRST" heading must be gone or reworded.
    step3_text = re.search(r"## Step 3 —.*?## Step 4", text, re.DOTALL)
    assert step3_text, "Could not find Step 3 section"
    # Count "FIRST" occurrences in Step 3 — there should be exactly 0 or 1 (the decision gate).
    first_count = step3_text.group(0).lower().count("dispatch first")
    assert first_count <= 1, \
        f"Step 3 has {first_count} 'DISPATCH FIRST' headings; only the multi-unit gate may be first"
