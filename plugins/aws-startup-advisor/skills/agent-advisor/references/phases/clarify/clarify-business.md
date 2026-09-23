---
_fragment: clarify-business
_of_phase: clarify
_contributes:
  - answers.json
---

# Clarify wording — Business audience

Translate scoring signals into business language. Map answers onto the SAME keys in
clarify.md Step 3 (do not invent new keys/values).

- **session_duration**: "Does your agent answer in a few seconds, work for a few minutes,
  work for hours, or run continuously?" → under_15min / 15min_to_8hr (minutes or hours) /
  over_8hr.
- **traffic_pattern**: "Is usage spiky with quiet gaps, or steady all day?" → bursty / steady / idle.
- **session_state**: "Does a person approve the agent's actions, or does it run on its own?"
  → hitl (approves) / stateful / stateless.
- **isolation**: "Do your different customers' data need to be strictly separated?" →
  required / nice_to_have / not_needed.
- **memory_needs**: "Should the agent remember a user across separate conversations?" →
  cross_session / session_only / none.
- **ops_preference**: "How hands-on do you want to be with infrastructure? just push code /
  some control / full control." → minimal / moderate / full_control.
- **compute_tier**: "Does a task do heavy number-crunching (video, large data, ML), or mostly
  call an AI model and wait?" → heavy_non_gpu / light; ask about GPU only if heavy.
- **instance_type_requirement**: "Has your team been told the agent must run on a specific
  kind of server (a particular machine size, a GPU, or ARM chips)? Most teams answer no."
  → yes / no; default unknown if unsure.
- **idle_resume**: "If a user steps away and comes back, must the work continue exactly where
  it paused?" → process_level / filesystem / none.
- **launch_concurrency**: "At peak, roughly how many new sessions start per second?" → high
  (many) / moderate / low.
- **multi_agent**: "One agent, or several working together?" → no / yes.
- **deployment_preference**: "Would you rather AWS fully manage the agent for you (you just
  describe it — no code to maintain), bring your own agent code, or let me recommend?" →
  harness / framework / either. Ask early. Only affects the AgentCore deployment style, not which
  runtime is chosen. Default `either`.
- **framework / existing_cluster / multi_cloud / platform_fit**: ask in plain terms; default
  to unknown if the user is unsure (the engine handles unknown safely).
- **compliance**: "Any compliance requirements? (HIPAA, SOC 2, etc.)" multi-select.
- **model_priority**: "What matters most for the AI — quality, speed, cost, or balanced?"
- **model_features**: if they need something specific, ask "what's the ONE most important thing
  the AI must do?" in plain terms — e.g. use tools/APIs, read very long documents, deep step-by-
  step reasoning, answer from your documents (RAG), understand images, _generate_ images, handle
  voice/speech, or produce embeddings. This picks a specialized model when needed (see
  `${CLAUDE_PLUGIN_ROOT}/skills/agent-advisor/references/decision-refs/model-selection.md`). If nothing special →
  `none`. **current_model**: migrate only ("what model are you on today?").
- **region**: "Where are your users — one region, a few, or global? Anywhere with data-residency
  rules, like the EU?" Used to check the recommended service is available there, and — for EU or
  GDPR — to flag the data-residency (CRIS) choice. Doesn't change which runtime is recommended.
