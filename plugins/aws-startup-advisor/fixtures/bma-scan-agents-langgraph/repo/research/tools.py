import os

import httpx
from langchain_core.tools import tool


@tool
def web_search(query: str) -> str:
    """Search the web."""
    resp = httpx.get("https://search.example.com/v1", params={"q": query}, headers={"x-api-key": os.environ["SEARCH_API_KEY"]})
    return resp.text


@tool
def read_notes(path: str) -> str:
    """Read a local notes file."""
    with open(path) as f:
        return f.read()
