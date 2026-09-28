# Heroku horizontal non-web scaling fixtures

Canned Design artifacts for the **Horizontal Non-Web Capacity Guard**
(`references/phases/design/design-mapping.md`): a persistent non-web formation with
`quantity > 1` cannot keep its horizontal capacity on an Elastic Beanstalk
SingleInstance environment, so Design routes that formation to Fargate instead.

The guard makes the Fargate table's tier coverage load-bearing for the _default_
compute path. Before this fixture existed, no fixture had a non-web formation with
`quantity > 1` at all, and the only `basic` dyno was a `web` process at `quantity: 1`
— so the guard, and the Fargate lookup it depends on, were completely uncovered.
A `basic` or `eco` worker at `quantity: 2` was routed to a Fargate table that had no
`basic`/`eco` row, the lookup missed, and `_on_not_found` dropped the formation from
both the design and the cost estimate with only a warning.

| Path                               | Role                                                                                      |
| ---------------------------------- | ----------------------------------------------------------------------------------------- |
| `seed/`                            | Post-Clarify seed (`design: pending`): `basic` web ×1, `basic` worker ×2, `eco` mailer ×2 |
| `after-design/`                    | Golden Design output: web on EB `t3.micro`, both non-web formations on Fargate 256/512    |
| `expected-nonweb-scaling.json`     | Assertions for the asserter, including the Fargate CPU/memory matrix                      |
| `check_expected_nonweb_scaling.py` | Stdlib checker (run it directly — see "Assert a run" below)                                |

## Assert a run

```bash
python3 check_expected_nonweb_scaling.py after-design
# or against a live run dir that completed Design from seed/:
python3 check_expected_nonweb_scaling.py /path/to/.migration/MMDD-HHMM
```

The asserter checks three things:

1. **Nothing is silently dropped** — every non-`release` formation in the inventory
   has at least one service in the design, and no `Unsupported dyno type` warning
   is present.
2. **The guard fired** — every non-web formation with `quantity > 1` maps to Fargate
   (256 CPU units / 512 MiB for `eco` and `basic`), with the guard warning recorded.
3. **The sizing tables still agree** (run-dir-independent) — `eco` and `basic` exist
   in all three dyno tables, the Fargate and EKS tier sets are identical, the EB tier
   set covers the Fargate one, and every Fargate row is a legal CPU/memory pairing per
   the matrix in `expected-nonweb-scaling.json`. Three pre-existing `*-xl` rows
   (8192 CPU with 65536 MiB, above the 60 GB ceiling for 8 vCPU) are listed in
   `fargate_matrix_baseline.exempt_rows` and tracked separately.

## Fresh-agent replay bar (house standard)

Copy `seed/*` into a scratch `.migration/<id>/` (including `.phase-status.json` with
`design: pending`), invoke the heroku-to-aws skill, let Design run, then
`python3 check_expected_nonweb_scaling.py <scratch_dir>` — must **PASS**. The
committed `after-design/` is the reference snapshot for that path. All app names are
synthetic.
