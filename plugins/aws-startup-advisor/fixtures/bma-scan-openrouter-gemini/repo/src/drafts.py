import os

from google import genai

DRAFT_MODEL = os.environ.get("DRAFT_MODEL", "gemini-2.5-flash")
client = genai.Client()


def draft(prompt: str) -> str:
    return client.models.generate_content(model=DRAFT_MODEL, contents=prompt).text
