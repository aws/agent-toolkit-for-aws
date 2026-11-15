---
_phase: clarify
_title: "Clarify Render Migration Requirements"
_requires_phase: discover
_input:
  - render-resource-inventory.json
  - render-resource-clusters.json
  - { file: ai-workload-profile.json, _when: "AI discovery produced the profile" }
_knowledge:
  - { file: references/shared/schema-preferences.md }
  - { file: references/shared/schema-render-preferences.json }
_fragments:
  - _id: global
    _trigger: { _always: true }
    _file: phases/clarify/clarify-global.md
  - _id: compute
    _trigger: { _when: "the inventory contains a web, private, worker, cron, or static resource" }
    _file: phases/clarify/clarify-compute.md
  - _id: data
    _trigger: { _when: "the inventory contains PostgreSQL or Key Value" }
    _file: phases/clarify/clarify-data.md
  - _id: storage
    _trigger: { _when: "the inventory contains a persistent disk" }
    _file: phases/clarify/clarify-storage.md
  - _id: workflow
    _trigger: { _when: "the inventory contains a Workflow, Workflow task, run, or attempt" }
    _file: phases/clarify/clarify-workflow.md
  - _id: network
    _trigger: { _when: "the inventory contains public domains, private services, routes, IP rules, or cross-service calls" }
    _file: phases/clarify/clarify-network.md
_assemble:
  _file: phases/clarify/clarify-assemble.md
_produces:
  - preferences.json
_advances_to: design
_interactive: true
_re_entry_guard:
  _stale_if_completed: design
  _stale_artifact: aws-design.json
  _on_reentry: stop_unless_confirmed
  _on_confirm: reset_downstream_to_pending
_preconditions:
  - _check_phase_completed: discover
    _on_failure: _halt_and_inform
  - _check_single_active_phase: true
    _on_failure: _halt_and_inform
  - _check_file_exists: [render-resource-inventory.json, render-resource-clusters.json]
    _on_failure: _unrecoverable
  - _validate_json: [render-resource-inventory.json, render-resource-clusters.json]
    _on_failure: _unrecoverable
_postconditions:
  - _check_file_exists: preferences.json
    _on_failure: _halt_and_inform
  - _validate_json: preferences.json
    _on_failure: _halt_and_inform
  - _assert: "preferences.json validates against schema-render-preferences.json and its inventory fingerprint matches the raw inventory bytes"
    _on_failure: _halt_and_inform
  - _assert: "every applicable selector requirement is answered, explicitly defaulted, or not_applicable; no unresolved disposition remains"
    _on_failure: _halt_and_inform
  - _assert: "questions are unique and byte-sorted by resource_id then question_id, and every question names the decision it can change"
    _on_failure: _halt_and_inform
_forbids_files:
  - aws-design.json
  - estimation-infra.json
  - "terraform/**"
---

# Phase 2: Clarify migration requirements

Clarify is mandatory. Fragments derive candidate questions from the frozen inventory; they do not prompt independently. The assembler asks only unresolved facts that can change an AWS service, availability or sizing, migration method, or cutover. It writes one deterministic assumption sheet.

A discovered value wins over a default. A user answer wins over both. An explicit default is permitted only when the relevant design reference names it and records its consequence. A decisive omission remains `unresolved`, blocks the postcondition, and returns to Clarify; it never reaches Design as an option list.

When an AI profile exists, ask only provider-neutral acceptance and runtime questions. Infrastructure Clarify continues, but no answer may activate AI execution while the profile state is `deferred_shared_ai_engine`.
