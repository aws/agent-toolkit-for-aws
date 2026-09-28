---
_fragment: clarify-technical
_of_phase: clarify
_contributes:
  - answers.json
---

# Clarify wording — Technical audience

Use direct technical terms. Map each answer onto the keys in clarify.md Step 3.

- **session_duration**: "How long do agent tasks typically run? seconds / minutes / hours
  (≤8h) / >8h or continuous." (>8h no longer rules AgentCore out — it routes to the
  Instances compute type, sessions up to 14 days. Truly always-on services are still
  steered elsewhere by `traffic_pattern`.)
- **instance_type_requirement**: "Do you have a requirement to choose a particular EC2
  instance type for your agent — a specific family/size, a GPU model, or ARM? yes / no."
- **traffic_pattern**: "Traffic shape? bursty with idle / steady continuous / mostly idle."
- **session_state**: "Execution model? stateless / stateful / human-in-the-loop approvals."
- **isolation**: "Multi-tenant isolation required between users? required / nice-to-have / not needed."
- **memory_needs**: "Memory across conversations? cross-session / session-only / none."
- **ops_preference**: "Ops you want to own? minimal (push code, get URL) / serverless with OS
  control / containers / Kubernetes full control."
- **compute_tier**: "Per-session compute? light (≤2 vCPU/8 GB) / heavy non-GPU (>2 vCPU) / GPU."
- **idle_resume**: "On idle-then-resume, do running processes need to continue exactly
  (process_level), is filesystem persistence enough (filesystem), or not needed (none)?"
- **launch_concurrency**: "Peak new-session launch rate? high (>5/sec) / moderate / low."
- **multi_agent / framework / existing_cluster / multi_cloud / platform_fit**: ask directly.
- **deployment_preference**: "Do you want a no-code managed agent runtime (AgentCore Harness),
  bring your own framework code (Strands/LangGraph/CrewAI/custom), or either?" Ask early. Only
  affects the AgentCore deployment model, not the runtime score. Default `either`.
- **compliance**: multi-select.
- **model_priority**: ask directly (quality/speed/cost/balanced/specialized).
- **model_features**: if priority is specialized (or a specific need is hinted), ask for the ONE
  most critical feature — tool use / long context (>300K) / extended thinking / RAG / multimodal
  (vision) / image generation / speech / embeddings. Drives a hard model override
  (see `${CLAUDE_PLUGIN_ROOT}/skills/agent-advisor/references/decision-refs/model-selection.md`). Else `none`.
- **current_model**: migrate only.
- **region**: "Where are your users / where must this run — single region, multi-region, or
  global? Any specific region (e.g. EU)?" Gates runtime availability (AgentCore/Harness aren't
  everywhere) and, for EU/GDPR, the geo-CRIS vs global-CRIS data-residency choice. Not scored.
