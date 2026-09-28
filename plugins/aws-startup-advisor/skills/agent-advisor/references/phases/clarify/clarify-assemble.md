---
_assemble: assemble-clarify
_of_phase: clarify
_reads:
  - technical wording fragment (clarify-technical.md contribution, when audience is technical)
  - business wording fragment (clarify-business.md contribution, when audience is business)
  - interpreted core-question answers (collected inline in clarify.md)
_produces:
  - answers.json
  - current-run-verifications.json
  - scoring-result.json
---

# Clarify — Assemble answers.json and run scoring

> **Assembler unit.** The Clarify phase presents the core scoring questions (in
> the audience-specific wording loaded from clarify-technical.md /
> clarify-business.md), interprets the answers, and writes `answers.json`
> inline within `clarify.md` (Step 4). Before scoring, it creates the sibling
> `current-run-verifications.json` artifact and records only evidence actually
> observed in this run; then it runs the deterministic scoring engine, which
> writes `scoring-result.json` (Step 5). This unit is the single creator of all
> three phase artifacts. See `clarify.md` § Step 4–5 for legal answer keys,
> the verification-evidence contract, and the scoring command.

The assembled workload answers preserve `target_maturity` and `readiness` but
never contain current-run verification evidence. The scoring artifact preserves
its `recommendation_status` and `deferred_verification_requirements`; deferred
verification is not silently converted into an elimination or final recommendation.
