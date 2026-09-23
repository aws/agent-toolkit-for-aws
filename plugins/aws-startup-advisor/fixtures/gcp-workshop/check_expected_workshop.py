#!/usr/bin/env python3
"""Assert a GCP what-if workshop run against expected-workshop.json."""
from __future__ import annotations
import json, sys
from pathlib import Path
FAILS=[]
def check(c,m):
    if not c: FAILS.append(m)
def main():
    if len(sys.argv) not in (2,3):
        print(__doc__); return 2
    run=Path(sys.argv[1]); fx=Path(__file__).resolve().parent
    seed=Path(sys.argv[2]) if len(sys.argv)==3 else fx/'seed'
    exp=json.loads((fx/'expected-workshop.json').read_text())
    inv_r, inv_s = run/'gcp-resource-inventory.json', seed/'gcp-resource-inventory.json'
    check(inv_r.exists(), 'missing inventory')
    if inv_r.exists() and inv_s.exists() and exp.get('inventory_must_match_seed_bytes'):
        check(inv_r.read_bytes()==inv_s.read_bytes(), 'inventory bytes changed')
    idxp=run/'scenarios'/'index.json'; check(idxp.exists(), 'missing index')
    if not idxp.exists():
        print('FAIL'); [print(' -',f) for f in FAILS]; return 1
    idx=json.loads(idxp.read_text()); sc=idx.get('scenarios') or []
    check(len(sc)>=exp['min_scenarios'], 'too few scenarios')
    check(idx.get('active_scenario_id')==exp['active_scenario_id'], 'active id')
    prefs=json.loads((run/'preferences.json').read_text())
    ca=((prefs.get('design_constraints') or {}).get('cpu_architecture') or {})
    check(ca.get('value')==exp['active_cpu_architecture'], f"arch={ca.get('value')}")
    if exp.get('q11b_prompt_must_contain'):
        check(exp['q11b_prompt_must_contain'] in (ca.get('prompt') or ''), 'Q11b prompt missing real clarify text')
    if exp.get('must_have_graviton_note'):
        note=(prefs.get('workshop') or {}).get('graviton_note') or ''
        check(bool(note), 'missing workshop.graviton_note')
        check('incompatible' in note.lower(), 'graviton_note should mention incompatible')
    if exp.get('must_keep_incompatible_worker_x86'):
        design=json.loads((run/'aws-design.json').read_text())
        worker=next((s for s in design.get('services',[]) if s.get('source_resource_id')=='run:worker'), None)
        check(worker is not None, 'missing worker service')
        if worker:
            check(worker.get('aws_config',{}).get('cpu_architecture')=='X86_64', 'incompatible worker must stay X86_64')
    est=json.loads((run/'estimation-infra.json').read_text())
    base_m=run/'scenarios'/f"{exp['baseline_scenario_id']}.json"
    if base_m.exists() and exp.get('balanced_must_differ_from_baseline'):
        b=json.loads(base_m.read_text())['estimation_summary']['aws_monthly_balanced']
        a=est['projected_costs']['aws_monthly_balanced']
        check(a!=b, f'balanced unchanged {a}')
    ph=run/'.phase-status.json'
    if ph.exists():
        p=json.loads(ph.read_text())
        if exp.get('current_phase_must_be'):
            check(p.get('current_phase')==exp['current_phase_must_be'], 'current_phase')
        if exp.get('workshop_phase_must_be'):
            check(p.get('phases',{}).get('workshop')==exp['workshop_phase_must_be'], 'workshop phase')
        if exp.get('generate_must_not_be_completed'):
            check(p.get('phases',{}).get('generate')!='completed', 'generate completed')
    if FAILS:
        print(f'FAIL ({len(FAILS)}):'); [print('  -',f) for f in FAILS]; return 1
    print('PASS — expected-workshop.json assertions hold'); return 0
if __name__=='__main__':
    sys.exit(main())
