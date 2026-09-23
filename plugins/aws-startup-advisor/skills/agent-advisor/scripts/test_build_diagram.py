import build_diagram


def test_resolve_runtime_single_winner():
    assert build_diagram.resolve_runtime(
        {"verdict": "agentcore"}, {}) == "agentcore"


def test_resolve_runtime_co_recommend_uses_confirm_choice():
    result = {"verdict": "co_recommend", "co_recommend": ["ecs", "eks"]}
    assert build_diagram.resolve_runtime(result, {"chosen_runtime": "eks"}) == "eks"


def test_resolve_runtime_co_recommend_falls_back_to_first():
    result = {"verdict": "co_recommend", "co_recommend": ["ecs", "eks"]}
    assert build_diagram.resolve_runtime(result, {}) == "ecs"


def test_resolve_runtime_no_viable():
    assert build_diagram.resolve_runtime(
        {"verdict": "no_viable_runtime"}, {}) == "none"


def test_labels_cover_all_runtimes():
    for rid in ("agentcore", "lambda_microvms", "ecs", "eks", "lambda"):
        assert rid in build_diagram.RUNTIME_LABELS


def test_service_labels_include_payments_and_registry():
    # Conditional AgentCore services (SA feedback: relevant but not always).
    assert build_diagram.SERVICE_LABELS["payments"] == "Payments"
    assert build_diagram.SERVICE_LABELS["registry"] == "Registry"


def test_payments_registry_render_in_diagram():
    out = build_diagram.render_mermaid(
        "agentcore", ["identity", "payments", "registry"], "claude_sonnet_5", "harness")
    assert "Payments" in out and "Registry" in out


def test_resolve_services_prefers_confirm():
    result = {"agentcore_services": ["identity", "observability"]}
    confirm = {"agentcore_services": ["identity", "memory", "gateway"]}
    assert build_diagram.resolve_services(result, confirm) == [
        "identity", "memory", "gateway"]


def test_resolve_services_falls_back_to_result():
    result = {"agentcore_services": ["identity", "observability"]}
    assert build_diagram.resolve_services(result, {}) == [
        "identity", "observability"]


def test_resolve_services_filters_unknown_and_dedupes():
    confirm = {"agentcore_services": ["identity", "identity", "bogus", "memory"]}
    assert build_diagram.resolve_services({}, confirm) == ["identity", "memory"]


def test_mermaid_has_runtime_model_and_services():
    out = build_diagram.render_mermaid(
        "agentcore", ["identity", "memory"], "claude_sonnet_5", "harness")
    assert out.startswith("flowchart TD")
    assert "AgentCore Runtime" in out
    assert "harness" in out.lower()
    assert "claude_sonnet_5" in out
    assert "Identity" in out and "Memory" in out
    assert "migration skill" not in out  # no handoff for agentcore


def test_mermaid_model_is_solid_edge_services_are_dotted():
    # Topology: the model is a downstream call (solid invoke edge); services are
    # cross-cutting capabilities attached with a dotted edge into a subgraph.
    out = build_diagram.render_mermaid(
        "agentcore", ["identity", "memory"], "claude_sonnet_5", "harness")
    assert "rt -->|invoke| model" in out       # model = solid data-flow edge
    assert 'subgraph svcs["AgentCore services"]' in out
    assert "rt -.-> svcs" in out               # services = dotted attachment
    # Services must NOT be flat solid children of the runtime anymore.
    assert "rt --> svc_identity" not in out


def test_mermaid_no_services_no_subgraph():
    out = build_diagram.render_mermaid(
        "agentcore", [], "claude_sonnet_5", "harness")
    assert "subgraph" not in out
    assert "rt -->|invoke| model" in out


def test_mermaid_adds_handoff_note_for_ecs():
    out = build_diagram.render_mermaid("ecs", [], "claude_sonnet_5", None)
    assert "Amazon ECS (Fargate)" in out
    assert "migration skill" in out


def test_mermaid_deterministic():
    a = build_diagram.render_mermaid("agentcore", ["identity", "memory"],
                                     "claude_sonnet_5", "harness")
    b = build_diagram.render_mermaid("agentcore", ["identity", "memory"],
                                     "claude_sonnet_5", "harness")
    assert a == b


def test_ascii_contains_runtime_model_services():
    out = build_diagram.render_ascii(
        "agentcore", ["identity", "memory"], "claude_sonnet_5", "harness")
    assert "AgentCore Runtime" in out
    assert "harness" in out.lower()
    assert "claude_sonnet_5" in out
    assert "- Identity" in out and "- Memory" in out
    assert "migration skill" not in out
    # Model is on the primary flow; services are attached, not call targets.
    assert "invoke" in out
    assert "attached AgentCore services" in out


