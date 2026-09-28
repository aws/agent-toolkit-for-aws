# MLOps — Startup Decision Guide

## The #1 Mistake: Over-Engineering ML Infrastructure

Most startups don't need MLOps platforms until they have a model in production serving real users. The sequence matters:

```
WRONG: Build SageMaker Pipeline → Train model → Find product-market fit
RIGHT: Notebook experiment → Prove value to users → Productionize with minimal infra → Add MLOps as scale demands
```

## Platform Selection by Stage

| Stage     | Monthly ML spend | Recommendation                                                                 | What you're skipping (intentionally)        |
| --------- | ---------------- | ------------------------------------------------------------------------------ | ------------------------------------------- |
| Pre-seed  | $0-200           | SageMaker notebooks + training jobs. No pipelines, no registry, no monitoring. | Everything except train → deploy            |
| Seed      | $200-2K          | Add Model Registry + basic monitoring. Still no pipelines.                     | Automated retraining, CI/CD for models      |
| Series A  | $2K-20K          | SageMaker Pipelines + MLflow tracking. Automate retraining.                    | Multi-environment promotion, shadow testing |
| Series B+ | $20K+            | Full MLOps: pipelines, registry, monitoring, shadow testing, multi-account     | Nothing — you need it all now               |

## Cost Traps Specific to Startups

### The Real-Time Endpoint Trap

**A single ml.m5.large real-time endpoint costs ~$100/month running 24/7, even with zero traffic.**

| Daily inference requests | Best deployment option                                       | Monthly cost |
| ------------------------ | ------------------------------------------------------------ | ------------ |
| < 100                    | Lambda with model loaded from S3                             | $1-5         |
| 100-10,000               | SageMaker Serverless Inference                               | $5-50        |
| 10K-100K                 | Real-time endpoint with aggressive auto-scaling (scale to 1) | $100-500     |
| 100K+                    | Real-time endpoint, right-sized with Inference Recommender   | $500+        |

**When to graduate from Serverless to Real-time:**

- p99 latency requirement < 500ms (Serverless cold starts add 1-5s)
- Model size > 6GB (Serverless max memory: 6GB)
- Sustained traffic > 10 req/sec (Serverless concurrency limit: 200)

### Spot Training: Free Money You're Leaving on the Table

**60-90% savings with one flag.** Set `use_spot_instances=True` on every training job. SageMaker handles interruptions automatically with checkpointing. The only exception is a truly time-critical training run (which you almost certainly don't have at seed stage).

### Trainium/Inferentia: The 50% Savings Most Startups Ignore

If your model is PyTorch or TensorFlow (vast majority of startups): check Neuron compatibility first. ml.trn1 for training and ml.inf2 for inference deliver 50%+ savings. Most startups default to GPU instances without checking because the docs seem complex — but the actual code change is minimal (Neuron SDK compiler handles it).

## Counterintuitive Advice

### Don't Use SageMaker Pipelines Until You Retrain Monthly

If you retrain quarterly or less, a manual notebook-driven workflow with Model Registry is fine. Pipelines add:

- Maintenance overhead (pipeline definitions are code you maintain)
- Debugging complexity (pipeline failures are harder to diagnose than notebook failures)
- Cost (pipeline execution has its own charges)

**Trigger to add pipelines**: You're retraining more than once per month AND manual retraining takes > 2 hours of engineer time.

### Skip Model Monitoring Until You Have Baseline Drift Data

Model Monitor requires a baseline created from training data. If you don't have 2+ weeks of production inference data to compare against, monitoring will generate noise (false positives) and waste your time.

**Trigger to add monitoring**: Model has been in production for 30+ days AND you have a hypothesis about what drift looks like for your data.

### MLflow vs SageMaker Experiments: Pick One, Don't Both

Startups that use both create confusion about "which is the source of truth." Decision:

- **New to ML, all-in on AWS**: SageMaker Experiments (tighter integration, less setup)
- **Existing MLflow muscle memory OR multi-cloud plans**: Managed MLflow on SageMaker
- **Never both.** The sync between them is imperfect and creates confusion.

## Credits-Specific Guidance

- SageMaker training jobs, endpoints, and notebooks are all covered by AWS Activate credits
- **Don't buy SageMaker Savings Plans with credits.** You don't have enough usage history to commit. Savings Plans lock you into $/hour commitments that outlast your credits.
- Spot Training stacks with credits — you burn credits at the Spot rate (60-90% less), making credits last 2-3x longer for training workloads
- **Bedrock fine-tuning is credit-eligible** — if you're choosing between self-managed SageMaker training and Bedrock fine-tuning for a foundation model, Bedrock fine-tuning is simpler AND uses credits

## When to Skip SageMaker Entirely

| Scenario                                           | Better alternative                                      | Why                                                          |
| -------------------------------------------------- | ------------------------------------------------------- | ------------------------------------------------------------ |
| Only using pre-trained models (no custom training) | Bedrock for LLMs, Rekognition/Comprehend for vision/NLP | Fully managed, no infrastructure, pay-per-request            |
| < 50 inferences/day, model < 500MB                 | Lambda + S3 model loading                               | Truly scales to zero, simplest possible deployment           |
| Team is Kubernetes-native, already running EKS     | KServe on EKS                                           | Leverage existing expertise, avoid two orchestration systems |
| Simple tabular ML (classification, regression)     | SageMaker Autopilot / Canvas                            | No-code/low-code, handles the entire ML lifecycle            |

## Anti-Patterns (Startup-Specific)

- **Building a "platform" before shipping a model.** If your first month is spent on pipeline infrastructure and nobody has deployed a model to production, priorities are wrong. Ship first, platformize second.
- **Real-time endpoints for batch scoring.** A startup doing nightly customer churn predictions on 10K users doesn't need an always-on endpoint. Batch Transform runs for 5 minutes and costs $0.50.
- **On-Demand training "because credits cover it."** Credits are finite. Spot Training at 70% savings makes your credits last 3x longer. Always use Spot.
- **Model Registry from day one with 1 model.** Registry adds value at 3+ model versions in production. With 1 model and no A/B testing, it's ceremony with no benefit.
- **Multi-account MLOps (dev/staging/prod) at seed stage.** You have one engineer doing ML. One account is fine. Add account separation when you have compliance requirements or 3+ ML engineers.
