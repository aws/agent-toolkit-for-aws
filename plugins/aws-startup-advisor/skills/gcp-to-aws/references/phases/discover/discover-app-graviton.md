# Discover Phase: App Code Graviton (ARM64) Compatibility

GCP-owned infrastructure step. Graviton/compute profiling is not delegated to `bedrock-migration-assessment`; this file owns every `graviton_profile` entry with `source: "app_code"`. It runs for every GCP run in which Step 1b of `discover.md` found source code or dependency manifests, whether or not the run is an `AI_CANDIDATE`, and it runs before the BMA app-code shim. `bedrock-migration-assessment` never emits, modifies, or drops `graviton_profile`.

## Step 0: Input gate

Reuse the Step 1b glob result from `discover.md`. If no source code or dependency manifest files were found, exit this file without emitting anything — `discover-iac.md` will emit coarser profiles from `machine_type` signals, and Clarify will confirm architecture.

## Step 2.7: Graviton (ARM64) Compatibility Scan

Assess each detected compute workload for Graviton (ARM64) compatibility and emit a `graviton_profile` entry per service. **Load** `references/shared/schema-graviton.md` for the detection-signal tables and the `graviton_profile` schema; **load** `references/shared/graviton.md` for tier definitions.

For each compute workload (web service, worker, function, container) detected from source code and manifests:

1. Determine the **language runtime** from the dependency manifest. Python, Node.js, Go, PHP, Ruby, and pure-JVM Java (Corretto/OpenJDK, no JNI) → `tier: "ready"`.
2. Scan for **risk signals** (downgrade to `conditional`): native C extensions (`node-gyp`, niche Python C packages), native gem extensions, JNI (`System.loadLibrary`, `JNI_OnLoad`), recompile-required languages (Rust/C/C++ without x86 assembly), `platform: linux/amd64` pinned in `docker-compose.yml` or build config.
3. Scan for **blockers** (`tier: "incompatible"`): GPU/CUDA usage (`import cuda`, `torch.cuda`, `nvidia`) → caveat `"route to G5/G6"`; Windows/.NET Framework targets.
4. If a `Dockerfile` is present, record whether its `FROM` base image has a multi-arch variant as a `signal`.

Write a `graviton_profile` array at the **top level** of `gcp-resource-inventory.json` (or, on hybrid runs where that file does not exist yet, at the top level of `ai-workload-profile.json`, alongside `models[]`/`workloads[]`). Top level is the one canonical location; the fixtures, `scripts/artifact-contracts.json` and the workshop sheet all read `graviton_profile[]` from the root of the file. Each entry uses the schema in `schema-graviton.md` with `source: "app_code"`. `graviton_profile` is an empty array when no compute workloads are detected.

`discover-iac.md` Step 7 must not overwrite an `app_code` profile for the same service — app-code signals win and IaC profiles fill gaps only. `clarify-compute.md` uses the presence of an `app_code` profile to decide whether architecture is confirmed by code or must be asked.

`scripts/gcp-route-gate.py` reads the top-level `graviton_profile` from `gcp-resource-inventory.json` or, on hybrid runs, `ai-workload-profile.json`; it also accepts `metadata.graviton_profile` in either file so a run that nested the array still passes (`GATE_PASS ... location=metadata`). Route applicability is decided by the route output gate in `discover.md` Step 2 (run through that script), not here. On the AI-only route (`ai_only`, no GCP inventory) that gate is `not_applicable`, so this file requires and writes no `graviton_profile`. On every other route a **missing** `graviton_profile` does not fail the gate: billing-only Discover writes no inventory, and this scan may not have emitted yet, so the gate reports `GATE_PASS ... reason=not_yet_known` and `clarify-compute.md` Q11b asks for the architecture. The gate fails with `ROUTE_GATE_FAIL` (STOP) only on malformed input: a file that is not a JSON object (`reason=unreadable`) or a `graviton_profile` that is not an array (`reason=malformed`).
