"""Deterministic architecture-diagram composer for agent-advisor.

Pure: (scoring-result, confirm) dicts -> {"mermaid": str, "ascii": str}.
Same input -> byte-identical output. No timestamps, no randomness.
"""
import json
import pathlib

RUNTIME_LABELS = {
    "agentcore": "AgentCore Runtime",
    "lambda_microvms": "Lambda MicroVMs",
    "ecs": "Amazon ECS (Fargate)",
    "eks": "Amazon EKS",
    "lambda": "AWS Lambda",
    "batch": "AWS Batch",
    "fargate": "AWS Fargate",
    "serverless_workers": "Temporal Serverless Workers (Public Preview)",
    "none": "No viable runtime",
}

SERVICE_LABELS = {
    "identity": "Identity",
    "observability": "Observability",
    "evaluations": "Evaluations",
    "optimization": "Optimization",
    "memory": "Memory",
    "gateway": "Gateway",
    "policy": "Policy",
    "managed_kb": "Managed KB",
    "code_interpreter": "Code Interpreter",
    "browser": "Browser",
    "web_search": "Web Search",
    "sandbox": "Sandbox",
    "payments": "Payments",
    "registry": "Registry",
}

# Runtimes whose compute layer needs heavy infrastructure execution (clusters,
# Terraform) handed off to the migration skill. AgentCore, Lambda MicroVMs, and
# standard Lambda are self-contained deliverables from this advisor — not handoffs.
# Runtimes that hand the compute layer to the migration skill (their service cards say so):
# ECS, EKS, Fargate (= ECS), and AWS Batch. AgentCore, standard Lambda, and Lambda MicroVMs
# are self-contained. Keep in sync with design.md's handoff_required definition.
HANDOFF_RUNTIMES = {"ecs", "eks", "fargate", "batch"}


def unit_runtime(unit):
    """The runtime a unit ACTUALLY deploys on — effective_runtime under a consolidated
    platform, falling back to verdict for split runs (or older design.json without the
    field). The diagram must render where the unit really runs, not its best-fit verdict."""
    return unit.get("effective_runtime") or unit.get("verdict", "unknown")


def units_on_interconnect(units, modes):
    """Units coupled via any coupling.mode in `modes`, PLUS the target ends of their one-way
    interacts_with couplings (e.g. a producer mode:queue interacts_with a consumer mode:none —
    the consumer is on the queue too). A system can MIX couplings (some units on a queue, others
    via a gateway); each interconnect is computed independently from per-unit coupling.mode, not
    from the single dominant platform.interconnect value. Returns [] when no unit uses `modes`."""
    by_id = {u["id"]: u for u in units}
    on = set()
    for u in units:
        coup = u.get("coupling", {})
        if coup.get("mode") in modes:
            on.add(u["id"])
            for tgt in coup.get("interacts_with", []):
                if tgt in by_id:
                    on.add(tgt)
    return [u for u in units if u["id"] in on]


def units_needing_handoff(units):
    """Units whose ACTUAL runtime (effective_runtime||verdict) hands the compute layer to
    the migration skill — i.e. is in HANDOFF_RUNTIMES. Mirrors the single-unit path's handoff node so
    a multi-unit ECS/EKS/Fargate/Batch system shows the same 'configured by the migration skill'
    indicator instead of silently dropping it. Returns [] when no unit needs a handoff."""
    return [u for u in units if unit_runtime(u) in HANDOFF_RUNTIMES]


def resolve_runtime(result, confirm):
    verdict = result.get("verdict")
    if verdict == "co_recommend":
        return confirm.get("chosen_runtime") or result.get("co_recommend", ["none"])[0]
    if verdict == "no_viable_runtime":
        return "none"
    return verdict


def resolve_services(result, confirm):
    services = confirm.get("agentcore_services") or result.get("agentcore_services", [])
    seen, out = set(), []
    for sid in services:
        if sid in SERVICE_LABELS and sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


