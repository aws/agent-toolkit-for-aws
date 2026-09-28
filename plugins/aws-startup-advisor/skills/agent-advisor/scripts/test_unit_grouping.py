"""Content lock for the unit-inventory grouping rules in the Discover phase.

The grouping judgment (in-process agents merge; cross-process split) is prose,
so these tests pin the load-bearing sentences the same way the temporal locks do.
"""
import json
import pathlib
import re

DISCOVER_MD = (pathlib.Path(__file__).parent.parent
               / "references" / "phases" / "discover" / "discover.md")
ASSEMBLE_MD = (pathlib.Path(__file__).parent.parent
               / "references" / "phases" / "discover" / "discover-assemble.md")


def _norm(p):
    return re.sub(r"\s+", " ", p.read_text())


def test_in_process_agents_merge():
    text = _norm(DISCOVER_MD)
    assert "in-process" in text.lower()
    assert re.search(r"in-process.{0,200}ONE unit", text, re.IGNORECASE), \
        "in-process coupled agents must be stated to merge into one unit"


def test_coupling_mode_vocabulary():
    text = _norm(DISCOVER_MD)
    for mode in ["queue", "api", "a2a", "none"]:
        assert f"`{mode}`" in text
    assert re.search(r"in_process.{0,160}never", text), \
        "in_process must be stated to never survive grouping"


def test_workload_class_vocabulary():
    text = _norm(DISCOVER_MD)
    for cls in ["agent_session", "batch", "light_io", "service"]:
        assert f"`{cls}`" in text


def test_confirmation_only_when_multiple():
    # Collapse invariant: a single-unit draft is recorded silently.
    text = _norm(ASSEMBLE_MD)
    assert re.search(r"ONLY when.{0,80}more than one unit|>\s*1 unit", text), \
        "grouping confirmation must be gated on >1 unit"


CLARIFY_MD = (pathlib.Path(__file__).parent.parent
              / "references" / "phases" / "clarify" / "clarify.md")


def test_clarify_two_levels():
    text = _norm(CLARIFY_MD)
    for dim in ["ops_preference", "existing_cluster", "multi_cloud", "platform_fit"]:
        assert f"`{dim}`" in text, f"system-level dim {dim} must be named"
    assert re.search(r"system-level.{0,200}asked once", text, re.IGNORECASE)
    assert re.search(r"primary unit.{0,200}full", text, re.IGNORECASE)
    assert re.search(r"ONE batched delta question", text), \
        "non-primary units get exactly one batched delta question"
    assert re.search(r"inherit.{0,120}primary", text, re.IGNORECASE)


def test_scoring_loop_per_agent_unit():
    text = _norm(CLARIFY_MD)
    assert re.search(r"once per `agent_session` unit", text), \
        "scoring must be stated to run once per agent-class unit"
    assert "scoring.py is NOT modified" in text or "scoring.py unchanged" in text


def test_cross_phase_field_seams():
    """Whole-branch review found field-name forks at phase seams (M1-M4).
    Pin the reader side to the producer's vocabulary."""
    report = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "generate" / "generate-report.md")
    plan = _norm(pathlib.Path(__file__).parent.parent
                 / "references" / "phases" / "migration-plan" / "migration-plan.md")
    clarify = _norm(CLARIFY_MD)
    # M2/M3: readers use the producer's names
    assert "PLATFORM.decision" not in report and "PLATFORM.rationale" not in report
    assert "platform.architecture" not in plan
    assert "consolidated" in report and "consolidate |" not in report
    design = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "design" / "design.md")
    assert "consolidate |" not in design, "stale consolidate token in design.md"
    # M1: clarify writes the legacy mirror
    assert re.search(r"entry_point.{0,300}answers.{0,200}primary unit", clarify, re.IGNORECASE) or \
           re.search(r"legacy.{0,120}mirror", clarify, re.IGNORECASE)
    # M4: plan injection uses real unit field names
    assert "model_recommendation" in plan and "agentcore_services" in plan


DISCOVER = DISCOVER_MD  # alias for readability


def test_temporal_detection_creates_units():
    text = _norm(DISCOVER_MD)
    assert "`temporal_worker_poll`" in text, "temporal poll tier must be a unit class"
    assert re.search(r"one\s+`temporal_worker_poll`\s+unit per (worker fleet|task-queue group)",
                     text, re.IGNORECASE)
    assert re.search(r"Activity execution class.{0,200}(agent_session|`agent_session`)",
                     text, re.DOTALL), "activity classes must map onto unit classes"
    assert "decision-refs/temporal.md" in text, "classification vocabulary must defer to temporal.md"


def test_intake_routes_temporal_into_main_flow():
    intake = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "intake" / "intake.md")
    assert "entry_point = temporal_worker" not in intake, \
        "the temporal branch entry point is retired — temporal routes into the main flow"
    assert re.search(r"[Tt]emporal signal", intake), \
        "intake still recognizes the temporal signal (as detection context, not a branch)"


def test_migration_plan_unit_correlation_overlay():
    plan = _norm(pathlib.Path(__file__).parent.parent
                 / "references" / "phases" / "migration-plan" / "migration-plan.md")
    assert '"evidence"' in plan, "injection units must carry the evidence correlation key"
    assert "advisor_unit" in plan and "advisor_target_runtime" in plan
    assert re.search(r"additive.{0,200}never (modify|remove)", plan, re.IGNORECASE | re.DOTALL), \
        "annotation must be declared additive-only"
    assert re.search(r"[Ss]ingle-unit.{0,120}(skip|SKIP)", plan), \
        "collapse invariant: single-unit runs skip the overlay"


def test_migration_plan_validates_advisor_model_contract_without_reselection():
    plan = _norm(pathlib.Path(__file__).parent.parent
                 / "references" / "phases" / "migration-plan" / "migration-plan.md")

    assert re.search(r"Validate the advisor model/path contract", plan), \
        "migration-plan must validate the advisor's per-workload model/path contract"
    assert "advisor wins" in plan.lower(), \
        "the advisor must remain the model-selection authority"
    assert "plan_model_mismatch" in plan and "_halt_and_inform" in plan, \
        "a plan mismatch must be visible and blocking"
    assert re.search(r"do not rewrite `design\.json`", plan, re.IGNORECASE), \
        "migration-plan must not silently replace the confirmed advisor decision"
    assert "model-recommendation-input.json" in plan and \
        "model_recommendation.py" in plan, \
        "mismatch resolution must return to the deterministic Model Recommend phase"
    frontmatter = plan.split("---", 2)[1] if plan.count("---") >= 2 else ""
    assert re.search(r"model contract validation", frontmatter, re.IGNORECASE), \
        "migration-plan postconditions must enforce contract validation"


def test_unit_trigger_vocabulary():
    text = _norm(DISCOVER_MD)
    assert '"trigger"' in text or "`trigger`" in text
    for v in ["request", "event", "schedule", "temporal"]:
        assert f"`{v}`" in text, f"trigger vocab missing {v}"


def test_activity_units_carry_task_queue_join_key():
    # Codex P1 #3: the diagram connected each fleet to EVERY activity (cartesian product)
    # because activity units had no queue membership. Discover must give each Activity-class
    # unit a task_queue field so a fleet connects only to the Activities on its queues[].
    text = _norm(DISCOVER_MD)
    assert re.search(r'"task_queue"', text) and re.search(r"Activity-class unit", text), \
        "discover must give each Activity-class unit a task_queue field"
    assert re.search(r"join key|never a cartesian product|never a cartesian", text, re.IGNORECASE), \
        "discover must frame task_queue as the fleet<->activity join key (no cartesian product)"


def test_design_writes_effective_runtime_and_coupling_per_unit():
    # Codex round-2 #2/#5: design.json must carry per-unit effective_runtime (single source
    # for every downstream deploy/cost/render target) and per-unit coupling (so the diagram
    # wires only queue-coupled units). Consolidation lives in platform, effective_runtime on units.
    design = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "design" / "design.md")
    assert "effective_runtime" in design, "design.md must produce a per-unit effective_runtime"
    assert re.search(r"consolidated.{0,80}platform\.runtime", design, re.IGNORECASE) and \
        re.search(r"split.{0,160}(verdict|resolved runtime)", design, re.IGNORECASE), \
        "effective_runtime must equal platform.runtime when consolidated, else the resolved verdict"
    assert re.search(r'"coupling"', design) or re.search(r"coupling.{0,40}context-signals", design), \
        "design.md must carry each unit's coupling over from context-signals"


