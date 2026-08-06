# Finetuning Technique Selection Guide

Not all models support all techniques. Always validate technique availability against the selected model's recipes before recommending. Only SFT, DPO, RLVR, and RLAIF are supported.

## Technique Overview

### SFT (Supervised Fine-Tuning)

**Use when:**

- Task has clear right/wrong answers
- Single optimal output per input
- Output represents exemplary responses
- Classification, extraction, structured generation

### DPO (Direct Preference Optimization)

**Use when:**

- Multiple valid outputs, some better than others
- Subjective quality (tone, style, helpfulness)
- Creative tasks with preference judgments

### RLVR (Reinforcement Learning from Verifiable Rewards)

**Use when:**

- Outputs can be verified programmatically
- Want to reward similarity to gold responses
- Code generation (passes tests = reward)
- Math problems (correct answer = reward)
- Constraint satisfaction (meets criteria = reward)

**Key difference from SFT:**

- SFT: Model learns to imitate gold responses directly
- RLVR: Model learns to maximize rewards (can be gold similarity or verification-based)

### RLAIF (Reinforcement Learning from AI Feedback)

**Use when:**

- Quality is subjective and hard to define with rules (tone, helpfulness, brand voice, safety)
- No human preference data is available and collecting it is too expensive or slow
- You want RLHF-level alignment without human annotators
- Task involves summarization, dialogue, or open-ended generation where "better" is a judgment call
- You need scalable preference signals that can be regenerated as the model improves

**Key difference from DPO:**

- DPO: Requires a static dataset of preference pairs (chosen/rejected) upfront
- RLAIF: Uses an AI judge model to generate preference signals or reward scores dynamically, enabling iterative improvement

**Key difference from RLVR:**

- RLVR: Reward is rule-based and programmatic (correct/incorrect, passes tests)
- RLAIF: Reward comes from an AI model evaluating subjective quality (helpfulness, coherence, safety)

**When NOT to use RLAIF:**

- Task has objectively verifiable answers → use RLVR instead
- You already have high-quality human preference data → use DPO instead
- You have clear gold-standard outputs → use SFT instead
- The AI judge model is weaker than the model being trained (judge quality bounds training quality)
