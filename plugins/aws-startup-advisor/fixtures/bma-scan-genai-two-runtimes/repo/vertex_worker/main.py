from google import genai

client = genai.Client(project="acme-prod", location="us-central1")


def summarize(doc: str) -> str:
    return client.models.generate_content(model="gemini-2.5-pro", contents=f"Summarize: {doc}").text
