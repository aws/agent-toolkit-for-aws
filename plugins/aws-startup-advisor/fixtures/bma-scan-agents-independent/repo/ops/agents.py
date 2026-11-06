from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

from ops.tools import check_status, issue_refund

_billing = create_react_agent(ChatAnthropic(model="claude-sonnet-4-5"), tools=[issue_refund])
support = create_react_agent(ChatAnthropic(model="claude-haiku-4-5"), tools=[check_status])


def handle_billing(question: str) -> str:
    return _billing.invoke({"messages": [("user", question)]})["messages"][-1].content


def handle_support(question: str) -> str:
    return support.invoke({"messages": [("user", question)]})["messages"][-1].content