def test_platform_runtime_enum_allows_lambda_consolidation():
    # Codex round-6 #2 (regression from round-5): the consolidation superset is "the runtime
    # satisfying every unit's hard constraints with the highest summed score" — any qualifying
    # runtime is legal, incl. Lambda / Lambda MicroVMs for an all-agent system. The
    # platform.runtime enum must NOT be over-narrowed to only ecs/eks/agentcore, and
    # migration-plan explicitly handles a lambda consolidation superset.
    design = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "design" / "design.md")
    m = re.search(r'"runtime":\s*"([^"]*consolidation superset[^"]*)"', design)
    assert m, "design.md must document the platform.runtime superset enum"
    enum = m.group(1)
    assert "lambda" in enum, \
        "platform.runtime enum must allow Lambda/Lambda MicroVMs consolidation, not only ecs/eks/agentcore"


def test_downstream_phases_read_effective_runtime():
    # Codex round-2 #2: estimate (cost), generate report (render target), and the diagram
    # must all key on effective_runtime, not the raw verdict — else a consolidated run costs
    # and displays the split verdicts while the POC deploys the superset.
    base = pathlib.Path(__file__).parent.parent / "references" / "phases"
    est = _norm(base / "estimate" / "estimate.md")
    rep = _norm(base / "generate" / "generate-report.md")
    assert "effective_runtime" in est, "estimate must cost by effective_runtime"
    assert "effective_runtime" in rep, "report must render the effective_runtime as the target"


def test_estimate_eks_not_hardcoded_fargate():
    # Codex round-6 #3: EKS cost must follow the cluster's actual node capacity type, not assume
    # EKS-on-Fargate. EC2/Spot/Karpenter/GPU and existing-cluster reuse price differently.
    est = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "estimate" / "estimate.md")
    assert re.search(r"do NOT assume Fargate|not assume Fargate", est, re.IGNORECASE), \
        "estimate must not hardcode EKS as Fargate"
    assert re.search(r"node capacity type", est, re.IGNORECASE) and \
        re.search(r"EC2|Karpenter|Spot", est), \
        "estimate must price EKS by actual node capacity type (EC2/Spot/Karpenter/GPU)"
    # Codex round-7 #2: reusing an existing cluster is near-zero ONLY with spare capacity;
    # otherwise Karpenter/ASG adds nodes and the full incremental cost applies.
    assert re.search(r"near-zero.{0,60}(only|ONLY).{0,40}spare capacity", est, re.IGNORECASE | re.DOTALL) or \
        re.search(r"spare capacity.{0,80}near-zero", est, re.IGNORECASE | re.DOTALL), \
        "existing-cluster near-zero must be gated on stated spare capacity"
    assert re.search(r"Karpenter/ASG adds nodes|full incremental", est, re.IGNORECASE), \
        "estimate must charge full incremental node cost when no spare capacity"
    # Codex round-9 #2: the node-aware EKS rule must apply to ANY unit whose effective_runtime is
    # eks — not only agent_session. A W1 existing-cluster-reuse or a consolidation can land a
    # service/batch unit on EKS; the service branch must not flat-price it as Fargate.
    assert re.search(r"ANY unit whose .?effective_runtime == .?eks", est, re.IGNORECASE), \
        "EKS pricing rule must apply to any unit on eks regardless of class"
    assert re.search(r"regardless of\s+class", est, re.IGNORECASE), \
        "EKS pricing rule must be class-agnostic (service/batch/light_io/agent_session)"
    # Codex round-10: the temporal_worker_poll polling tier must NOT be hardcoded "tens of $/mo"
    # for EKS — a GPU/EC2/Karpenter worker fleet is priced by node capacity like any other unit.
    m = re.search(r"temporal_worker_poll units.{0,2600}", est, re.DOTALL)
    assert m, "estimate must have a temporal_worker_poll cost bullet"
    tw = m.group(0)
    assert re.search(r"effective_runtime == .?eks.{0,200}(EKS pricing rule|node capacity)",
                     tw, re.IGNORECASE | re.DOTALL), \
        "temporal polling tier must apply the node-aware EKS rule, not a flat 'tens of $/mo'"
    # Codex round-11 #1: serverless_workers is a legal temporal verdict but had no polling-tier
    # cost path — must define one (pre-release → MCP rate or qualitative fallback, not fabricated).
    assert re.search(r"serverless_workers.{0,300}(qualitative|Public Preview|unverified)",
                     tw, re.IGNORECASE | re.DOTALL), \
        "temporal polling tier must define a serverless_workers path (Public Preview/qualitative fallback)"
    # Codex round-11 #2: must NOT assert execution-tier dominance unconditionally — compare the
    # two computed bands (a GPU/high-node polling fleet or low Activity volume can flip it).
    assert not re.search(r"execution tier\s+dominates(?![^.]*compar)", tw, re.IGNORECASE), \
        "must not state 'execution tier dominates' unconditionally"
    assert re.search(r"compare the .{0,20}bands|can equal or exceed|material or even dominant",
                     tw, re.IGNORECASE), \
        "temporal takeaway must compare the two bands, not assume a fixed order"
    # Self-audit (pre-round-12): Temporal Cloud orchestration is a system-level cost — the prior
    # text both said "not folded into any unit's other breakdown" AND "a separate line in the
    # per-unit cost breakdown", which is contradictory and unexecutable (breakdown is fixed at
    # {compute, model_tokens, other}). It must be recorded at the SYSTEM level (total + top-level
    # assumptions), never inside a unit breakdown.
    # (scope to the whole estimate.md — the temporal table is wide, so a fixed window is fragile)
    assert re.search(r"do NOT fold them into any unit", est, re.IGNORECASE), \
        "Temporal Cloud actions must not be folded into a unit breakdown"
    assert not re.search(r"separate line in the per-unit .{0,20}breakdown", est, re.IGNORECASE), \
        "must not instruct putting orchestration into a per-unit breakdown (schema has no slot)"
    assert re.search(r"total_monthly_magnitude_usd.{0,120}(system-level|orchestration|PLUS)",
                     est, re.IGNORECASE | re.DOTALL), \
        "total must account for the system-level orchestration line, not just the unit sum"


def test_agentcore_endpoint_note_is_per_unit_not_primary():
    # Codex round-9 #1: the AgentCore /invocations+/ping endpoint note must attach to EVERY unit
    # whose effective_runtime is agentcore, not just the primary/winning unit. A split system with
    # primary=Lambda + secondary AgentCore must still emit the note for the AgentCore unit.
    plan = _norm(pathlib.Path(__file__).parent.parent
                 / "references" / "phases" / "migration-plan" / "migration-plan.md")
    assert re.search(r"PER UNIT", plan) and \
        re.search(r"EVERY unit whose .?effective_runtime == .?agentcore", plan, re.IGNORECASE), \
        "AgentCore endpoint note must be per-unit, keyed on each unit's effective_runtime"
    assert re.search(r"NOT just the primary", plan, re.IGNORECASE), \
        "AgentCore endpoint note must not be keyed on the primary/winning unit only"
    # Audit finding #1: the prose is correct but the injection JSON schema must ALSO carry a
    # per-unit endpoint field, or an assembler following the schema drops the note for a
    # secondary AgentCore unit — re-introducing the primary-keyed twin.
    assert re.search(r'"endpoint_contract"', plan), \
        "migration-plan injection schema must have a per-unit endpoint_contract field"


def test_poc_goal_line_enumerates_lambda_microvms():
    # Audit finding #3: the poc.md Goal-line runtime enumeration must include lambda_microvms —
    # every other effective_runtime has a goal phrase; omitting it is the 'list missing
    # lambda_microvms' twin.
    poc = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "poc" / "poc.md")
    # The Goal line lists AgentCore/ECS/EKS/Fargate/Lambda/Batch/Temporal — Lambda MicroVMs too.
    m = re.search(r"\*\*Goal\*\*.{0,600}", poc, re.DOTALL)
    assert m and re.search(r"Lambda MicroVMs", m.group(0)), \
        "poc Goal-line enumeration must include a Lambda MicroVMs phrase"


def test_migration_plan_consolidated_overrides_top_level_approach():
    # Codex round-2 #2: the top-level injection reads the primary unit's legacy mirror; under
    # consolidation it must instead follow platform.runtime (retarget), not inject harness/AgentCore.
    plan = _norm(pathlib.Path(__file__).parent.parent
                 / "references" / "phases" / "migration-plan" / "migration-plan.md")
    assert re.search(r"[Cc]onsolidated platform overrides", plan) or \
        re.search(r"platform\.mode\s*==\s*\"?consolidated\"?.{0,200}platform\.runtime", plan, re.DOTALL), \
        "migration-plan must override the top-level approach from platform.runtime when consolidated"
    # Codex round-7 #1: the non-agentcore superset list must include lambda_microvms (restored as
    # a legal superset), or an AgentCore primary leaks harness into a MicroVMs consolidation.
    assert re.search(r"lambda_microvms", plan) and \
        re.search(r"harness/strands ONLY when|only inject .?.?harness", plan, re.IGNORECASE), \
        "migration-plan retarget override must cover lambda_microvms; harness only when superset is agentcore"


