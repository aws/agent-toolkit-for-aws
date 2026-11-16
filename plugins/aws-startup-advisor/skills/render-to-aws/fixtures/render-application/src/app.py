import os
from openai import OpenAI

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

def generate():
    return client.responses.create(model="gpt-4o-mini", input="not retained by scanner")
