from openai import OpenAI

client = OpenAI()
TICKET_SCHEMA = {"type": "json_schema", "json_schema": {"name": "ticket", "schema": {"type": "object"}}}


def reply(question: str) -> str:
    resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": question}], stream=True)
    return "".join(chunk.choices[0].delta.content or "" for chunk in resp)


def triage(text: str) -> str:
    resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": text}], response_format=TICKET_SCHEMA)
    return resp.choices[0].message.content


def describe(image_url: str) -> str:
    content = [{"type": "text", "text": "Describe this."}, {"type": "image_url", "image_url": {"url": image_url}}]
    resp = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": content}])
    return resp.choices[0].message.content


def draft(prompt: str) -> str:
    return client.responses.create(model="gpt-4.1", input=prompt).output_text


def setup() -> str:
    return client.beta.assistants.create(model="gpt-4o", name="helper").id


def route(ticket: str) -> str:
    resp = client.chat.completions.create(model="ft:gpt-4o-mini-2024-07-18:acme:triage:a1b2", messages=[{"role": "user", "content": ticket}])
    return resp.choices[0].message.content