def test_handoff_required_scans_all_units_effective_runtime():
    # Codex round-7 #3 + round-8 #2: handoff_required must be true when ANY unit's effective_runtime
    # needs a compute handoff — one of ecs, eks, fargate, or batch (not just the primary/winning
    # runtime; fargate=ECS and batch both hand the compute layer to migration skill per their
    # service cards). AgentCore/Lambda/Lambda MicroVMs are self-contained.
    design = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "design" / "design.md")
    assert re.search(r"ANY unit'?s? .?effective_runtime.? needs a", design, re.IGNORECASE), \
        "handoff_required must be keyed on any unit's effective_runtime, not just the primary"
    assert re.search(r"not just the primary", design, re.IGNORECASE), \
        "design must state handoff_required is not just the primary/winning runtime"
    # round-8 #2: the set must include fargate and batch, not just ecs/eks.
    assert re.search(r"\{ecs, eks, fargate, batch\}", design), \
        "handoff_required set must include fargate and batch (both hand off compute), not just ecs/eks"
    # build_diagram's HANDOFF_RUNTIMES must stay in sync with the design definition.
    import build_diagram
    assert build_diagram.HANDOFF_RUNTIMES == {"ecs", "eks", "fargate", "batch"}, \
        "build_diagram.HANDOFF_RUNTIMES must match design.md's handoff set (ecs/eks/fargate/batch)"


def test_agentcore_consolidation_keeps_endpoint_note():
    # Codex round-8 #1: the AgentCore endpoint/services note must follow platform.runtime, not be
    # unconditionally suppressed under consolidation — a consolidation ONTO AgentCore still needs
    # the POST /invocations + GET /ping note, while a non-AgentCore superset must NOT get it.
    plan = _norm(pathlib.Path(__file__).parent.parent
                 / "references" / "phases" / "migration-plan" / "migration-plan.md")
    assert re.search(r"AgentCore .*note follows .*platform\.runtime", plan, re.IGNORECASE), \
        "AgentCore endpoint note must follow platform.runtime, not be unconditionally suppressed"
    assert re.search(r"ONLY when .?platform\.runtime == .?agentcore", plan), \
        "AgentCore note injected only when the superset is itself AgentCore"


def test_contributing_does_not_mislabel_llm_to_bedrock_as_dsl():
    # Codex round-3 #5: llm-to-bedrock is a single prose SKILL.md (no phase frontmatter); the
    # frontmatter validator only checks heroku-to-aws + agent-advisor. CONTRIBUTING must not
    # claim llm-to-bedrock is a phase-DSL skill.
    contributing = (pathlib.Path(__file__).parent.parent.parent.parent / "CONTRIBUTING.md")
    if not contributing.exists():
        return  # CONTRIBUTING lives at the plugin root; skip if layout differs
    text = re.sub(r"\s+", " ", contributing.read_text())
    # In the architecture table, the llm-to-bedrock row must NOT say "phase DSL".
    m = re.search(r"\*\*llm-to-bedrock\*\*\s*\|([^|]*)\|", text)
    assert m, "CONTRIBUTING must have an llm-to-bedrock architecture row"
    assert "phase DSL" not in m.group(1), \
        "llm-to-bedrock is prose, not phase DSL — CONTRIBUTING must not label it DSL"
    assert re.search(r"[Tt]wo are built on the .{0,20}phase DSL", text) or \
        re.search(r"prose SKILL", text), \
        "CONTRIBUTING must state two DSL skills (heroku + agent-advisor), the rest prose"


def test_co_recommend_resolved_to_runtime_before_gate_and_effective_runtime():
    # Codex round-3 #1: co_recommend is NOT a runtime. The platform gate must compare the
    # RESOLVED runtime (chosen_runtime for a co_recommend unit), and design's effective_runtime
    # must never be the literal "co_recommend". Two tied units sent to different runtimes must
    # trigger the divergence gate, not be seen as "both co_recommend" and skip it.
    confirm = _norm(pathlib.Path(__file__).parent.parent
                    / "references" / "phases" / "confirm" / "confirm.md")
    design = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "design" / "design.md")
    assert re.search(r"resolved runtime", confirm, re.IGNORECASE) and \
        re.search(r"[Nn]ever compare the literal|not a runtime", confirm), \
        "confirm platform gate must compare resolved runtime, not the literal co_recommend"
    assert re.search(r"chosen_runtime", confirm), \
        "confirm gate must use chosen_runtime for a co_recommend unit"
    assert re.search(r"[Nn]ever the literal .?co_recommend|ALWAYS a concrete runtime", design), \
        "design effective_runtime must never be the literal co_recommend"


def test_migration_plan_deployment_model_consistent_with_target_runtime():
    # Codex round-3 #2: a consolidated (or co_recommend→non-agentcore) row must not carry
    # deployment_model: harness with target_runtime: ecs. deployment_model is harness/etc ONLY
    # when target_runtime is agentcore; otherwise framework_on_runtime.
    plan = _norm(pathlib.Path(__file__).parent.parent
                 / "references" / "phases" / "migration-plan" / "migration-plan.md")
    assert re.search(r"deployment_model.{0,80}consistent with.{0,20}target_runtime", plan, re.IGNORECASE), \
        "migration-plan must require deployment_model consistent with target_runtime"
    assert re.search(r"only when.{0,40}target_runtime\s*==\s*\"?agentcore", plan, re.IGNORECASE) and \
        re.search(r"framework_on_runtime", plan), \
        "harness only when target_runtime==agentcore, else framework_on_runtime"


def test_confirm_step3_covers_all_non_agentcore_runtimes():
    # Codex round-4 #3: Step 3 (add-on services for non-AgentCore runtimes) must be the
    # fallthrough for EVERY non-agentcore pick — including lambda_microvms from a co_recommend
    # tie — or that unit never confirms agentcore_services/tool_choices.
    confirm = _norm(pathlib.Path(__file__).parent.parent
                    / "references" / "phases" / "confirm" / "confirm.md")
    assert re.search(r"Step 3.{0,120}lambda_microvms", confirm) or \
        re.search(r"non-AgentCore runtime.{0,120}lambda_microvms", confirm, re.IGNORECASE), \
        "confirm Step 3 must include lambda_microvms among the non-agentcore runtimes"
    assert re.search(r"[Ee]very non-agentcore runtime|no runtime pick skips", confirm), \
        "confirm Step 3 must be the fallthrough for every non-agentcore runtime"


def test_confirm_resolves_each_agent_unit_independently():
    # Codex round-2 #1: confirm must run per agent_session unit (each unit's own verdict,
    # deployment_model, services, co_recommend tie), writing confirm.json.units[<id>] — not one
    # global deployment_model/services applied to every unit.
    confirm = _norm(pathlib.Path(__file__).parent.parent
                    / "references" / "phases" / "confirm" / "confirm.md")
    assert re.search(r"once per .?agent_session.? unit|per-unit confirm", confirm, re.IGNORECASE), \
        "confirm must iterate per agent_session unit"
    assert "units[<unit_id>]" in confirm or re.search(r"confirm\.json\.units\[", confirm), \
        "confirm.json must carry per-unit entries"
    assert re.search(r"[Nn]ever (apply|copy).{0,90}(another|primary)", confirm), \
        "confirm must forbid applying one unit's runtime/services to another"


def test_migration_plan_injects_effective_runtime():
    # Codex P1 #1: consolidated must drive the plan. The injection's target_runtime is the
    # EFFECTIVE runtime (platform.runtime under consolidated), not the raw split verdict.
    plan = _norm(pathlib.Path(__file__).parent.parent
                 / "references" / "phases" / "migration-plan" / "migration-plan.md")
    assert "effective runtime" in plan.lower(), \
        "migration-plan must inject the effective runtime"
    assert re.search(r'platform\.mode\s*==\s*"?consolidated"?', plan) and \
        "platform.runtime" in plan, \
        "migration-plan effective runtime must resolve platform.runtime under consolidated"
    assert "raw_verdict" in plan, \
        "migration-plan must still carry the raw verdict for report trade-off display"


def test_report_v3_data_seams():
    report = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "generate" / "generate-report.md")
    for token in ['"trigger"', "provenance", "platform_decision.offer",
                  '"breakdown"', "drivers", "key_change", "volatile_facts"]:
        assert token.strip('"') in report, f"v3 report must consume {token}"
    assert "hero-panel" not in report, "v3 dropped the hero panel"


