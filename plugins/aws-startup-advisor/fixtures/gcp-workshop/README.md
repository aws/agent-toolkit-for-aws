# GCP what-if workshop fixtures

Infra-route pilot for `gcp-to-aws` (`references/phases/workshop/`).

| Path                         | Role                                                                                      |
| ---------------------------- | ----------------------------------------------------------------------------------------- |
| `seed/`                      | Post-Estimate baseline (`cpu_architecture=x86`, real Q11b prompt, mixed graviton_profile) |
| `after-graviton-reprice/`    | After Apply with `graviton` + caveat (worker stays x86)                                   |
| `check_expected_workshop.py` | Stdlib asserter                                                                           |

```bash
python3 check_expected_workshop.py after-graviton-reprice
```

## House replay bar

Before merge: from `seed/`, enter workshop → set CPU architecture to `graviton`
(sheet must show the incompatible-worker caveat) → Apply & reprice → Compare →
asserter PASS. The committed `after-graviton-reprice/` was produced by that
mechanical path (inventory bytes frozen; worker remains `X86_64`;
`workshop.graviton_note` set). Prefer also a fresh-agent transcript on the PR.
