# LLM-as-Judge with Built-in Metrics: Alignment Guide

This file describes the process for aligning on built-in metrics to use for model evaluations with LLMaaJ.

## Select Metrics

Refer to the metrics tables below for the full list of metrics with descriptions and common combinations.

Based on the user's task and data, recommend specific metrics with reasoning:

> "Based on your [task], I recommend these metrics:
>
> - [metric1]: [why it matters for this task]
>
> Does this look good, or do you want to consider other metrics?"

⏸ **Wait for user to confirm.**

Tips:

- Start with the common combinations from the metrics file as a baseline
- Adjust based on what you know about the user's task and data
- If the user pushes back, understand why and adjust — don't just agree

## LLM-as-Judge Built-in Metrics

SageMaker provides 11 built-in metrics for LLM-as-Judge evaluation, organized into Quality and Responsible AI categories.

## Quality Metrics

| Metric                   | Description                                                                                                                                                              | When to Use                                                          |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------- |
| Correctness              | Measures if the model's response to the prompt is correct. If a reference response (ground truth) is provided in the dataset, the evaluator considers this when scoring. | QA, math problems, factual tasks                                     |
| Completeness             | Measures how well the model's response answers every question in the prompt. If a reference response is provided, the evaluator considers this when scoring.             | Multi-part questions, comprehensive answers, summarization           |
| Faithfulness             | Identifies whether the response contains information not found in the prompt to measure how faithful the response is to the available context.                           | RAG applications, context-grounded responses                         |
| Helpfulness              | Measures how helpful the model's response is using factors including whether it follows instructions, is sensible and coherent, and anticipates implicit needs.          | General assistance, customer service, broad evaluation               |
| Coherence                | Measures how coherent the response is by identifying logical gaps, inconsistencies, and contradictions.                                                                  | Long-form content, reasoning tasks, explanations                     |
| Relevance                | Measures how relevant the answer is to the prompt.                                                                                                                       | All tasks - commonly used baseline metric                            |
| FollowingInstructions    | Measures how well the model's response respects the exact directions found in the prompt.                                                                                | Instruction-following tasks, structured outputs, specific formatting |
| ProfessionalStyleAndTone | Measures how appropriate the response's style, formatting, and tone is for a professional setting.                                                                       | Business communications, formal writing                              |

## Responsible AI Metrics

| Metric       | Description                                                                                                    | When to Use                                       |
| ------------ | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| Harmfulness  | Evaluates whether the response contains harmful content.                                                       | Safety evaluation, content moderation             |
| Stereotyping | Evaluates whether content in the response contains stereotypes of any kind (either positive or negative).      | Fairness evaluation, bias detection               |
| Refusal      | Determines if the response directly declines to answer the prompt or rejects the request by providing reasons. | Safety evaluation, understanding model boundaries |

## Usage in Code

In code, these metrics are specified as `Builtin.Correctness`, `Builtin.Completeness`, etc. When discussing with users, use natural language names.

## Common Metric Combinations

- **QA/Math tasks** → Correctness, Completeness, Faithfulness, Relevance
- **Summarization** → Completeness, Coherence, Relevance
- **General assistance** → Helpfulness, Relevance, FollowingInstructions
- **Safety evaluation** → Harmfulness, Stereotyping, Refusal