def test_migrate_runs_estimate():
    skill = _norm(pathlib.Path(__file__).parent.parent / "SKILL.md")
    assert "skip Estimate" not in skill, "migrate now runs Estimate (target-state run cost)"
    est = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "estimate" / "estimate.md")
    assert re.search(r"target-state run cost", est, re.IGNORECASE)
    assert re.search(r"TCO.{0,120}(Migration Plan|migration plugins|gcp)", est, re.IGNORECASE | re.DOTALL)


def test_poll_units_list_queues():
    text = _norm(DISCOVER_MD)
    assert '"queues"' in text or "`queues`" in text
    assert re.search(r"temporal_worker_poll.{0,200}queues", text, re.IGNORECASE)


def test_migration_plan_gcp_report_firewall():
    """BUG-1 (live test 0715): the inline gcp engine must render migration-report.html
    in gcp's OWN format — the advisor v3 shell must not bleed into it."""
    mp = _norm(pathlib.Path(__file__).parent.parent
               / "references" / "phases" / "migration-plan" / "migration-plan.md")
    assert re.search(r"[Cc]ontext firewall", mp), "Phase E must state the gcp context firewall"
    assert "report-shell.md" in mp and re.search(
        r"[Dd]o NOT apply.{0,120}report-shell", mp, re.DOTALL), \
        "must forbid applying the advisor shell to gcp artifacts"
    assert re.search(r"ADDITIVE-ONLY|additive-only", mp), \
        "the help-banner injection must be declared additive-only"


def test_help_banner_suppressed_pre_launch():
    """The support page is not launched — the help banner must be SUPPRESSED at its single
    source, and every consumer (recommendation report, POC report, migration-report
    post-process) must gate on that status and omit the banner while suppressed."""
    root = pathlib.Path(__file__).parent.parent
    banner = _norm(root / "references" / "report-help-banner.md")
    assert re.search(r"banner_status:\s*SUPPRESSED", banner), \
        "report-help-banner.md must declare banner_status: SUPPRESSED pre-launch"
    # Each consumer must reference the gate so it doesn't render the banner unconditionally.
    for rel in [
        "references/phases/generate/generate-report.md",
        "references/phases/poc/poc-report.md",
        "references/phases/migration-plan/migration-plan.md",
    ]:
        text = _norm(root / rel)
        assert re.search(r"SUPPRESSED", text) and re.search(r"banner_status", text), \
            f"{rel} must gate the help banner on banner_status (skip while SUPPRESSED)"
    # Codex round-12 #3: unconditional "render the CTA" statements must ALSO be gated — the
    # top-of-file instruction in generate-report.md and the usage note in report-help-banner.md
    # previously told the interpreter to render the CTA / put the banner at the top of EVERY
    # report with no gate, which could still leak the staging link.
    gen = _norm(root / "references" / "phases" / "generate" / "generate-report.md")
    assert re.search(r"ONLY when.{0,40}banner_status.{0,20}LIVE|render NO help CTA", gen, re.IGNORECASE), \
        "generate-report.md top instruction must gate the help CTA on banner_status"
    assert re.search(r"applies ONLY while .?banner_status.? is .?LIVE", banner, re.IGNORECASE), \
        "report-help-banner.md usage note must be gated on banner_status LIVE"


def test_serverless_workers_unverified_breakdown_schema():
    # Codex round-12 #1: SW polling may be qualitatively unverifiable, but the phase otherwise
    # requires every breakdown component + the unit total to be a dollar band. Reconcile: an
    # unverifiable component uses "unverified", and the unit total reflects it rather than
    # fabricating a number.
    est = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "estimate" / "estimate.md")
    assert re.search(r'"unverified"', est), \
        "estimate must define an 'unverified' breakdown value for a non-priceable SW rate"
    assert re.search(r"EXCEPT when.{0,80}unverifiable|unverified.{0,120}monthly_magnitude_usd",
                     est, re.IGNORECASE | re.DOTALL), \
        "the 'every component is a band' rule must carve out the unverified SW case for the total"


def test_report_cost_dominance_not_hardcoded_and_temporal_vars_defined():
    # Codex round-12 #2: the report must not hardcode "model tokens dominate every line" (Estimate
    # now compares bands), and TEMPORAL_COST / TEMPORAL_COST_SUMMARY used in the cost table must be
    # defined in the data-collection table or they render blank.
    rep = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "generate" / "generate-report.md")
    assert "model tokens dominate every line" not in rep, \
        "report must not hardcode unconditional model-token dominance"
    assert re.search(r"COST_DOMINANT_NOTE", rep), \
        "report must derive the dominant-tier note from the actual estimate bands"
    # Every templated variable used in the cost summary must be defined in the collection table.
    for var in ["COST_DOMINANT_NOTE", "TEMPORAL_COST", "TEMPORAL_COST_SUMMARY"]:
        assert len(re.findall(rf"`?{var}`?", rep)) >= 2, \
            f"{var} must be BOTH defined in the data-collection table AND used in the template"


def test_report_reads_fields_producers_actually_write():
    # Contract audit (pre-round-13): the report template must not reference estimate.json /
    # design.json fields that the producers never emit (they render blank / empty parens).
    rep = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "generate" / "generate-report.md")
    est = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "estimate" / "estimate.md")
    # Fields the report reads that estimate.json must actually produce:
    assert "ESTIMATE.total or" not in rep and "ESTIMATE.total }}" not in rep, \
        "report must read total_monthly_magnitude_usd, not the non-existent ESTIMATE.total"
    for total_field in ["total_compute", "total_model", "total_other"]:
        assert total_field in est, \
            f"estimate.md must emit {total_field} that the cost Total row reads"
    # driver key is `driver`, not `dimension`; model field is `model`, not `model_display`.
    assert "driver.dimension" not in rep, "report must read driver.driver (producer's key)"
    assert "model_display" not in rep, "report must read model_recommendation.model (producer's key)"
    # per-unit breakdown has no compute_note/model_note subfields (breakdown is fixed at 3 keys).
    assert "compute_note" not in rep and "model_note" not in rep, \
        "report must not read breakdown subfields the producer never writes"
    # per-unit scores live in scoring-result.json, not on design.json units[].
    assert "unit.scores[" not in rep, \
        "report must read SCORING_RESULT.units[unit.id].scores, not unit.scores off a design unit"
    # PLATFORM_DECISION has no `rationale`; render from offer.sacrifices instead.
    assert "PLATFORM_DECISION.rationale" not in rep, \
        "report must render the platform decision from offer.sacrifices, not a non-existent rationale"
    # poc-report Overview help CTA must be gated too (not just the body block).
    poc = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "poc" / "poc-report.md")
    assert re.search(r"GATED on .{0,40}banner_status|render NO help strip", poc, re.IGNORECASE), \
        "poc-report Overview must gate the help CTA on banner_status, matching its body block"


def test_report_contract_round13_fixes():
    # Codex round-13: four more producer→consumer mismatches in generate-report.md.
    rep = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "generate" / "generate-report.md")
    est = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "estimate" / "estimate.md")
    # #1 TEMPORAL_UNITS_PRESENT must key on units[].workload_class, not design.temporal.units
    # (the temporal block has no units field).
    assert re.search(r"TEMPORAL_UNITS_PRESENT.{0,160}workload_class == .?temporal_worker_poll",
                     rep, re.DOTALL), \
        "TEMPORAL_UNITS_PRESENT must key on units[].workload_class == temporal_worker_poll"
    # #2 the unverified-component rule must cover ALL three column totals + the grand total,
    # not only total_model.
    assert re.search(r"uniform across all three column totals AND", est), \
        "estimate must apply the unverified-exclusion rule to every total, not just total_model"
    # #3 rule-based (non-agent) units read design's rationale, not fabricated verdict_detail /
    # rule_cite / rule_text / considered_and_rejected.
    for ghost in ["verdict_detail", "rule_text", "considered_and_rejected"]:
        assert ghost not in rep, \
            f"rule-based form must not read {ghost} (design produces rationale + key_change only)"
    # #4 eliminated is a {runtime: reason} map — read as a map, scoped to the current unit,
    # never as an array with .length / elim.runtime.
    assert ".eliminated.length" not in rep and "elim.runtime" not in rep, \
        "eliminated is a map; must not read .length / elim.runtime"
    assert re.search(r"FOR EACH \(runtime, reason\) IN SCORING_RESULT\.units\[unit\.id\]\.eliminated",
                     rep), \
        "eliminated must be iterated as a (runtime, reason) map scoped to the current unit"


