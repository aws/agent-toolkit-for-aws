import requests
from langchain_core.tools import tool


@tool
def issue_refund(order_id: str) -> str:
    """Record a refund for an order."""
    return f"refund queued for {order_id}"


@tool
def check_status(service: str) -> str:
    """Check a service status page."""
    return requests.get(f"https://status.example.com/{service}", timeout=5).text