def test_ascii_handoff_for_ecs():
    out = build_diagram.render_ascii("ecs", [], "claude_sonnet_5", None)
    assert "Amazon ECS" in out
    assert "migration skill" in out


def test_ascii_no_handoff_for_standard_lambda():
    # Standard Lambda is a self-contained Build target (function skeleton), not a
    # heavy-infrastructure handoff — no migration skill note.
    out = build_diagram.render_ascii("lambda", [], "claude_sonnet_5", None)
    assert "AWS Lambda" in out
    assert "migration skill" not in out


def test_ascii_deterministic():
    a = build_diagram.render_ascii("eks", ["identity"], "claude_sonnet_5", None)
    b = build_diagram.render_ascii("eks", ["identity"], "claude_sonnet_5", None)
    assert a == b


def test_build_diagram_end_to_end():
    result = {"verdict": "agentcore", "deployment_model": "harness",
              "agentcore_services": ["identity"],
              "model_recommendation": {"model": "claude_sonnet_5"}}
    out = build_diagram.build_diagram(result, {})
    assert "flowchart TD" in out["mermaid"]
    assert "AgentCore Runtime" in out["ascii"]


def test_build_diagram_no_viable():
    out = build_diagram.build_diagram({"verdict": "no_viable_runtime"}, {})
    assert "No viable runtime" in out["mermaid"]
    assert "No viable runtime" in out["ascii"]


def test_golden_agentcore_full():
    result = {"verdict": "agentcore", "deployment_model": "framework_on_runtime",
              "agentcore_services": ["identity", "observability", "memory", "gateway"],
              "model_recommendation": {"model": "claude_sonnet_5"}}
    out = build_diagram.build_diagram(result, {})
    # runtime + deployment model + all four services + model, no handoff
    assert "framework_on_runtime" in out["mermaid"]
    for svc in ("Identity", "Observability", "Memory", "Gateway"):
        assert svc in out["mermaid"] and svc in out["ascii"]
    assert "migration skill" not in out["mermaid"]


def test_golden_lambda_microvms_no_services_no_handoff():
    result = {"verdict": "lambda_microvms", "deployment_model": None,
              "agentcore_services": [],
              "model_recommendation": {"model": "claude_sonnet_5"}}
    out = build_diagram.build_diagram(result, {})
    assert "Lambda MicroVMs" in out["mermaid"]
    assert "migration skill" not in out["mermaid"]  # MicroVMs is not a handoff runtime


def test_golden_ecs_has_handoff():
    result = {"verdict": "ecs", "deployment_model": None,
              "agentcore_services": ["identity"],
              "model_recommendation": {"model": "claude_sonnet_5"}}
    out = build_diagram.build_diagram(result, {})
    assert "migration skill" in out["mermaid"]
    assert "migration skill" in out["ascii"]


def test_golden_co_recommend_renders_chosen():
    result = {"verdict": "co_recommend", "co_recommend": ["ecs", "eks"],
              "deployment_model": None, "agentcore_services": [],
              "model_recommendation": {"model": "claude_sonnet_5"}}
    out = build_diagram.build_diagram(result, {"chosen_runtime": "eks"})
    assert "Amazon EKS" in out["mermaid"]
    assert "migration skill" in out["mermaid"]  # eks is a handoff runtime


def _two_unit_design():
    return {
        "units": [
            {"id": "chat-agent", "workload_class": "agent_session",
             "verdict": "agentcore",
             "model_recommendation": {"model": "claude_sonnet_5"}},
            {"id": "summarizer", "workload_class": "batch", "verdict": "batch",
             "model_recommendation": None},
        ],
        "platform": {"mode": "split", "runtime": None, "interconnect": "queue",
                     "shared_services": []},
    }


def test_multi_unit_renders_subgraph_per_unit():
    out = build_diagram.build_diagram({}, {}, design=_two_unit_design())
    assert "chat-agent" in out["mermaid"] and "summarizer" in out["mermaid"]
    assert out["mermaid"].count("subgraph") >= 2


def test_multi_unit_interconnect_edge():
    out = build_diagram.build_diagram({}, {}, design=_two_unit_design())
    assert "queue" in out["mermaid"].lower()


