import os

from openai import OpenAI

client = OpenAI(default_headers={"OpenAI-Project": os.environ.get("OPENAI_PROJECT_ID", "")})


def start_report(text: str) -> str:
    resp = client.responses.create(model="gpt-4o", background=True, input=f"Write a report on: {text}")
    return resp.id


def research(question: str) -> str:
    resp = client.responses.create(model="gpt-4o", tools=[{"type": "web_search"}], input=question)
    return resp.output_text


def ask_docs(question: str) -> str:
    resp = client.responses.create(
        model="gpt-4o",
        tools=[{"type": "mcp", "server_label": "docs", "server_url": "https://example.com/mcp"}],
        input=question,
    )
    return resp.output_text


def lookup(query: str) -> str:
    resp = client.chat.completions.create(
        model="gpt-4o",
        tools=[{"type": "function", "function": {"name": "web_search", "parameters": {"type": "object"}}}],
        messages=[{"role": "user", "content": query}],
    )
    return resp.choices[0].message.content


def remember(note: str) -> str:
    resp = client.responses.create(model="gpt-4o", store=True, input=note)
    return resp.id