def test_report_all_template_vars_have_a_producer():
    # Mechanical audit (pre-round-14): every JSON-contract {{ VARIABLE }} in generate-report.md
    # must either be defined in the R0 data-collection table or be a documented prose/derived
    # value. These specific ones were used-but-undefined (render blank) or ghost fields.
    rep = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "generate" / "generate-report.md")
    # §1 summary non-agent Basis is the twin of the §3 rule-based form (round-13 #3): it must read
    # unit.rationale, NOT unit.rule_cite (design produces rationale, not rule_cite).
    assert "unit.rule_cite" not in rep, \
        "§1 summary non-agent Basis must read unit.rationale, not the unproduced unit.rule_cite"
    # used-but-previously-undefined variables must now be defined in the R0 table.
    for var in ["PRIMARY_UNIT", "unit.runner_up_runtime", "unit.runner_up_score", "SYSTEM_NAME"]:
        assert var in rep, \
            f"{var} must be defined in the R0 data-collection table (it is used in the template)"
    # the runner-up row must be gated so a null runner-up doesn't render empty parens.
    assert re.search(r"IF unit\.runner_up_runtime", rep), \
        "the Runner-up row must be gated on unit.runner_up_runtime so it degrades gracefully"


def test_report_contract_round14_fixes():
    # Codex round-14: three more producer→consumer mismatches — two were my own mechanical-audit
    # misjudgments (assumed pct existed, assumed PROVENANCE path was right).
    rep = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "generate" / "generate-report.md")
    # #1 runner-up must be PER UNIT (derived inside the loop from that unit's scores), not a
    # global scalar shared across all agent units.
    assert "RUNNER_UP_RUNTIME" not in rep and "RUNNER_UP_SCORE" not in rep, \
        "runner-up must not be a global scalar; use per-unit unit.runner_up_*"
    assert re.search(r"unit\.runner_up_runtime.{0,220}per-unit loop|NOT a global scalar",
                     rep, re.DOTALL | re.IGNORECASE), \
        "runner-up must be documented as per-unit derived, not global"
    # #2 pct has no producer in scoring.json — the score loop must define the normalization
    # formula, and must NOT destructure pct from the scores map.
    assert "(runtime, score, pct) IN" not in rep, \
        "the scores map is {runtime: score}; pct must not be destructured from it"
    assert re.search(r"pct\s*=\s*ROUND\(100", rep), \
        "the score bar must define pct = ROUND(100 * score / MAX(...)) — a real normalization"
    # #3 provenance is layered (system.provenance + units[id].provenance), not top-level
    # answers.json.provenance.
    assert "answers.json.provenance" not in rep, \
        "PROVENANCE must read the layered system.provenance / units[id].provenance, not top-level"
    assert re.search(r"system\.provenance", rep) and re.search(r"units\[unit_id\]\.provenance", rep), \
        "the Assessment-inputs Source must look up the layered provenance by scope"


def _run_score_units(answers):
    import subprocess  # nosec B404 — test-only, fixed args
    import sys
    import tempfile

    script = pathlib.Path(__file__).parent / "score_units.py"
    with tempfile.TemporaryDirectory() as tmp:
        # No context-signals.json in this dir — mirrors a skipped-Discover run.
        answers_path = pathlib.Path(tmp) / "answers.json"
        answers_path.write_text(json.dumps(answers), encoding="utf-8")
        proc = subprocess.run(  # nosec B603 — test-only, fixed args
            [sys.executable, str(script), str(answers_path)],
            capture_output=True, text=True, check=True,
        )
    return json.loads(proc.stdout)


_SCORING_ANSWERS = {
    "entry_point": "build_scratch",
    "primary_unit": "solo",
    "system": {"ops_preference": "minimal", "existing_cluster": "none",
               "multi_cloud": "no", "platform_fit": "none"},
    "units": {
        "solo": {"workload_class": "agent_session", "session_duration": "15min_to_8hr",
                 "traffic_pattern": "steady", "session_state": "stateful",
                 "isolation": "nice_to_have", "memory_needs": "session_only",
                 "multi_agent": "no", "framework": "langgraph", "idle_resume": "none",
                 "compute_tier": "light", "launch_concurrency": "moderate",
                 "deployment_preference": "framework", "compliance": [],
                 "model_priority": "balanced", "region": "single"},
        "cron": {"workload_class": "batch"},
    },
}


def test_scoring_command_importable_and_wraps_units():
    # Codex round-15 P1, retargeted from the former inline interpreter one-liner to the
    # committed score_units.py: the Clarify scoring command must be runnable and must WRAP
    # results under {"units": {...}} (downstream reads .units[id]), not emit a bare
    # {unit_id: result} map.
    clarify = _norm(pathlib.Path(__file__).parent.parent
                    / "references" / "phases" / "clarify" / "clarify.md")
    assert re.search(r'score_units\.py"\s+"\$RUN_DIR/answers\.json"', clarify), \
        "clarify must invoke the committed score_units.py with answers.json as an argument"
    assert "python -c" not in clarify, \
        "clarify must not inline scoring code — committed scripts only (skills.sh RCE flag)"
    out = _run_score_units(_SCORING_ANSWERS)
    assert set(out["units"].keys()) == {"solo"}, \
        "results must be wrapped under a top-level 'units' key, agent_session units only"
    # single-unit collapse: primary unit's result must also be mirrored to the top level.
    for key, value in out["units"]["solo"].items():
        assert out.get(key) == value, \
            f"primary unit's '{key}' must be mirrored to the top level for legacy readers"


def test_build_diagram_single_unit_design_renders_from_unit():
    # Codex round-15 P2: a single-unit design must render from the design UNIT (effective_runtime,
    # model), not fall through to the legacy `result` path (which produced None/unknown).
    import build_diagram
    design = {
        "units": [{
            "id": "solo", "workload_class": "agent_session",
            "verdict": "agentcore", "effective_runtime": "agentcore",
            "deployment_model": "harness",
            "model_recommendation": {"model": "claude_sonnet_5"},
            "agentcore_services": ["memory"],
        }],
        "platform": {"mode": "split", "runtime": None, "interconnect": "in_process"},
    }
    # Pass a WRAPPED scoring-result as `result` (no top-level verdict/model) — the bug case.
    out = build_diagram.build_diagram({"units": {"solo": {}}}, {}, design=design)
    assert "AgentCore Runtime" in out["mermaid"], \
        "single-unit design must render the unit's effective_runtime, not None"
    assert "claude_sonnet_5" in out["mermaid"], \
        "single-unit design must render the unit's model, not 'unknown'"


def test_report_assessment_inputs_enumerates_layered_answers():
    # Codex round-15 P2: the Assessment-inputs table must flatten answers.system + each
    # answers.units[id] (excluding provenance), not iterate the impossible "ANSWERS + UNITS".
    rep = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "generate" / "generate-report.md")
    assert "(dim, value, scope, unit_id) IN ANSWERS + UNITS" not in rep, \
        "Assessment inputs must not iterate ANSWERS + UNITS (yields no dimensions)"
    assert re.search(r"FOR EACH \(dim, value\) IN ANSWER_LAYERS\.system EXCEPT", rep) and \
        re.search(r"FOR EACH \(dim, value\) IN ANSWER_LAYERS\.units\[unit_id\] EXCEPT", rep), \
        "Assessment inputs must flatten ANSWER_LAYERS.system + .units[id], excluding provenance"


def test_temporal_poc_dispatches_on_effective_runtime():
    # Codex round-15 P2: a temporal_worker_poll unit on EKS must get the eks (kubectl) base, not
    # always the ecs Terraform shape.
    shapes = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "decision-refs" / "poc-shapes.md")
    poc = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "poc" / "poc.md")
    assert re.search(r"[Bb]ase shape follows.{0,40}effective_runtime", shapes), \
        "the Temporal POC base shape must follow the unit's effective_runtime"
    assert re.search(r"effective_runtime == .?eks.{0,120}(eks|kubectl|Kubernetes)", shapes, re.DOTALL), \
        "an EKS temporal worker must use the eks/kubectl base, not ecs Terraform"
    assert re.search(r"effective.?runtime.{0,80}eks.{0,60}kubectl|eks.{0,40}NO Terraform", poc, re.DOTALL | re.IGNORECASE), \
        "poc.md temporal dispatch must route EKS workers to the kubectl base"


def test_runner_up_excludes_the_winner():
    # Codex round-15 P3: runner-up must EXCLUDE unit.verdict, not just be "2nd sorted" — else a
    # co_recommend winner picked from a tie can appear as its own runner-up.
    rep = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "generate" / "generate-report.md")
    assert re.search(r"runner_up_runtime.{0,200}EXCLUDING .?unit\.verdict", rep, re.DOTALL), \
        "runner-up must be the top score EXCLUDING unit.verdict, not the 2nd-sorted entry"


