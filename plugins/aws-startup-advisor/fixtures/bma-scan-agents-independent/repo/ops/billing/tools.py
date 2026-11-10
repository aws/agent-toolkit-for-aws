from langchain_core.tools import tool


@tool
def lookup(order_id: str) -> str:
    """Look up an order's refund state."""
    return f"refund queued for {order_id}"
