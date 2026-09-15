# LLM-as-Judge Custom Metrics Guide

This file describes the process for collecting and validating custom metric definitions.

## Step 1: Collect Custom Metrics

Ask the user to provide their custom metrics as JSON — either by pasting it directly or pointing to a file. The JSON must be an array of metric definitions following the Bedrock format.

> "Please share your custom metrics JSON. You can paste it here or point me to a file."

⏸ Wait for user.

### Helping Users Structure Metrics

If the user doesn't have ready-made JSON but describes what they want to evaluate, you can help them create the JSON structure. Be upfront about limitations:

> "I can help you put together the JSON structure based on what you've described. Note that I can't guarantee the judge model will interpret your metric exactly as intended — you may need to iterate on the prompt wording after seeing initial results."

When helping, follow the Bedrock-recommended prompt structure (in this order):

1. Role definition (optional)
2. Task description (required, minimum 15 words)
3. Criterion and rubric (optional)
4. Input variables (required, must be last in the prompt)

Available input variables: `{{prompt}}`, `{{prediction}}`, `{{ground_truth}}`

Example of a valid single custom metric:

```json
[
  {
    "customMetricDefinition": {
      "name": "DomainAccuracy",
      "instructions": "You are a domain expert. Evaluate whether the response accurately addresses the domain-specific aspects of the prompt.\n\nPrompt: {{prompt}}\nResponse: {{prediction}}",
      "ratingScale": [
        { "definition": "Accurate", "value": { "floatValue": 1.0 } },
        { "definition": "Inaccurate", "value": { "floatValue": 0.0 } }
      ]
    }
  }
]

```

Multiple custom metrics go in the same array (max 10 per job).

## Step 2: Write and Validate the JSON Artifact

Once you have the custom metrics JSON (from the user or co-created), write it to a file called `custom_metrics.json` in the project root directory (`[PROJECT_DIR]/custom_metrics.json`). This ensures it can be reliably loaded by both notebooks (via `Path("[PROJECT_DIR]") / "custom_metrics.json"`) and scripts regardless of working directory.

Then validate it by running the validation script:

```bash
python scripts/validate_custom_metrics.py custom_metrics.json

```

If validation fails, show the errors to the user and iterate until it passes.

⏸ Do not proceed until validation passes.

## After Collection

Once custom metrics are validated, return to the main workflow (Step 7) to check if the user also wants built-in metrics.
