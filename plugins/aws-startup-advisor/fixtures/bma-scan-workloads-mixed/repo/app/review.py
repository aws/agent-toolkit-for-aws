import anthropic
from google import genai
from google.genai import types

claude = anthropic.Anthropic()
gemini = genai.Client(api_key="unused")
REVIEW_FORMAT = {"type": "json_schema", "schema": {"type": "object"}}
LOOKUP = {"name": "lookup", "description": "Look up an order", "input_schema": {"type": "object"}}


def review(diff: str) -> str:
    msg = claude.messages.create(model="claude-sonnet-4-5", max_tokens=1024, messages=[{"role": "user", "content": diff}],
                                 output_config={"format": REVIEW_FORMAT}, tools=[LOOKUP])
    return msg.content[0].text


def summarize(text: str) -> str:
    config = types.GenerateContentConfig(response_mime_type="application/json")
    return gemini.models.generate_content(model="gemini-2.5-flash", contents=text, config=config).text


def embed(text: str) -> list[float]:
    return gemini.models.embed_content(model="text-embedding-004", contents=text).embeddings[0].values
