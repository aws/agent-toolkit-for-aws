# Evaluation Type Guide

Help the user decide which evaluation type to use based on their goals and constraints.

## Evaluation types at a glance

| Type          | What it does                                                                                                         | Eval dataset? | Cost   | Supported models |
| ------------- | -------------------------------------------------------------------------------------------------------------------- | ------------- | ------ | ---------------- |
| LLM-as-Judge  | An LLM scores your model's responses on subjective qualities like helpfulness, correctness, coherence, and safety.   | Yes           | Higher | OSS only         |
| Custom Scorer | Your own scoring logic (or a built-in scorer) evaluates outputs programmatically — exact/near match, pattern checks. | Yes           | Lower  | All              |

**When to use which — in short:**

- To assess subjective qualities like tone, helpfulness, coherence, or faithfulness → **LLM-as-Judge**
- When a programmatic approach can give a meaningful signal about output quality → **Custom Scorer**

## Decision flow

Work through the steps below in order. For each, use what you already know from conversation history, plan.md, workflow_state.json, or other files you've read. Only ask the user if you genuinely don't know.

### Step 1: Check for evaluation dataset

For this step, you need to know: **whether the user has an evaluation dataset.**

If you don't know from previous context, ask:

> "Do you have an eval dataset?"

⏸ Wait for user.

If the user does not have one:

> "All supported evaluation types require an evaluation dataset. Unfortunately, this skill can't help with model evaluation without one."

Stop here. Do not offer to help create or find a dataset, since our references do not support this.

If the user has an evaluation dataset, continue.

### Step 2: Check model compatibility

For this step, you need to know: **what type of model is being evaluated** (open source or Nova).

If you don't already know from conversation context, try to determine it:

1. If you have the **training job name or ARN**, run `aws sagemaker list-tags --resource-arn <training-job-arn>` and look for the `sagemaker-studio:jumpstart-model-id` tag.
   - Contains "nova" (e.g., nova-micro, nova-lite, nova-pro) → **Nova**
   - Anything else (Llama, Mistral, Qwen, GPT-OSS, DeepSeek, etc.) → **OSS**
2. If you have a **Model Package ARN**, run `aws sagemaker describe-model-package --model-package-name <arn>` and check the model description or source tags for the same model ID.
3. If neither is available, ask the user:

   > "What model are you evaluating — is it a Nova model or an open-source model (like Llama, Mistral, Qwen, etc.)?"

If the model is Nova, LLM-as-Judge is not supported. Tell the user:

> "Unfortunately, LLM-as-Judge isn't available for Nova models. Can we use Custom Scorer instead?"

If Nova -> Skip to Step 4 (Recommend); the choice is already determined.

Else -> Continue to Step 3 with the remaining options.

### Step 3: Gather information and assess signal strength

This step has four substeps. Substeps **3a** and **3b** are **questions you ask the user**; substeps **3c** and **3d** are **silent reasoning you do on your own**. Do each substep on its own — never collapse them, and never skip an ASK substep because the answer "seems obvious." You may only skip an ASK substep if you already have a clear, explicit answer from earlier in the conversation.

#### Step 3a: Understand the task and data — [ASK THE USER]

You need to understand: **what the model does, what the evaluation data looks like, and — critically — what the model's outputs and the reference answers look like** (e.g., a single exact value, a short label, or free-form paragraph-length text).

If you don't already have a clear picture from conversation context, ask:

> "Can you tell me about the task you're focused on? What does your model do, what does your evaluation dataset look like, and what form do the answers take — exact values, short labels, or longer free-form text?"

The answer-format detail matters: it drives the signal-strength assessment in Step 3c and the caveats in Step 4. If the user's answer is vague about output/answer format, ask a follow-up before moving on.

⏸ Wait for user.

#### Step 3b: Check cost sensitivity — [ASK THE USER]

LLM-as-Judge invokes a model to score each sample, which adds cost. Custom Scorer runs your own code, which is cheaper.

**You MUST ask this question unless the user has already given an explicit cost priority earlier in the conversation.** Do not infer or assume cost sensitivity from the task, the budget, or anything else — get it directly from the user:

> "On a scale of 1-5, how important is it to you to keep evaluation costs low, even if it means less nuanced results? 5 means prioritize budget above all else."

⏸ Wait for user.

#### Step 3c: Assess Custom Scorer signal strength — [THINK — do not message the user]

Based on the task and data (especially the answer format from Step 3a), decide **how strong a signal a custom (programmatic) scorer could give about task success.** Rate it **strong**, **medium**, or **weak**:

