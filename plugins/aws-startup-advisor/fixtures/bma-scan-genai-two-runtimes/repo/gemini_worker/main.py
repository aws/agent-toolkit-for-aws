from google import genai

client = genai.Client()


def tag(text: str) -> str:
    return client.models.generate_content(model="gemini-2.5-flash", contents=f"Tag: {text}").text
