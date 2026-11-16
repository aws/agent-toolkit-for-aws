import os

from langchain_openai import ChatOpenAI
from openai import OpenAI

ROUTER = "https://openrouter.ai/api/v1"
writer = ChatOpenAI(model="openai/gpt-4o", base_url=ROUTER, api_key=os.environ["OPENROUTER_API_KEY"])
router = OpenAI(base_url=ROUTER, api_key=os.environ["OPENROUTER_API_KEY"])


def write(topic: str) -> str:
    return writer.invoke(f"Write about {topic}").content


def check(text: str) -> str:
    resp = router.chat.completions.create(model="anthropic/claude-3.5-sonnet", messages=[{"role": "user", "content": text}])
    return resp.choices[0].message.content
