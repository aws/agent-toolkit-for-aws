# Heroku what-if workshop fixtures

Canned Estimate → workshop reprice artifacts for the `heroku-to-aws` what-if
workshop checkpoint (`references/phases/workshop/`, `_kind: checkpoint`).
Discovery inventory is frozen; Design + Estimate refresh under `scenarios/`.

| Path                         | Role                                                                       |
| ---------------------------- | -------------------------------------------------------------------------- |
| `seed/`                      | Post-Estimate baseline (x86 EB `t3.small`, single-AZ) before workshop      |
| `after-arm64-reprice/`       | After Apply & reprice with `workshop.cpu_architecture=arm64` (`t4g.small`) |
| `expected-workshop.json`     | Assertions for the asserter                                                |
| `check_expected_workshop.py` | Stdlib checker                                                             |

## Assert a run

```bash
python3 check_expected_workshop.py after-arm64-reprice
# or against a live .migration/<id>/ that followed the arm64 sheet path:
python3 check_expected_workshop.py /path/to/.migration/MMDD-HHMM seed
```

## Fresh-agent replay bar (house standard)

Before opening a PR that changes workshop behavior, a **fresh agent** must produce
an after-state from `seed/` by following the phase specs only (no fixture peek):

1. Copy `seed/*` into a scratch `.migration/<id>/` (include `.phase-status.json`
   with `workshop: pending`).
2. Agent plays the SA: enter workshop → set CPU architecture `arm64` → Apply &
   reprice → Compare → (optional) Exit without Generate.
3. Run `python3 check_expected_workshop.py <scratch_dir> seed` — must **PASS**.

The committed `after-arm64-reprice/` is the reference snapshot for that path.
Record in the PR that the replay was run (attach the agent transcript). Manual
demo alone is not enough for the house bar.

## SA demo script (manual)

1. Copy `seed/*` into a scratch `.migration/0719-demo/` (include `.phase-status.json`).
2. Invoke heroku-to-aws Estimate handoff / say **Enter what-if workshop**.
3. Confirm baseline capture creates `scenarios/scenario-001*`.
4. On the sheet, set **CPU architecture → arm64**, leave other knobs; **Apply & reprice**.
5. Confirm Design emits EB `t4g.small` + `cpu_architecture: arm64`, Estimate
   balanced total changes, `scenario-002` appears, inventory bytes unchanged.
6. **Compare scenarios** — baseline vs scenario-002 (all three cost tiers).
7. Optional second apply: set `data.database_ha` / `global.availability` to
   `multi-az`, Apply & reprice → `scenario-003`.
8. **Exit to Generate** — `workshop-assemble` marks workshop completed and sets
   `current_phase: generate`; working tree matches the active scenario.

Partner one-liner: _SAs can run a what-if workshop after Estimate: change region,
HA, compute target, or Graviton preference and compare up to 5 priced scenarios
without re-discovery. (Rates are cache-based; regional deltas noted qualitatively.)_