def test_scoring_reads_only_answers_json():
    # Codex round-17 P1, retargeted to the committed score_units.py: scoring must NOT open
    # context-signals.json (absent on skipped-Discover runs — build_scratch / no-path).
    # workload_class is persisted into answers.json.units[id] (Step 4), and entry_point read
    # from .phase-status.json — answers.json is always present.
    clarify = _norm(pathlib.Path(__file__).parent.parent
                    / "references" / "phases" / "clarify" / "clarify.md")
    src = (pathlib.Path(__file__).parent / "score_units.py").read_text(encoding="utf-8")
    assert "context-signals.json" not in src, \
        "the executed scoring code must not open context-signals.json (absent on skipped-Discover)"
    assert "sys.argv[1]" in src, \
        "scoring must read answers.json from argv (always present), never a hardcoded path"
    # behavioral: runs to completion in a directory that has ONLY answers.json
    out = _run_score_units(_SCORING_ANSWERS)
    assert "cron" not in out["units"], \
        "the filter must read workload_class from the answers.json unit entry (batch excluded)"
    # workload_class is persisted into answers.json units + filtered from there
    assert re.search(r'"workload_class":\s*"<class>"', clarify), \
        "answers.json units[] must persist workload_class (Step 4 schema)"
    assert 'info.get("workload_class") == "agent_session"' in src, \
        "the filter must read workload_class from the answers.json unit entry"
    # entry_point sourced from .phase-status.json, not context-signals.json
    assert re.search(r"entry_point.{0,80}\.phase-status\.json", clarify, re.DOTALL), \
        "entry_point must be read from .phase-status.json"


def test_clarify_scope_gate_requires_agent_unit():
    # Scope decision: agent-advisor is scoped to agentic systems. Clarify halts a purely
    # non-agent system (no agent_session unit) with _halt_and_inform, so every phase after may
    # assume >=1 agent unit. Round-24 P1: the gate must run BEFORE primary selection (an
    # all-non-agent system has no valid agent primary to pick/question).
    clarify_raw = (pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "clarify" / "clarify.md").read_text()
    clarify = re.sub(r"\s+", " ", clarify_raw)
    assert re.search(r"[Ss]cope gate", clarify) and re.search(r"BEFORE primary selection", clarify), \
        "clarify must have a scope gate that runs before primary selection"
    assert re.search(r"at least one .?agent_session.? unit", clarify, re.IGNORECASE), \
        "the gate must require >=1 agent_session unit"
    assert re.search(r"_halt_and_inform", clarify), \
        "the gate must halt (not silently proceed) for a purely non-agent system"
    # ORDERING: the scope-gate section must physically precede the "Primary unit" bullet.
    gate_pos = clarify_raw.find("Scope gate")
    primary_pos = clarify_raw.find("**Primary unit:**")
    assert 0 < gate_pos < primary_pos, \
        "the scope gate must appear before the Primary unit selection in the file"
    # the retired zero-agent sentinel/flag must be gone
    assert "no_agent_units" not in clarify, \
        "the no_agent_units zero-agent path must be removed (scoped out via the gate)"
    assert "'non_agent'" not in clarify and '"non_agent"' not in clarify, \
        "the non_agent sentinel must be gone"


def test_clarify_materializes_single_unit_when_no_inventory():
    # A single-workload build_scratch run has no unit in context-signals/context-notes; Clarify
    # materializes one — default agent_session (so the ordinary case passes the scope gate).
    clarify = _norm(pathlib.Path(__file__).parent.parent
                    / "references" / "phases" / "clarify" / "clarify.md")
    assert re.search(r"No inventory at all|MATERIALIZES exactly one .{0,20}unit", clarify), \
        "clarify must materialize a single unit when no inventory exists"
    assert re.search(r"workload_class.{0,40}defaults to .?agent_session", clarify, re.DOTALL), \
        "the materialized single unit defaults to agent_session"
    # the materialized record is COMPLETE (coupling/trigger/description/evidence) for downstream.
    for field in ["coupling", "trigger", "description", "evidence"]:
        assert field in clarify, \
            f"the materialized unit record must carry {field} for downstream fallback"


def test_scoring_result_schema_scored_only():
    # After scope-out, scoring-result.json is a single scored shape (no zero-agent variant): the
    # flat primary mirror + a non-empty units{} map whose values are scored per-unit results.
    import json
    schema = json.loads((pathlib.Path(__file__).parent.parent
                         / "scripts" / "schemas" / "scoring-result.json").read_text())
    assert "oneOf" not in schema, "schema must be a single scored shape (no zero-agent union)"
    assert "units" in schema.get("required", []), "scored shape must require units"
    try:
        import jsonschema
    except ImportError:
        return
    jsonschema.Draft7Validator.check_schema(schema)
    V = jsonschema.Draft7Validator(schema)
    _unit = {"verdict": "ecs", "scores": {"ecs": 10}, "eliminated": {},
             "deployment_model": None, "agentcore_services": [],
             "model_recommendation": {"model": "m", "reasoning": "r"},
             "deferred_verification_requirements": [],
             "recommendation_status": "final"}
    scored = {**_unit, "assumptions_used": [], "warnings": [], "units": {"solo": _unit}}
    assert V.is_valid(scored), "scored shape (wrapped, non-empty units) must validate"
    assert not V.is_valid({**scored, "units": {}}), "empty units must be rejected"
    assert not V.is_valid({k: v for k, v in scored.items() if k != "units"}), \
        "missing units must be rejected"
    assert not V.is_valid({**scored, "units": {"broken": {}}}), \
        "a units value missing scored fields must be rejected"
    assert not V.is_valid({**scored, "verdict": "non_agent"}), \
        "the retired non_agent sentinel must be rejected by the enum"
    # the zero-agent shape is no longer valid.
    assert not V.is_valid({"units": {}, "no_agent_units": True}), \
        "the retired zero-agent shape must no longer validate"


def test_confirm_persists_resolved_runtimes_including_temporal():
    # round-19 redesign: Confirm resolves every unit's runtime ONCE (incl temporal Tier-1 user
    # choices) into resolved_runtimes; Design consumes it verbatim and never re-asks.
    confirm = _norm(pathlib.Path(__file__).parent.parent
                    / "references" / "phases" / "confirm" / "confirm.md")
    design = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "design" / "design.md")
    assert "resolved_runtimes" in confirm, \
        "confirm must persist resolved_runtimes covering every unit"
    assert re.search(r"Tier-1 rule.{0,80}(user choice|AskUserQuestion).{0,120}resolved_runtimes",
                     confirm, re.DOTALL | re.IGNORECASE), \
        "confirm must persist the temporal Tier-1 user choice into resolved_runtimes"
    assert re.search(r"resolved_runtimes.{0,120}verbatim|Consume Confirm.{0,80}do NOT re-evaluate",
                     design, re.DOTALL | re.IGNORECASE), \
        "Design must consume resolved_runtimes verbatim, not re-evaluate temporal Tier 1"


def test_poc_gate_keys_on_effective_runtime_not_agent_pool():
    # round-19 redesign: Gate 2 / poc entry must offer any supported effective_runtime
    # (incl batch/fargate/serverless_workers), not just the agent-only scoring pool.
    gen = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "generate" / "generate.md")
    poc = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "poc" / "poc.md")
    plan = _norm(pathlib.Path(__file__).parent.parent
                 / "references" / "phases" / "migration-plan" / "migration-plan.md")
    for doc, name in [(gen, "generate"), (poc, "poc"), (plan, "migration-plan")]:
        assert re.search(r"effective_runtime", doc), \
            f"{name} POC gate must key on effective_runtime"
        assert re.search(r"batch.{0,20}fargate.{0,20}serverless_workers|serverless_workers", doc), \
            f"{name} POC gate must include batch/fargate/serverless_workers"


def test_confirm_resolves_temporal_via_temporal_md():
    # Codex round-18 P2: workload-classes.md has no temporal_worker_poll rule; a zero-agent
    # Temporal system must resolve its polling runtime via temporal.md Tier 1 for the platform gate.
    confirm = _norm(pathlib.Path(__file__).parent.parent
                    / "references" / "phases" / "confirm" / "confirm.md")
    assert re.search(r"temporal_worker_poll.{0,120}temporal\.md", confirm, re.DOTALL), \
        "confirm must resolve temporal_worker_poll units via temporal.md, not workload-classes.md"


def test_eks_temporal_cert_paths_mounted_as_volume():
    # Codex round-18 P2: TEMPORAL_TLS_*_PATH are file paths; secretKeyRef injects env values, so
    # the cert Secret keys must be mounted as a volume with the *_PATH vars set to mounted paths.
    shapes = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "decision-refs" / "poc-shapes.md")
    assert re.search(r"TEMPORAL_TLS_CA_PATH.{0,200}(volume|volumeMount|mounted)", shapes, re.DOTALL), \
        "cert *_PATH vars must be backed by a mounted volume, not secretKeyRef env values"


