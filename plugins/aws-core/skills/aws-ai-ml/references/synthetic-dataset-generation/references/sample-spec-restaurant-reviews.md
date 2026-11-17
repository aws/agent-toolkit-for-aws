# Restaurant Review Sentiment Classification Dataset

## Use Case Context
A restaurant conglomerate that owns several restaurants across multiple cities wants to generate a synthetic review dataset for training a sentiment classification model. The dataset should reflect the diversity of the company's portfolio — different cuisine types, restaurant formats, and locations — while producing realistic reviews grounded in the style and tone of real customer feedback. The model will be fine-tuned using SFT on a Nova model via Bedrock.

## Quality Standards

- Authenticity: Reviews should read like real customer feedback, not marketing copy or template output
- Sentiment accuracy: The sentiment label must accurately reflect the tone of the generated review
- Grounding: Each generated review should reflect the style and length of a real review from the same restaurant and star rating
- Diversity: Cover the full range of restaurants, cuisine types, star ratings, and review styles in the portfolio

## Input Data

- `restaurants.csv` — CSV file listing the company's restaurants. Contains the columns `restaurant_name, cuisine_type, city, address, restaurant_type`

- `reviews.parquet` — Parquet file of real customer reviews with columns: `restaurant_name, review_source, username, date, star_rating, review_text`

## Input Data Preparation

- Load `restaurants.csv` with pandas (`pd.read_csv`) and drop any rows that have a null value for any of restaurant_name, restaurant_type, cuisine_type. Those columns will be referenced as categorical fields.
- Load `reviews.parquet` with pandas (`pd.read_parquet`) and drop any records where review_text is empty or under 5 words. review_text will be sampled, conditioned on star_rating and restaurant_name. Deduplicate reviews by review_text (some reviews appear on multiple sources)

## Output Schema
Bedrock Converse format (JSONL), compatible with SageMaker Nova SFT. Note: Bedrock_Converse is a strict-key format — only `messages`, `schemaVersion`, `system`, and `toolConfig` are allowed as top-level keys. All generation-time fields (restaurant_name, cuisine_type, etc.) are used during generation but only the `messages` structure appears in the final output record.

```json
{
    "messages": [
        {
            "role": "user",
            "content": [
                {
                    "text": "Classify the sentiment of the following restaurant review as positive, negative, or neutral:\n\n{review_text}"
                }
            ]
        },
        {
            "role": "assistant",
            "content": [
                {
                    "text": "{sentiment}"
                }
            ]
        }
    ]
}
```

## Data Generation

### Data Fields

1. **Sample categorical attributes**:
    - restaurant_name (Core): sample from restaurant names in restaurants.csv
    - cuisine_type (Core): use the cuisine_type corresponding to the sampled restaurant_name from restaurants.csv
    - restaurant_type (Core): use the restaurant_type corresponding to the sampled restaurant_name from restaurants.csv
    - star_rating (Core): weighted (5% 1-star, 15% 2-star, 25% 3-star, 35% 4-star, 20% 5-star)
    - seed_review (Auxiliary): from reviews.parquet, select a real review matching the sampled restaurant_name and star_rating.
2. **LLM-generated fields**:
    - review_text (Core): Use restaurant_name, cuisine_type, restaurant_type, star_rating, and seed_review. Write a restaurant review that matches the style, approximate length, and star_rating of the seed_review, but with original content. Reference specific details appropriate to the cuisine_type and restaurant_type.
3. **Compute programmatic fields**:
    - sentiment (Core): mapped from star_rating — 1-2 stars → "negative", 3 stars → "neutral", 4-5 stars → "positive"

## Data Verification

1. **Structural checks**:
    - output format: each record has only allowed Bedrock Converse top-level keys (`messages` required; no extra keys like `restaurant_name` or `sentiment` at the top level). `messages` is an array with exactly 2 elements, first with `role: "user"` and second with `role: "assistant"`, each containing a `content` array with at least one object that has a `text` key.
    - user message `content[0].text` contains the review_text
    - assistant message `content[0].text` is one of [positive, negative, neutral]
    - 3-gram overlap between review_text and seed_review must be below 30% (measured as fraction of generated review's 3-grams that appear in the seed)

2. **Semantic checks (LLM-based)** — single consolidated LLM call per record:
    - classify the sentiment expressed in the review_text within the user message on a scale of 1-3. Reject sample if predicted sentiment is more than 1 step away from mapped sentiment