def render_mermaid(runtime, services, model, deployment_model):
    label = RUNTIME_LABELS.get(runtime, runtime)
    if runtime == "agentcore" and deployment_model:
        label = f"{label}<br/>({deployment_model})"
    lines = ["flowchart TD"]
    # Primary request/data flow (solid): user invokes the runtime, runtime calls the model.
    lines.append(f'    user["User / Client"]')
    lines.append(f'    rt["{label}"]')
    lines.append("    user -->|request| rt")
    # A model-less unit (non-agent: batch/service/light_io that calls no Bedrock model) has no
    # model node or invoke edge — do not render "Bedrock model: unknown".
    if model and model != "unknown":
        lines.append(f'    model["Bedrock model:<br/>{model}"]')
        lines.append("    rt -->|invoke| model")
    # AgentCore services are cross-cutting capabilities attached to the runtime, NOT
    # downstream call targets — group them in a subgraph and attach with dotted edges.
    if services:
        lines.append('    subgraph svcs["AgentCore services"]')
        lines.append("        direction LR")
        for sid in services:
            lines.append(f'        svc_{sid}["{SERVICE_LABELS[sid]}"]')
        lines.append("    end")
        lines.append("    rt -.-> svcs")
    if runtime in HANDOFF_RUNTIMES:
        lines.append('    handoff["Compute configured by the migration skill"]')
        lines.append("    rt -.-> handoff")
    return "\n".join(lines)


def render_ascii(runtime, services, model, deployment_model):
    label = RUNTIME_LABELS.get(runtime, runtime)
    if runtime == "agentcore" and deployment_model:
        label = f"{label} ({deployment_model})"
    # Primary flow: user -> runtime (-> Bedrock model, only if the unit calls one).
    lines = [
        "User / Client",
        "    |  request",
        "    v",
        f"[ {label} ]",
    ]
    if model and model != "unknown":
        lines += [f"    |  invoke", "    v", f"Bedrock model: {model}"]
    # Services are attached capabilities, shown separately (not as call targets).
    if services:
        lines.append("")
        lines.append(f"[ {label} ] .. attached AgentCore services:")
        for sid in services:
            lines.append(f"  - {SERVICE_LABELS[sid]}")
    if runtime in HANDOFF_RUNTIMES:
        lines.append("")
        lines.append("Note: compute configured by the migration skill")
    return "\n".join(lines)


