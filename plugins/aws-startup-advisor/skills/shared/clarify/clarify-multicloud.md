# Clarify — Multi-Cloud Portability (canonical)

> Canonical multi-cloud-portability question for Clarify's Global/Strategic
> category, vendored into each skill that runs a full-migration Clarify phase
> (`references/vendored/clarify/clarify-multicloud.md`) and kept
> byte-identical by `shared:sync`. Whether a customer needs to keep running
> workloads across multiple cloud providers does not depend on which cloud
> they are migrating FROM, so the question and its early-exit consequence are
> identical everywhere.

## Why this file exists

`gcp-to-aws` has this as an early-exit strategic question (its Q5) that
immediately forces EKS and skips the Kubernetes-sentiment question entirely
when the answer is yes. `azure-to-aws` had no standalone equivalent — its
compute-target question (Q-C1) offers EKS as one of three options, described
only as "only if your team already runs Kubernetes," with no dedicated
portability gate and no early-exit behavior. A customer with a genuine
multi-cloud requirement on Azure gets asked a plain compute-preference
question instead of having their hard constraint recognized up front.

## The question

> Multi-cloud portability is an immediate decision point — if required, Kubernetes (EKS) is
> the only portable abstraction, and we can skip several compute questions.
>
> 1. Yes, multi-cloud required
> 2. No, AWS-only is acceptable
> 3. I don't know

| Answer                    | Recommendation Impact                                                                                                                                                                                                                                                                      |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Yes, multi-cloud required | **Immediate EKS recommendation** — Kubernetes is the only portable abstraction layer. Skip the Kubernetes-sentiment / compute-target question. Container-orchestration-eligible PaaS compute (Cloud Run, App Engine, App Service) routes to EKS too, overriding its normal default target. |
| No, AWS-only acceptable   | Full compute decision tree continues — EKS vs the simpler managed-container option is evaluated based on team sentiment / detected signals                                                                                                                                                 |

### Interpret

```
1 -> compute: "eks" — Immediate EKS recommendation. EARLY EXIT: skip the compute-target / K8s-sentiment question.
2 -> (no constraint written — full compute decision tree continues)
3 -> same as default (2) — assume AWS-only
```

**Default:** 2 — no constraint, evaluate the full compute decision tree.

## What a consuming skill supplies

1. **Which downstream questions this early-exit skips.** GCP's early exit
   skips its Q8 (Kubernetes sentiment) and Q7b (App Engine compute-operational-
   model), routing App Engine to EKS instead of its normal Elastic-Beanstalk
   default. Azure's equivalent early exit skips its Q-C1 (compute target) and
   routes any App-Service-Plan compute that would otherwise default to
   Elastic Beanstalk to EKS instead.
2. **Firing condition.** Always fires when compute resources are present
   (the question is meaningless with no compute to place); a skill whose
   estate has zero compute resources may treat it as N/A.
