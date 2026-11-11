from langchain_anthropic import ChatAnthropic
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from research.tools import read_notes, web_search

model = ChatAnthropic(model="claude-sonnet-4-5")
research_agent = create_react_agent(model, tools=[web_search, read_notes], checkpointer=MemorySaver())
summarizer = ChatGoogleGenerativeAI(model="gemini-2.5-flash", project="acme-prod")
local = ChatOpenAI(model="gpt-4o-mini", base_url="https://llm-proxy.internal/v1")


def research(topic: str) -> str:
    result = research_agent.invoke({"messages": [("user", topic)]}, config={"configurable": {"thread_id": "1"}})
    return result["messages"][-1].content


def summarize(text: str) -> str:
    return summarizer.invoke(f"Summarize: {text}").content


def classify(text: str) -> str:
    return local.invoke(text).content
