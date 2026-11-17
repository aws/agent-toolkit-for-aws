# Product Review Sentiment Classification Dataset

## Use Case Context
Generate a dataset of product reviews with sentiment labels for training a
classification model. A US-based online retailer wants to understand customer
sentiment to identify actionable insights for capitalizing on successful products
and improving struggling ones. Each sample contains a prompt-completion pair
where the prompt asks to classify a review's sentiment and the completion
provides the correct label (positive, negative, or neutral). The model will be
fine-tuned using SFT on an open-source HuggingFace model.

## Quality Standards

- Authenticity: Reviews must reflect genuine customer experiences, not template-like output
- Sentiment accuracy: Labels must accurately match the expressed sentiment in the review
- Diversity: Cover a range of product categories, review lengths, and writing styles
- Naturalness: Written in conversational English with realistic customer language

## Output Schema
HuggingFace Prompt Completion format (JSONL), compatible with SageMaker open-source SFT. Extra metadata fields are included alongside the required `prompt` and `completion` keys (HF_Prompt_Completion allows additional keys):

```json
{
  "prompt": "Classify the sentiment of the following product review as positive, negative, or neutral:\n\n{review_text}",
  "completion": "{sentiment}",
  "product_category": "product category, string",
  "sentiment": "sentiment label, string",
  "review_text": "generated product review, string",
  "review_length": "target length category, string",
  "review_aspects": "aspects covered in the review, array of strings",
  "customer_experience_level": "simulated reviewer experience, string"
}
```

## Data Generation

### Data Fields

1. **Sample categorical attributes** with specified distributions:
    - product_category (Core): weighted (25% Electronics, 20% Home & Kitchen, 15% Clothing & Accessories, 10% Toys & Games, 10% Sports & Outdoors, 8% Beauty & Personal Care, 5% Pet Supplies, 3% Automotive, 2% Books, 2% Health & Wellness)
    - sentiment (Core): The overall sentiment of the review, weighted (40% positive, 30% negative, 30% neutral)
    - review_length (Auxiliary): Target word-count range, weighted (40% short (20-50 words), 40% medium (50-100 words), 20% long (100-200 words))
    - review_aspects (Auxiliary): array of 1-3, select uniformly without replacement from [quality, value, shipping, customer service, durability, ease of use, design]
    - customer_experience_level (Auxiliary): weighted (20% novice, 60% regular, 20% power_user)
2. **LLM-generated fields**:
    - review_text (Core): Use product_category, sentiment, review_length, review_aspects, and customer_experience_level. Reason about how to construct an authentic review, then extract the final review from the chain-of-thought output. Vary writing style based on customer experience level (novice=simpler, power_user=detailed technical).
3. **Compute programmatic fields**:
    - prompt (Core): Use template "Classify the sentiment of the following product review as positive, negative, or neutral:\n\n{review_text}"
    - completion (Core): Copy the sentiment field value exactly (case-sensitive)

### Generation Constraints

- Avoid overly generic or template-like language

## Data Verification

1. **Structural checks**:
    - output format: each record contains `prompt` and `completion` keys with non-empty string values, and does NOT contain `chosen` or `rejected` keys (HF_Prompt_Completion format)
    - review_aspects: 1-3 unique values from the allowed list, no duplicates
    - prompt: contains exact template text with review_text inserted, non-empty
    - completion: one of [positive, negative, neutral], exactly matches sentiment (case-sensitive)
    - review_text word count: within review_length spec (short: 20-50, medium: 50-100, long: 100-200) ±10% tolerance

2. **Semantic checks (LLM-based)** — single consolidated LLM call per record:
    - Classify the sentiment expressed in review_text and verify it matches the sentiment field
    - Request prediction in XML format for reliable parsing
    - Reject sample if predicted sentiment does not match the sentiment field