def render_multi_unit_mermaid(design):
    lines = ["flowchart TD"]
    units = design.get("units", [])
    platform = design.get("platform", {})
    interconnect = platform.get("interconnect", "none")
    temporal_block = design.get("temporal", {})

    # Sanitize unit id for mermaid node id (replace hyphens with underscores)
    def sanitize_id(uid):
        return uid.replace("-", "_")

    # Check if this is a Temporal system
    worker_poll_units = [u for u in units if u.get("workload_class") == "temporal_worker_poll"]
    is_temporal = bool(worker_poll_units or temporal_block)

    if is_temporal:
        # Temporal topology: Temporal Server → worker_poll unit → Activity units.
        # The orchestrator label reflects the chosen Way (self-hosted stays self-hosted).
        way = temporal_block.get("way", "unknown")
        if way == "self_hosted":
            orch_label = "Temporal Server<br/>(self-hosted, orchestrator)"
        elif way == "cloud":
            orch_label = "Temporal Cloud<br/>(orchestrator)"
        else:
            orch_label = "Temporal Server<br/>(orchestrator)"
        lines.append(f'    temporal_cloud["{orch_label}"]')

        # Render each unit as a subgraph
        for unit in units:
            uid = unit["id"]
            sanitized_id = sanitize_id(uid)
            verdict = unit_runtime(unit)
            model_rec = unit.get("model_recommendation")

            # Build node label with runtime and model
            label_parts = [RUNTIME_LABELS.get(verdict, verdict)]
            if model_rec and model_rec.get("model"):
                label_parts.append(model_rec["model"])
            node_label = "<br/>".join(label_parts)

            lines.append(f'    subgraph {sanitized_id}["{uid}"]')
            lines.append(f'        {sanitized_id}_node["{node_label}"]')
            lines.append('    end')

        # Connect Temporal Cloud to worker_poll units
        for unit in worker_poll_units:
            sanitized_id = sanitize_id(unit["id"])
            lines.append(f"    temporal_cloud --> {sanitized_id}")

        # Connect each worker fleet ONLY to the Activity units it actually executes —
        # matched by queue membership (fleet.queues[] contains the Activity's task_queue),
        # never a cartesian product across all fleets. Fall back to a single-fleet
        # connect-all only when the fleet/queue data can't disambiguate.
        non_worker_units = [u for u in units if u.get("workload_class") != "temporal_worker_poll"]
        single_fleet = len(worker_poll_units) == 1
        for worker in worker_poll_units:
            worker_id = sanitize_id(worker["id"])
            fleet_queues = set(worker.get("queues", []))
            for activity_unit in non_worker_units:
                activity_id = sanitize_id(activity_unit["id"])
                task_queue = activity_unit.get("task_queue", "")
                if task_queue and fleet_queues:
                    # Only connect when this Activity runs on a queue this fleet polls.
                    if task_queue not in fleet_queues:
                        continue
                    lines.append(f"    {worker_id} -->|{task_queue}| {activity_id}")
                elif single_fleet:
                    # One fleet, no queue metadata to split on: it runs every Activity.
                    if task_queue:
                        lines.append(f"    {worker_id} -->|{task_queue}| {activity_id}")
                    else:
                        lines.append(f"    {worker_id} --> {activity_id}")
                # Multiple fleets without queue data: cannot attribute — leave unconnected
                # rather than draw a false cartesian-product edge.
    else:
        # Generic multi-unit topology
        lines.append('    user["User / Client"]')

        # NOTE: unlike the single-unit path, the multi-unit diagram does NOT draw a per-unit
        # AgentCore-services subgraph — with N units it would clutter the topology, and the
        # Generate report already lists each unit's agentcore_services in its per-unit table.
        # The handoff indicator (below) IS mirrored because it reflects a topology fact.

        # Render each unit as a subgraph
        agent_session_units = []
        for unit in units:
            uid = unit["id"]
            sanitized_id = sanitize_id(uid)
            verdict = unit_runtime(unit)
            model_rec = unit.get("model_recommendation")

            # Build node label with runtime and model
            label_parts = [RUNTIME_LABELS.get(verdict, verdict)]
            if model_rec and model_rec.get("model"):
                label_parts.append(model_rec["model"])
            node_label = "<br/>".join(label_parts)

            lines.append(f'    subgraph {sanitized_id}["{uid}"]')
            lines.append(f'        {sanitized_id}_node["{node_label}"]')
            lines.append('    end')

            # Track agent_session units for user entry edge
            if unit.get("workload_class") == "agent_session":
                agent_session_units.append(sanitized_id)

        # Connect user to agent_session units
        for uid in agent_session_units:
            lines.append(f"    user -->|request| {uid}")

        # Add interconnect nodes/edges. A system can MIX couplings — some units on a queue,
        # others via a gateway (Design records only the dominant `platform.interconnect`, but the
        # per-unit coupling.mode holds the real picture). So draw EACH interconnect that any unit
        # actually uses, independently — not one exclusive branch keyed on platform.interconnect.
        if len(units) > 1:
            has_any_coupling = any("coupling" in u for u in units)
            queue_units = units_on_interconnect(units, {"queue"})
            gw_units = units_on_interconnect(units, {"api", "a2a"})

            # No per-unit coupling data at all → fall back to the single platform.interconnect
            # over all units (legacy behavior for designs that predate per-unit coupling).
            if not has_any_coupling:
                if interconnect == "queue":
                    queue_units = units
                elif interconnect == "gateway":
                    gw_units = units

            if len(queue_units) > 1:
                lines.append('    queue["Queue"]')
                # Producer/consumer direction isn't in the data model, so show each coupled
                # unit's participation with an undirected-style dotted edge (as with gateway).
                for unit in queue_units:
                    lines.append(f"    {sanitize_id(unit['id'])} -.-> queue")
            if len(gw_units) > 1:
                lines.append('    gateway["Gateway"]')
                for unit in gw_units:
                    lines.append(f"    {sanitize_id(unit['id'])} -.-> gateway")
        # single unit, or interconnect none/in_process with no couplings: no edges

    # Handoff indicator — same as the single-unit path, but per unit: any unit on a
    # HANDOFF_RUNTIME (ecs/eks/fargate/batch) has its compute configured by the migration skill.
    handoff_units = units_needing_handoff(units)
    if handoff_units:
        lines.append('    handoff["Compute configured by the migration skill"]')
        for unit in handoff_units:
            lines.append(f"    {sanitize_id(unit['id'])} -.-> handoff")

    return "\n".join(lines)


