---
_fragment: collect
_of_phase: feedback
_contributes:
  - trace.json (anonymized migration trace)
  - feedback.json (survey state, trace_included flag)
---

# Feedback — Collect

> **Fragment unit.** See `feedback.md` for how it is composed into the sidebar.

Asks the five optional questions and builds the anonymized trace.

**The anonymization rule is a hard boundary, not a best effort.** `trace.json` carries
phase timings, counts, size bands, and which routes fired. It never carries resource
names, ARM resource IDs, subscription or tenant IDs, file paths, or exact dollar
figures. Azure raises the stakes here relative to the sibling skills, because an ARM
resource ID embeds the subscription ID and the resource group name in a single string
— a trace that copies an `azure_id` verbatim leaks both.

## Status — skeleton (build step 1)

Wiring only; the question set and the trace builder land alongside the fixtures work.
