import requests
from langchain_core.tools import tool


@tool
def lookup(service: str) -> str:
    """Check a service status page."""
    return requests.get(f"https://status.example.com/{service}", timeout=5).text