def _consolidated_design():
    # Codex #2: consolidated onto ECS — the diagram must render each unit on its
    # effective_runtime (ecs), NOT its raw verdict (agentcore/batch).
    return {
        "units": [
            {"id": "chat-agent", "workload_class": "agent_session",
             "verdict": "agentcore", "effective_runtime": "ecs",
             "model_recommendation": {"model": "claude_sonnet_5"}},
            {"id": "summarizer", "workload_class": "batch",
             "verdict": "batch", "effective_runtime": "ecs",
             "model_recommendation": None},
        ],
        "platform": {"mode": "consolidated", "runtime": "ecs", "interconnect": "none",
                     "shared_services": []},
    }


def test_consolidated_diagram_renders_effective_runtime_not_verdict():
    out = build_diagram.build_diagram({}, {}, design=_consolidated_design())
    m = out["mermaid"]
    # Both units render as ECS (the consolidated target)...
    assert m.count("Amazon ECS (Fargate)") >= 2
    # ...not their raw best-fit verdicts.
    assert "AgentCore Runtime" not in m
    assert "AWS Batch" not in m


def _mixed_coupling_design():
    # Codex #5: interconnect == queue means "at least one queue coupling exists", not
    # "every unit is on the queue". The independent (coupling none) unit must NOT be wired.
    return {
        "units": [
            {"id": "producer", "workload_class": "service", "verdict": "fargate",
             "coupling": {"mode": "queue", "interacts_with": ["consumer"]},
             "model_recommendation": None},
            {"id": "consumer", "workload_class": "light_io", "verdict": "lambda",
             "coupling": {"mode": "none", "interacts_with": []},
             "model_recommendation": None},
            {"id": "loner", "workload_class": "batch", "verdict": "batch",
             "coupling": {"mode": "none", "interacts_with": []},
             "model_recommendation": None},
        ],
        "platform": {"mode": "split", "runtime": None, "interconnect": "queue",
                     "shared_services": []},
    }


def test_queue_interconnect_follows_one_way_coupling():
    # Codex round-3 #4: a one-way coupling is producer mode:queue interacts_with [consumer],
    # consumer mode:none. BOTH ends must be on the queue; the truly independent unit must not.
    out = build_diagram.build_diagram({}, {}, design=_mixed_coupling_design())
    m = out["mermaid"]
    assert "producer -.-> queue" in m
    # The consumer is mode:none but is the target of the producer's queue coupling — wired.
    assert "consumer -.-> queue" in m
    # The independent unit (neither queue nor a coupling target) is drawn but NOT wired.
    assert "loner" in m
    assert "loner -.-> queue" not in m


def _mixed_gateway_design():
    # Codex round-4 #2: gateway must filter like queue — connect only api/a2a-coupled units
    # (and their interacts_with targets), never independent mode:none units.
    return {
        "units": [
            {"id": "orchestrator", "workload_class": "agent_session", "verdict": "agentcore",
             "coupling": {"mode": "a2a", "interacts_with": ["tool-agent"]},
             "model_recommendation": {"model": "claude_sonnet_5"}},
            {"id": "tool-agent", "workload_class": "agent_session", "verdict": "agentcore",
             "coupling": {"mode": "none", "interacts_with": []},
             "model_recommendation": {"model": "claude_sonnet_5"}},
            {"id": "loner", "workload_class": "batch", "verdict": "batch",
             "coupling": {"mode": "none", "interacts_with": []},
             "model_recommendation": None},
        ],
        "platform": {"mode": "split", "runtime": None, "interconnect": "gateway",
                     "shared_services": []},
    }


def test_gateway_interconnect_only_wires_gateway_coupled_units():
    out = build_diagram.build_diagram({}, {}, design=_mixed_gateway_design())
    m = out["mermaid"]
    # Node ids are sanitized (hyphens → underscores).
    assert "orchestrator -.-> gateway" in m
    # tool-agent is mode:none but is the a2a target — wired.
    assert "tool_agent -.-> gateway" in m
    # The independent unit must NOT be wired to the gateway.
    assert "loner" in m
    assert "loner -.-> gateway" not in m


def _mixed_queue_and_gateway_design():
    # Codex round-5 #1: a system can mix couplings — an api pair AND a queue pair. Design records
    # only the dominant platform.interconnect (gateway wins), but BOTH must be drawn; the queue
    # relationship must not vanish just because a gateway coupling also exists.
    return {
        "units": [
            {"id": "api-a", "workload_class": "agent_session", "verdict": "agentcore",
             "coupling": {"mode": "api", "interacts_with": ["api-b"]},
             "model_recommendation": {"model": "claude_sonnet_5"}},
            {"id": "api-b", "workload_class": "service", "verdict": "fargate",
             "coupling": {"mode": "none", "interacts_with": []},
             "model_recommendation": None},
            {"id": "q-producer", "workload_class": "service", "verdict": "fargate",
             "coupling": {"mode": "queue", "interacts_with": ["q-consumer"]},
             "model_recommendation": None},
            {"id": "q-consumer", "workload_class": "batch", "verdict": "batch",
             "coupling": {"mode": "none", "interacts_with": []},
             "model_recommendation": None},
        ],
        # gateway wins as the single dominant interconnect value...
        "platform": {"mode": "split", "runtime": None, "interconnect": "gateway",
                     "shared_services": []},
    }


