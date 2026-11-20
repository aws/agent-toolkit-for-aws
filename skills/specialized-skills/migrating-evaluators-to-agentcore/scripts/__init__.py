"""Deterministic migration tools.

These tools replace LLM judgment for the mechanical parts of a migration:

- ``classify.py``               — metric → deployment path + exact score key
- ``names.py``                  — project/evaluator naming with CLI constraints enforced
- ``generate_handlers.py``      — Lambda handler file generation from mapping.json
- ``adot.py``                   — ADOT documents + score extraction + evaluator ID resolution
- ``generate_client_script.py`` — ``*_agentcore.py`` generation (traces) / scaffold (live agent)
- ``deployer.py``               — preflight_check() + migration.sh generation
- ``package_ragas_lambda.py``   — RAGAS: rewrite pyproject pins, inject stubs, self-test
- ``verify_deps.py``            — verify + auto-fix Lambda app dependencies, pre-deploy
- ``smoke_test_lambda.py``      — quick single-invoke test after deploy

Every tool is standalone (no package install), so it runs from a copied skill
directory: ``python3 scripts/classify.py --help``.
"""
