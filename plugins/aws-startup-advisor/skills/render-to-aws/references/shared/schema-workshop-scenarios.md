# Render workshop scenario contract

`scenarios/index.json` contains schema version `1.0`, a raw-inventory `inventory_fingerprint`, `baseline_scenario_id`, `active_scenario_id`, `next_ordinal`, and at most five scenario manifests. Scenario IDs are monotonic `scenario-NNN`; deleted IDs are never reused.

Each manifest records label, created-at timestamp, the same inventory fingerprint, byte digests for `preferences.json`, `aws-design.json`, and `estimation-infra.json`, only preference paths differing from baseline, selected-target changes, and an estimation summary. The summary contains capacity-preserving and right-sized known-cost monthly values, both floor flags and unpriced counts, delta, complexity tier, pricing source, nullable region note, nullable recommendation outcome, and `calculator_url: null`.

The baseline cannot be evicted without explicit reset consent. Before any read, compare, activation, or refresh, verify every digest and reject partial/stale scenarios. Working artifacts must byte-match the active manifest. The exact raw inventory fingerprint is checked before every refresh and on exit.