def render_multi_unit_ascii(design):
    lines = ["Multi-unit Architecture:", ""]
    units = design.get("units", [])
    platform = design.get("platform", {})
    interconnect = platform.get("interconnect", "none")
    temporal_block = design.get("temporal", {})

    # Check if this is a Temporal system
    worker_poll_units = [u for u in units if u.get("workload_class") == "temporal_worker_poll"]
    is_temporal = bool(worker_poll_units or temporal_block)

    if is_temporal:
        # Temporal topology — orchestrator label reflects the chosen Way.
        way = temporal_block.get("way", "unknown")
        if way == "self_hosted":
            lines.append("Temporal Server (self-hosted, orchestrator)")
        elif way == "cloud":
            lines.append("Temporal Cloud (orchestrator)")
        else:
            lines.append("Temporal Server (orchestrator)")
        lines.append("    |")
        lines.append("    v")

        for unit in units:
            uid = unit["id"]
            verdict = unit_runtime(unit)
            model_rec = unit.get("model_recommendation")

            label = RUNTIME_LABELS.get(verdict, verdict)
            if model_rec and model_rec.get("model"):
                label += f" ({model_rec['model']})"

            if unit.get("workload_class") == "temporal_worker_poll":
                lines.append(f"  [ {uid}: {label} ] <-- long-polls task queues")
            else:
                task_queue = unit.get("task_queue", "")
                queue_info = f" (task queue: {task_queue})" if task_queue else ""
                lines.append(f"    --> [ {uid}: {label} ]{queue_info}")
    else:
        # Generic multi-unit topology
        lines.append("User / Client")
        lines.append("    |")
        lines.append("    v")

        for unit in units:
            uid = unit["id"]
            verdict = unit_runtime(unit)
            model_rec = unit.get("model_recommendation")

            label = RUNTIME_LABELS.get(verdict, verdict)
            if model_rec and model_rec.get("model"):
                label += f" ({model_rec['model']})"

            lines.append(f"  [ {uid}: {label} ]")

        # A system can mix couplings — draw EACH interconnect any unit actually uses (from
        # per-unit coupling.mode), not just the single dominant platform.interconnect value.
        # This mirrors the Mermaid path so a queue+gateway mix doesn't lose the queue here.
        has_any_coupling = any("coupling" in u for u in units)
        queue_units = units_on_interconnect(units, {"queue"})
        gw_units = units_on_interconnect(units, {"api", "a2a"})
        if not has_any_coupling:
            if interconnect == "queue":
                queue_units = units
            elif interconnect == "gateway":
                gw_units = units
        if len(queue_units) > 1:
            lines.append("")
            lines.append("Interconnect: Queue — " +
                         ", ".join(u["id"] for u in queue_units))
        if len(gw_units) > 1:
            lines.append("")
            lines.append("Interconnect: Gateway — " +
                         ", ".join(u["id"] for u in gw_units))

    # Handoff indicator (mirrors the Mermaid multi-unit path and the single-unit ASCII note):
    # any unit on a HANDOFF_RUNTIME has its compute configured by the migration skill.
    handoff_units = units_needing_handoff(units)
    if handoff_units:
        lines.append("")
        lines.append("Note: compute configured by the migration skill — " +
                     ", ".join(u["id"] for u in handoff_units))

    return "\n".join(lines)