def test_assessment_inputs_excludes_workload_class_metadata():
    # Codex round-18 P3: after persisting workload_class into answer units, the Assessment-inputs
    # loop must exclude it (metadata, not a scored dimension), not render it with source=detected.
    rep = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "generate" / "generate-report.md")
    assert re.search(r'EXCEPT "provenance", "workload_class"', rep), \
        "the unit Assessment-inputs loop must exclude both provenance and workload_class"


def test_confirm_rescore_reuses_wrapper_command():
    # Codex round-16 P2: no-viable-runtime rescoring must reuse clarify's wrapper-producing
    # command, NOT invoke scoring.py directly (which writes a flat result and clobbers units{}).
    confirm = _norm(pathlib.Path(__file__).parent.parent
                    / "references" / "phases" / "confirm" / "confirm.md")
    assert re.search(r"Do NOT invoke .?scoring\.py.? directly", confirm, re.IGNORECASE), \
        "confirm rescoring must forbid direct scoring.py (it clobbers the units{} wrapper)"
    assert re.search(r"clarify\.md Step 5", confirm), \
        "confirm rescoring must reuse clarify.md Step 5's wrapper-producing command"
    assert "scripts/scoring.py $RUN_DIR/answers.json" not in confirm, \
        "the direct flat scoring.py rescore command must be gone"


def test_report_answer_layers_variable_defined():
    # Codex round-16 P2: the Assessment-inputs flattening reads ANSWER_LAYERS (the layered
    # answers.json), which must be a defined R0 variable — ANSWERS is only the primary merge.
    rep = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "generate" / "generate-report.md")
    assert len(re.findall(r"`?ANSWER_LAYERS`?", rep)) >= 2, \
        "ANSWER_LAYERS must be defined in R0 AND used by the Assessment-inputs flattening"
    assert re.search(r"ANSWER_LAYERS.{0,120}\.system.{0,40}\.units", rep, re.DOTALL), \
        "ANSWER_LAYERS must be sourced from the layered answers.json (.system + .units)"


def test_eks_temporal_poc_no_http_smoke_no_terraform_teardown():
    # Codex round-16 P2: the EKS Temporal shape must NOT inherit the generic EKS HTTP smoke
    # (a worker has no HTTP endpoint) and must NOT mandate terraform destroy (EKS uses kubectl).
    shapes = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "decision-refs" / "poc-shapes.md")
    # The EKS temporal variant must state there is NO service.yaml / no HTTP curl smoke.
    assert re.search(r"NO `?service\.yaml`?|exposes NO HTTP", shapes, re.IGNORECASE), \
        "EKS temporal POC must not inherit the HTTP service/port-forward smoke"
    assert re.search(r"kubectl logs", shapes), \
        "EKS temporal smoke proof must be via kubectl logs, not an HTTP curl"
    # Teardown must be base-conditional (kubectl delete on EKS, not terraform destroy).
    assert re.search(r"on \*\*EKS\*\*,?\s*`?kubectl delete", shapes, re.IGNORECASE) or \
        re.search(r"never `?terraform\s+destroy`? on the EKS base", shapes, re.IGNORECASE), \
        "EKS temporal teardown must be kubectl delete, never terraform destroy"


def test_build_diagram_preserves_authoritative_empty_services():
    # Codex round-16 P2: an explicit empty agentcore_services list means the user declined all
    # add-ons; the single-unit design path must NOT fall back to scoring defaults for [].
    import build_diagram
    design = {
        "units": [{
            "id": "solo", "workload_class": "agent_session",
            "verdict": "ecs", "effective_runtime": "ecs",
            "model_recommendation": {"model": "claude_sonnet_5"},
            "agentcore_services": [],  # authoritative: user declined all
        }],
        "platform": {"mode": "split", "runtime": None, "interconnect": "in_process"},
    }
    # result carries scoring defaults that must NOT leak in when the unit says [].
    result = {"verdict": "ecs", "agentcore_services": ["identity", "observability"],
              "model_recommendation": {"model": "claude_sonnet_5"}}
    out = build_diagram.build_diagram(result, {}, design=design)
    assert "Identity" not in out["mermaid"] and "Observability" not in out["mermaid"], \
        "an authoritative empty agentcore_services must not fall back to scoring defaults"


def test_design_effective_runtime_enum_includes_serverless_workers():
    # Codex round-16 P2: serverless_workers is a legal temporal Tier 1 outcome that Estimate/POC
    # dispatch on — it must be in Design's effective_runtime enum.
    design = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "design" / "design.md")
    assert re.search(r"effective_runtime.{0,200}serverless_workers", design, re.DOTALL), \
        "the effective_runtime enum must include serverless_workers"


def test_eks_temporal_artifacts_complete_and_not_ecs_runtask():
    # Codex round-17 P2: the EKS Temporal artifact list must include smoke_worker.py and a
    # concrete starter Job manifest, and the shared delta must not call the starter an
    # ECS-only run-task.
    shapes = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "decision-refs" / "poc-shapes.md")
    assert re.search(r"smoke_worker\.py", shapes) and re.search(r"smoke-job\.yaml", shapes), \
        "EKS temporal artifacts must include smoke_worker.py and k8s/smoke-job.yaml"
    # the shared delta must distinguish ECS run-task from EKS Job, not say run-task unconditionally
    assert re.search(r"ECS.{0,30}run-task.{0,60}EKS.{0,30}Job|EKS base a one-shot .?Job",
                     shapes, re.DOTALL), \
        "the starter must be specified per base (ECS run-task vs EKS Job)"
    # secret created from env/files, not committed in a generated secret.yaml
    assert re.search(r"do NOT commit connection material into\s*a generated .?secret\.yaml",
                     shapes, re.IGNORECASE), \
        "EKS temporal Secret must be created from env/files, not a committed secret.yaml"


def test_serverless_workers_has_no_card_derivation():
    # Codex round-17 P2: serverless_workers has no runtime card; Design must not try to load
    # serverless_workers.md and must derive key_change from temporal.md + poc-shapes.md.
    design = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "design" / "design.md")
    assert re.search(r"serverless_workers.{0,60}NO runtime card|NO runtime card.{0,60}serverless_workers",
                     design, re.DOTALL | re.IGNORECASE), \
        "design must state serverless_workers has no runtime card"
    assert re.search(r"[Dd]o NOT try to load .?serverless_workers\.md|skip this load for it",
                     design), \
        "design must not attempt to load a nonexistent serverless_workers.md"
    assert re.search(r"serverless_workers.{0,200}temporal\.md", design, re.DOTALL), \
        "serverless_workers key_change must derive from temporal.md + poc-shapes.md"


def test_design_consumes_resolved_runtimes_for_all_units():
    # Codex round-20 P1: Design must use confirm.resolved_runtimes verbatim for EVERY unit, not
    # re-evaluate temporal/workload rules (which can disagree with platform_decision).
    design = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "design" / "design.md")
    assert re.search(r"non-agent unit'?s? runtime comes from .?confirm\.json\.resolved_runtimes.{0,40}VERBATIM",
                     design, re.DOTALL | re.IGNORECASE), \
        "Design must consume resolved_runtimes verbatim for every non-agent unit"
    assert re.search(r"[Ff]allback (only|when).{0,80}resolved_runtimes is absent|[Ff]allback only:", design), \
        "rule re-evaluation must be a fallback, not the primary path"


def test_design_top_level_chosen_runtime_defined():
    # Codex round-20 P2: the legacy mirror must define top-level chosen_runtime (postcondition
    # requires it) — the primary unit's resolved runtime.
    design = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "design" / "design.md")
    assert re.search(r"top-level `?chosen_runtime`?.{0,120}resolved_runtimes\[primary_unit\]",
                     design, re.DOTALL), \
        "top-level chosen_runtime must be defined as the primary unit's resolved runtime"


