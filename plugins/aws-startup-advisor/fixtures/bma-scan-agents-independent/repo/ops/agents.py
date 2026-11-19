from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent

from ops.billing.tools import lookup as billing_lookup
from ops.sales.tools import lookup as sales_lookup
from ops.support.tools import lookup as support_lookup

_billing = create_react_agent(ChatAnthropic(model="claude-sonnet-4-5"), tools=[billing_lookup])
support = create_react_agent(ChatAnthropic(model="claude-haiku-4-5"), tools=[support_lookup])
sales = create_react_agent(ChatAnthropic(model="claude-sonnet-4-5"), tools=[sales_lookup])


def handle_billing(question: str) -> str:
    return _billing.invoke({"messages": [("user", question)]})["messages"][-1].content


def handle_support(question: str) -> str:
    return support.invoke({"messages": [("user", question)]})["messages"][-1].content


def handle_sales(question: str) -> str:
    return sales.invoke({"messages": [("user", question)]})["messages"][-1].content