def build_diagram(result, confirm, design=None):
    # If design has multiple units, render multi-unit topology
    if design is not None:
        units = design.get("units", [])
        if len(units) > 1:
            return {
                "mermaid": render_multi_unit_mermaid(design),
                "ascii": render_multi_unit_ascii(design),
            }
        if len(units) == 1:
            # Single-unit design: render from the design UNIT (which carries the resolved
            # effective_runtime, model_recommendation, deployment_model, agentcore_services),
            # falling back to the legacy `result`/`confirm` for any field the unit omits. This
            # fixes the case where `result` is the wrapped scoring-result.json ({"units": {...}})
            # whose top-level verdict/model are absent (which rendered "runtime None / model
            # unknown"), while preserving the collapse invariant: given consistent single-unit
            # data, this path and the legacy path below produce identical output.
            unit = units[0]
            runtime = unit_runtime(unit)
            if runtime in ("none", "no_viable_runtime", "unknown"):
                runtime = resolve_runtime(result, confirm)
            if runtime == "none":
                msg = "No viable runtime — see blocking constraints"
                return {
                    "mermaid": f'flowchart TD\n    n["{msg}"]',
                    "ascii": f"[ {RUNTIME_LABELS['none']} ]\n{msg}",
                }
            # Fall back to result/confirm ONLY when the unit OMITS the key — an explicit empty
            # list is authoritative (the user declined all AgentCore add-ons) and must be kept,
            # not replaced by scoring defaults like Identity/Observability.
            if "agentcore_services" in unit:
                services = unit["agentcore_services"] or []
            else:
                services = resolve_services(result, confirm)
            services = [s for s in services if s in SERVICE_LABELS]
            model = (unit.get("model_recommendation") or {}).get("model") \
                or result.get("model_recommendation", {}).get("model", "unknown")
            deployment_model = unit.get("deployment_model") or result.get("deployment_model")
            return {
                "mermaid": render_mermaid(runtime, services, model, deployment_model),
                "ascii": render_ascii(runtime, services, model, deployment_model),
            }

    # Legacy single-unit path (no design supplied — e.g. pre-design diagram)
    runtime = resolve_runtime(result, confirm)
    if runtime == "none":
        msg = "No viable runtime — see blocking constraints"
        return {
            "mermaid": f'flowchart TD\n    n["{msg}"]',
            "ascii": f"[ {RUNTIME_LABELS['none']} ]\n{msg}",
        }
    services = resolve_services(result, confirm)
    model = result.get("model_recommendation", {}).get("model", "unknown")
    deployment_model = result.get("deployment_model")
    return {
        "mermaid": render_mermaid(runtime, services, model, deployment_model),
        "ascii": render_ascii(runtime, services, model, deployment_model),
    }


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="agent-advisor diagram composer")
    parser.add_argument("result", type=pathlib.Path)
    parser.add_argument("confirm", type=pathlib.Path)
    parser.add_argument("design", type=pathlib.Path, nargs="?", default=None,
                        help="Optional design.json path for multi-unit topology")
    args = parser.parse_args(argv)
    result = json.loads(args.result.read_text())
    confirm = json.loads(args.confirm.read_text()) if args.confirm.exists() else {}
    design = json.loads(args.design.read_text()) if args.design and args.design.exists() else None
    diagram = build_diagram(result, confirm, design=design)
    out = (
        "```mermaid\n" + diagram["mermaid"] + "\n```\n\n"
        "<details><summary>ASCII (plain-text fallback)</summary>\n\n"
        "```\n" + diagram["ascii"] + "\n```\n\n</details>\n"
    )
    out_path = args.result.parent / "diagram.md"
    out_path.write_text(out)
    runtime = resolve_runtime(result, confirm) if not design else "multi-unit"
    print(f"RESULT=ok RUNTIME={runtime}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
