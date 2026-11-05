# Render migration report decision core

The Generate report fragment MUST render one accessible, self-contained HTML report from the current inventory, preferences, design, estimate, generation ledger, and validation outcome. The report is a customer artifact; source secrets, environment values, personal data, repository URLs, account/workspace/project/environment IDs, and local paths never belong in it.

## Required rendered structure

Use one `<h1>`, `<html lang="en">`, a `<nav class="toc" aria-label="Table of contents">`, and exactly one non-empty `<section>` for each stable ID below. Every TOC link targets one of these IDs, and every ID appears in the TOC.

1. `decision-summary` — recommendation, current Render baseline, both AWS scenarios, and the known-cost-floor caveat.
2. `architecture` — cluster-level rationale, build-once ECR promotion, private ingress, and selected managed services.
3. `exec-targets` — one visible row per `aws-design.json` mapping. The row carries exact `data-source-resource-id` and `data-aws-service` attributes.
4. `exec-costs` — exact anchors for `current_render`, `capacity_preserving`, `right_sized`, and `delta`; each element has `data-cost-key` and renders its dollar value.
5. `migration-data` — PostgreSQL full-load/CDC procedure, Key Value transition, writer quiescence, integrity checks, and source retention.
6. `migration-storage` — EFS pre-copy/delta transfer for `/var/data`, ownership/permissions/locking checks, quiescence, integrity, and rollback.
7. `migration-deployment` — build-once ECR digest promotion, serving-deploy identity, auto-deploy state, immutable rollout, and rollback lineage.
8. `cutover` — prerequisites, certificate readiness, DNS TTL, writer quiescence, traffic shift, and acceptance checks.
9. `rollback` — rollback triggers, writer fencing, DNS/traffic restoration, target cleanup limits, and retained Render source.
10. `verification` — concrete endpoint, database, cache, disk, worker/cron, and Workflow checks.
11. `deferred-surfaces` — exact `deferred_shared_ai_engine` warning and every `conditional_workflow_generation_unsupported` warning. Deferred work is never represented as generated.
12. `appendix-accounting` — discovered/design/generated/consumed/unsupported counts and all source rows. The section carries `data-accounted-count` equal to the design mapping count.
13. `appendix-artifacts` — Terraform, docs, scripts, warnings, and validation report catalog.
14. `appendix-assumptions` — defaults, cost-floor limitations, Workflow test limits, and validation limitations.

The footer says `draft for review` and tells the reader to validate estimates before decisions. Tables use `<caption>` and every `<th>` uses `scope="col"` or `scope="row"`. Images have non-empty `alt`; figures have an `aria-label` and `<figcaption>`. Do not use color as the only status carrier.

## Cross-artifact truth

The report validator compares rendered targets to every `aws-design.json` mapping, cost anchors to `estimation-infra.json`, and accounting to `generation-warnings.json`. The generation ledger classifies every design source exactly once as generated, consumed topology, deferred, or conditionally unsupported. AI is represented only by the exact deferred state; Workflow Terraform is represented only when its semantics are supported and validated.

A failed report is renamed to `migration-report.incomplete.html`. It remains available for diagnosis but MUST NOT satisfy Generate `_produces` or completion. There is no skip-and-complete path.
