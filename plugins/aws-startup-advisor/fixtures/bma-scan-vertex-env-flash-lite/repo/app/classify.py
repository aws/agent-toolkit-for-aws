from google import genai

client = genai.Client(project="acme-prod", location="us-central1")


def label(ticket: str) -> str:
    resp = client.models.generate_content(model="gemini-2.5-flash-lite", contents=f"Label this ticket: {ticket}")
    return resp.text