def test_mixed_queue_and_gateway_both_rendered():
    out = build_diagram.build_diagram({}, {}, design=_mixed_queue_and_gateway_design())
    m = out["mermaid"]
    # Gateway pair wired.
    assert "api_a -.-> gateway" in m and "api_b -.-> gateway" in m
    # Queue pair must ALSO be wired — not lost to the exclusive branch.
    assert 'queue["Queue"]' in m
    assert "q_producer -.-> queue" in m and "q_consumer -.-> queue" in m
    # Cross-wiring must not happen (queue units not on gateway, api units not on queue).
    assert "q_producer -.-> gateway" not in m
    assert "api_a -.-> queue" not in m


def test_single_unit_design_falls_back_to_legacy_render():
    d = {"units": [_two_unit_design()["units"][0]],
         "platform": {"mode": "split", "runtime": None,
                      "interconnect": "in_process", "shared_services": []}}
    legacy = build_diagram.build_diagram(
        {"verdict": "agentcore",
         "agentcore_services": [],
         "model_recommendation": {"model": "claude_sonnet_5"}}, {})
    unitized = build_diagram.build_diagram(
        {"verdict": "agentcore",
         "agentcore_services": [],
         "model_recommendation": {"model": "claude_sonnet_5"}}, {}, design=d)
    assert unitized["mermaid"] == legacy["mermaid"], \
        "collapse invariant: one unit renders exactly the legacy diagram"


def _temporal_design():
    return {
        "units": [
            {"id": "worker-fleet", "workload_class": "temporal_worker_poll",
             "verdict": "ecs", "queues": ["agent-tasks", "batch-tasks"],
             "model_recommendation": None},
            {"id": "doc-chat", "workload_class": "agent_session",
             "verdict": "agentcore",
             "model_recommendation": {"model": "claude_sonnet_5"},
             "task_queue": "agent-tasks"},
            {"id": "ocr", "workload_class": "batch", "verdict": "batch",
             "model_recommendation": None,
             "task_queue": "batch-tasks"},
        ],
        "platform": {"mode": "split", "runtime": None, "interconnect": "none",
                     "shared_services": []},
        "temporal": {"way": "cloud", "server": "Temporal Cloud"},
    }


def _temporal_design_multi_fleet():
    # Two fleets, each polling its OWN queue; each Activity runs on exactly one queue.
    # A correct diagram connects fleet-a -> chat (agent-tasks) and fleet-b -> ocr
    # (batch-tasks), NEVER the cartesian product (fleet-a -> ocr, fleet-b -> chat).
    return {
        "units": [
            {"id": "fleet-a", "workload_class": "temporal_worker_poll",
             "verdict": "ecs", "queues": ["agent-tasks"], "model_recommendation": None},
            {"id": "fleet-b", "workload_class": "temporal_worker_poll",
             "verdict": "ecs", "queues": ["batch-tasks"], "model_recommendation": None},
            {"id": "chat", "workload_class": "agent_session", "verdict": "agentcore",
             "model_recommendation": {"model": "claude_sonnet_5"},
             "task_queue": "agent-tasks"},
            {"id": "ocr", "workload_class": "batch", "verdict": "batch",
             "model_recommendation": None, "task_queue": "batch-tasks"},
        ],
        "platform": {"mode": "split", "runtime": None, "interconnect": "none",
                     "shared_services": []},
        "temporal": {"way": "self_hosted", "server": "self-hosted"},
    }


def test_temporal_self_hosted_not_labeled_cloud():
    # #4: a self_hosted Way must not be rendered as "Temporal Cloud".
    out = build_diagram.build_diagram({}, {}, design=_temporal_design_multi_fleet())
    assert "Temporal Cloud" not in out["mermaid"]
    assert "Temporal Cloud" not in out["ascii"]
    assert "self-hosted" in out["mermaid"]
    assert "self-hosted" in out["ascii"]