- **Strong**: A programmatic check can reliably tell you whether the output is correct. Examples include math problems with numerical answers, classification tasks with labels, or extraction tasks with exact ground truths.
- **Medium**: The task has reference answers, and programmatic comparison gives a useful but imperfect signal. Examples include summarization or Q&A where the answers are free-form / paragraph-length, so text comparison against references captures something meaningful but misses semantically-equivalent phrasings, or format compliance checks where you can verify structure even if you can't verify content quality.
- **Weak**: What matters about the output is hard to capture in code. There may be no reliable reference answer to compare against, or the reference doesn't capture what the user actually cares about.

Think broadly — even tasks that seem subjective may have a programmatic angle. Note your rating; you'll use it in Step 4, and if it is **medium or weak** you must surface that limitation as a caveat.

#### Step 3d: Assess LLM-as-Judge signal strength — [THINK — do not message the user]

Based on the task and data, decide **how strong a signal an LLM judge could give about task success.** Rate it **strong**, **medium**, or **weak**:

- **Strong**: Key model quality metrics are inherently subjective — helpfulness, coherence, tone, etc.
- **Medium**: The task has some subjective element, but also a clear factual or structural component that a programmatic approach could partially cover.
- **Weak**: The task has a single objectively correct answer, and a judge model carries the risk of hallucinating, while a programmatic check would be more reliable.

Think broadly — LLM-as-Judge can surface issues that are hard to anticipate with code, but it's not always the best tool for the job.

### Step 4: Recommend an evaluation type

**Gate — before you recommend, confirm you have every input below.** If the model is Nova, the gate is already satisfied (Custom Scorer is the only option) — skip the checklist and proceed directly to the Nova recommendation. Otherwise, do not present a recommendation until each of these is known. If any is missing, go back and complete the corresponding step first:

- [ ] **Evaluation dataset** confirmed (Step 1)
- [ ] **Model type** known — Nova or OSS (Step 2)
- [ ] **Task + answer format** understood (Step 3a)
- [ ] **Cost sensitivity** obtained directly from the user, or already stated explicitly earlier (Step 3b)
- [ ] **Custom Scorer signal strength** rated (Step 3c) and **LLM-as-Judge signal strength** rated (Step 3d)

Once all inputs are in hand, use the signal strength assessments and cost sensitivity to make a recommendation:

- **Nova model** → recommend **Custom Scorer** (only available option).
- **Custom Scorer signal is strong** → recommend **Custom Scorer**. It's deterministic, reproducible, and cost-effective. A programmatic approach gives you a reliable signal for this task.
- **Cost sensitivity is very high (4-5) and Custom Scorer signal is weak but not totally absent** → recommend **Custom Scorer**, but be upfront that the programmatic signal may be limited for this task. A partial signal at low cost may be preferable to a richer signal at higher cost.
- **LLM-as-Judge signal is strong and Custom Scorer signal is weak** → recommend **LLM-as-Judge**. The task needs the kind of nuanced judgment that only an LLM can provide.
- **Both have medium or strong signal** → Carefully weigh the customer's cost concerns with the benefits of each eval type. Recommend the one that you think fits all of their needs the best.

**Always state caveats.** Whenever the Custom Scorer signal you rated in Step 3c is **medium or weak** (e.g., QA or summarization with free-form / paragraph-length reference answers), and you recommend Custom Scorer, you MUST tell the user that the programmatic signal is limited — semantically-equivalent but differently-worded answers may score poorly, so the result is an approximate signal, not a precise measure of quality.

Present your recommendation with a brief reason:

> "Based on what you've told me, I'd recommend **[evaluation type]** — [one sentence explaining why]. Want to go with that?"

⏸ Wait for user to confirm.

Once the user confirms, return to the main SKILL.md workflow (Step 2: Validate and hand off).

---

## Custom Scorer: choosing the right scorer type

If the user chose Custom Scorer, use this logic to recommend the specific scorer:

| Scorer | Recommend when |
|--------|---------------|
| Prime Math | Task involves mathematical reasoning with verifiable numeric/symbolic answers |
| Prime Code | Task involves code generation that can be tested against input/output pairs |
| Custom Lambda | Any task with custom scoring logic that doesn't fit Prime Math or Prime Code |

**Decision logic:**

1. If task is **math with verifiable answers** → recommend **Prime Math**.
2. If task is **code generation with testable I/O** → recommend **Prime Code**.
3. Otherwise → recommend **Custom Lambda**.