def test_mixed_system_model_less_and_temporal_downstream():
    # Model-less non-agent units still occur in MIXED systems (an agent + a batch/service unit),
    # so the consumer-phase handling for model-less units + the temporal fixes survive the
    # scope-out; only the pure zero-agent branches were removed.
    gen = _norm(pathlib.Path(__file__).parent.parent / "references" / "phases" / "generate" / "generate.md")
    poc = _norm(pathlib.Path(__file__).parent.parent / "references" / "phases" / "poc" / "poc.md")
    pocrep = _norm(pathlib.Path(__file__).parent.parent / "references" / "phases" / "poc" / "poc-report.md")
    est = _norm(pathlib.Path(__file__).parent.parent / "references" / "phases" / "estimate" / "estimate.md")
    bd = (pathlib.Path(__file__).parent / "build_diagram.py").read_text()
    # poc resolves model only when non-null; model-less units omit Bedrock wiring
    assert re.search(r"whose `?model_recommendation`? is non-null", poc), \
        "poc Step 2 must resolve model only for non-null model_recommendation"
    assert re.search(r"[Mm]odel-less units.{0,200}omits all Bedrock wiring", poc, re.DOTALL), \
        "poc must define the model-less unit path (no Bedrock wiring)"
    # generate temporal gate on units[].workload_class, not temporal.units
    assert re.search(r"workload_class == .?temporal_worker_poll.{0,80}temporal.{0,20}block has no .?units", gen, re.DOTALL), \
        "generate temporal §3c must gate on units[].workload_class, not temporal.units"
    # generate serverless_workers no-card exception
    assert re.search(r"serverless_workers.{0,60}NO .{0,20}card", gen, re.DOTALL), \
        "generate must keep the serverless_workers no-card exception"
    # build_diagram omits the model node when model is unknown/None
    assert re.search(r'if model and model != "unknown":', bd), \
        "build_diagram must render the model node only when a real model exists"
    # poc-report diagram built per-unit from effective_runtime, not hardcoded AgentCore
    assert re.search(r"each on ITS OWN `?effective_runtime`?, NOT hardcoded to AgentCore", pocrep, re.DOTALL), \
        "poc-report diagram must be built per-unit from effective_runtime"
    # estimate: worker unit charges only polling; execution tier not re-added (double-count fix)
    assert re.search(r"DOUBLE-COUNT|do NOT also add execution cost into the worker unit", est, re.IGNORECASE), \
        "estimate must not double-count the execution tier into the worker unit"
    # the pure zero-agent branch language must be gone from generate's postcondition
    assert "ZERO-AGENT path" not in gen and "no_agent_units" not in gen, \
        "generate must not reference the removed zero-agent path"


def test_schema_validates_each_units_value():
    # Codex round-22 #6: the scored wrapper must validate each units[] value as a scored result,
    # not accept units:{"broken":{}}.
    import json
    schema = json.loads((pathlib.Path(__file__).parent.parent
                         / "scripts" / "schemas" / "scoring-result.json").read_text())
    assert "$defs" in schema and "scoredUnit" in schema["$defs"], \
        "schema must define a reusable scoredUnit and apply it to units values"
    try:
        import jsonschema
    except ImportError:
        return
    V = jsonschema.Draft7Validator(schema)
    bare = {"verdict": "ecs", "scores": {"ecs": 10}, "eliminated": {},
            "deployment_model": None, "agentcore_services": [],
            "model_recommendation": {"model": "m", "reasoning": "r"},
             "deferred_verification_requirements": [],
             "recommendation_status": "final",
            "assumptions_used": [], "warnings": []}
    assert V.is_valid({**bare, "units": {"solo": bare}}), "valid per-unit value must validate"
    assert not V.is_valid({**bare, "units": {"broken": {}}}), \
        "a units value missing scored fields must be rejected"


def test_scope_gate_after_temporal_activity_classification():
    # Codex round-25 P1: the scope gate must not halt a no-code Temporal workload before its
    # Activities are classified (a temporal_worker_poll-only seed would falsely halt).
    clarify = _norm(pathlib.Path(__file__).parent.parent
                    / "references" / "phases" / "clarify" / "clarify.md")
    assert re.search(r"[Dd]o NOT halt a Temporal system on the strength of a .?temporal_worker_poll",
                     clarify), \
        "the gate must not halt a Temporal system before its Activities are classified"
    assert re.search(r"Activity classification is part of building\s*the inventory.{0,80}BEFORE the scope gate",
                     clarify, re.DOTALL), \
        "no-code Activity classification must run before the scope gate concludes"


def test_poc_shapes_model_less_variants_per_shape():
    # Codex round-25 P1: each runtime shape (ecs/eks/lambda/batch) must have an explicit
    # model-less variant, not just the common-contract conditional.
    shapes = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "decision-refs" / "poc-shapes.md")
    # at least the common conditional + per-shape model-less notes
    assert shapes.count("Model-less variant") >= 3, \
        "ecs/eks/lambda/batch shapes must each carry an explicit model-less variant note"
    assert re.search(r"Bedrock wiring is CONDITIONAL on the unit'?s `?model_recommendation != null",
                     shapes), \
        "the common contract must gate Bedrock wiring on model_recommendation != null"
    # poc.md prereq: Bedrock model access only for model-bearing units
    poc = _norm(pathlib.Path(__file__).parent.parent
                / "references" / "phases" / "poc" / "poc.md")
    assert re.search(r"Bedrock model access for the\s*resolved model id ONLY when the unit is model-bearing",
                     poc, re.DOTALL), \
        "poc prerequisites must make Bedrock model access conditional on model-bearing units"


def test_round26_temporal_single_workload_and_multiunit_poc_report():
    # Codex round-26: (1) a single-workload Temporal signal still records a draft incl.
    # temporal_worker_poll, and the one-unit collapse does not skip Activity classification/gate;
    # (2) the POC report renders per-unit runtime/model, not a single global one.
    intake = _norm(pathlib.Path(__file__).parent.parent / "references" / "phases" / "intake" / "intake.md")
    clarify = _norm(pathlib.Path(__file__).parent.parent / "references" / "phases" / "clarify" / "clarify.md")
    pocrep = _norm(pathlib.Path(__file__).parent.parent / "references" / "phases" / "poc" / "poc-report.md")
    assert re.search(r"Temporal signal ALWAYS records a draft, even for a single workload", intake), \
        "intake must record a Temporal draft even for a single workload"
    assert re.search(r"Temporal Activity interview/classification below and the scope gate are NOT skippable",
                     clarify), \
        "the one-unit collapse must not skip the Temporal Activity classification or the scope gate"
    assert re.search(r"one node per\s*unit in .?UNITS.?, each on ITS OWN .?effective_runtime", pocrep, re.DOTALL), \
        "the POC report diagram must render per-unit runtimes, not a single global one"
    assert re.search(r"resolved Bedrock model PER UNIT", pocrep), \
        "the POC report must resolve model per unit, not a single global MODEL_DISPLAY"


def test_round26_model_less_prose_conditional():
    # Codex round-26 #3: W5 README, poc goal, and batch key_change must not claim Bedrock for a
    # model-less unit.
    shapes = _norm(pathlib.Path(__file__).parent.parent / "references" / "decision-refs" / "poc-shapes.md")
    poc = _norm(pathlib.Path(__file__).parent.parent / "references" / "phases" / "poc" / "poc.md")
    batch = _norm(pathlib.Path(__file__).parent.parent / "references" / "decision-refs" / "batch.md")
    assert re.search(r"do not claim Bedrock calls for a\s*model-less unit", shapes, re.DOTALL), \
        "W5 README claim must be conditional on model-bearing"
    assert re.search(r"Never claim .?Bedrock connectivity.? for a unit whose .?model_recommendation.? is null", poc), \
        "poc goal must not claim Bedrock connectivity for a model-less unit"
    assert re.search(r"`?bedrock:InvokeModel`? ONLY when the\s*job actually calls a model", batch, re.DOTALL), \
        "batch key_change source must make InvokeModel conditional on a model-calling job"


def test_round27_service_cards_model_less_conditional():
    # Codex round-27 P2: service-card model prose (batch Six Dimensions, ecs/eks/lambda IAM) must
    # not mandate bedrock:InvokeModel unconditionally — Design/Generate consume these for non-agent
    # units, so a model-less secondary unit would get false Bedrock IAM. Cards + a Design
    # consumption rule now condition Bedrock on model-bearing.
    dr = pathlib.Path(__file__).parent.parent / "references" / "decision-refs"
    for card in ["ecs.md", "eks.md", "lambda.md", "lambda-microvms.md"]:
        t = _norm(dr / card)
        assert re.search(r"bedrock:InvokeModel`? \(model-bearing units only", t), \
            f"{card} IAM must condition InvokeModel on model-bearing units"
    batch = _norm(dr / "batch.md")
    assert re.search(r"model-bearing jobs only", batch) and \
        re.search(r"model-less.{0,80}omits `?bedrock:InvokeModel", batch, re.DOTALL), \
        "batch card must condition its Bedrock items on a model-bearing job"
    design = _norm(pathlib.Path(__file__).parent.parent
                   / "references" / "phases" / "design" / "design.md")
    assert re.search(r"[Mm]odel-less consumption rule.{0,200}model_recommendation.? is null", design, re.DOTALL), \
        "Design must state the model-less card-consumption rule (strip Bedrock items)"