def test_temporal_multi_fleet_no_cartesian_product():
    # #3: each fleet connects ONLY to the Activity on its own queue.
    out = build_diagram.build_diagram({}, {}, design=_temporal_design_multi_fleet())
    m = out["mermaid"]
    # Correct edges present.
    assert "fleet_a -->|agent-tasks| chat" in m
    assert "fleet_b -->|batch-tasks| ocr" in m
    # Cross edges (cartesian product) must NOT appear.
    assert "fleet_a -->|batch-tasks| ocr" not in m
    assert "fleet_a --> ocr" not in m
    assert "fleet_b --> chat" not in m
    assert "fleet_b -->|agent-tasks| chat" not in m


def test_temporal_topology_renders_temporal_cloud_node():
    out = build_diagram.build_diagram({}, {}, design=_temporal_design())
    assert "Temporal Cloud" in out["mermaid"]
    assert "orchestrator" in out["mermaid"]
    assert "Temporal Cloud" in out["ascii"]


def test_temporal_topology_connects_worker_poll_unit():
    out = build_diagram.build_diagram({}, {}, design=_temporal_design())
    # Temporal Cloud should connect to worker-fleet
    assert "temporal_cloud --> worker_fleet" in out["mermaid"]
    # Worker should connect to activity units
    assert "worker_fleet -->" in out["mermaid"]
    assert "doc_chat" in out["mermaid"] or "doc-chat" in out["mermaid"]


def test_temporal_topology_no_user_edge():
    out = build_diagram.build_diagram({}, {}, design=_temporal_design())
    # Should NOT have user -> agent edge in Temporal systems
    assert 'user["User' not in out["mermaid"]
    assert "User / Client" not in out["ascii"] or "Temporal Cloud" in out["ascii"]


def test_temporal_topology_no_inter_unit_queue_chain():
    out = build_diagram.build_diagram({}, {}, design=_temporal_design())
    # Should NOT have a separate queue node chaining units
    assert 'queue["Queue"]' not in out["mermaid"]
    assert "Interconnect: Queue" not in out["ascii"]


def test_temporal_topology_with_task_queue_labels():
    out = build_diagram.build_diagram({}, {}, design=_temporal_design())
    # Should label edges with task queue names when available
    assert "agent-tasks" in out["mermaid"] or "batch-tasks" in out["mermaid"]


def test_multi_unit_handoff_node_for_ecs_units():
    # Audit finding #2: the multi-unit diagram must show the "configured by migration skill"
    # handoff indicator for units on a HANDOFF_RUNTIME — same as the single-unit path — instead
    # of silently dropping it. Consolidated-onto-ECS is the canonical case.
    out = build_diagram.build_diagram({}, {}, design=_consolidated_design())
    assert "migration skill" in out["mermaid"], \
        "multi-unit Mermaid must render the handoff node for ECS/EKS/Fargate/Batch units"
    assert "migration skill" in out["ascii"], \
        "multi-unit ASCII must render the handoff note (twin of the Mermaid path)"


def test_multi_unit_no_handoff_for_self_contained_units():
    # The inverse: an all-Lambda/AgentCore multi-unit system needs NO handoff indicator.
    design = {
        "units": [
            {"id": "a", "workload_class": "agent_session", "verdict": "agentcore",
             "effective_runtime": "agentcore", "model_recommendation": None},
            {"id": "b", "workload_class": "light_io", "verdict": "lambda",
             "effective_runtime": "lambda", "model_recommendation": None},
        ],
        "platform": {"mode": "split", "runtime": None, "interconnect": "none",
                     "shared_services": []},
    }
    out = build_diagram.build_diagram({}, {}, design=design)
    assert "migration skill" not in out["mermaid"]
    assert "migration skill" not in out["ascii"]


def test_units_needing_handoff_covers_all_four_runtimes():
    # units_needing_handoff must key on the same set as HANDOFF_RUNTIMES (ecs/eks/fargate/batch).
    units = [
        {"id": "e", "effective_runtime": "ecs"},
        {"id": "k", "effective_runtime": "eks"},
        {"id": "f", "effective_runtime": "fargate"},
        {"id": "b", "effective_runtime": "batch"},
        {"id": "l", "effective_runtime": "lambda"},
        {"id": "a", "effective_runtime": "agentcore"},
        {"id": "m", "effective_runtime": "lambda_microvms"},
    ]
    got = {u["id"] for u in build_diagram.units_needing_handoff(units)}
    assert got == {"e", "k", "f", "b"}, \
        "handoff set must be exactly ecs/eks/fargate/batch; lambda/agentcore/microvms self-contained"
