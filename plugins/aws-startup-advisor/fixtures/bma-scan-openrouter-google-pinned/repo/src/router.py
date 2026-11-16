import os

from openai import OpenAI

router = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])
VERTEX_ONLY = {"provider": {"only": ["google-vertex"]}}


def answer(question: str) -> str:
    resp = router.chat.completions.create(model="anthropic/claude-3.5-sonnet", messages=[{"role": "user", "content": question}])
    return resp.choices[0].message.content


def quick(question: str) -> str:
    resp = router.chat.completions.create(model="google/gemini-2.5-flash", messages=[{"role": "user", "content": question}], extra_body=VERTEX_ONLY)
    return resp.choices[0].message.content
