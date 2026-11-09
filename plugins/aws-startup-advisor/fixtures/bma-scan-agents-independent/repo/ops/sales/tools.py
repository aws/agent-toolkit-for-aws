from langchain_core.tools import tool


@tool
def lookup(account: str) -> str:
    """Look up an account's plan."""
    return f"{account}: team plan"
