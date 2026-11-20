"""LangChain: the supervisor with `create_agent` (the "subagents" pattern: workers wrapped as tools).

LangChain's agent function builds a tool-calling loop (on top of LangGraph since version 1.0). A worker is an agent
that is wrapped in a tool, which is exactly what m04_supervisor.py does by hand. Run:  python examples/frameworks/f01_langchain.py
Install:  pip install langchain langchain-openai
"""
import common
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI

cfg = common.settings()
model = ChatOpenAI(model=cfg["model"], base_url=cfg["base_url"], api_key=cfg["api_key"])  # any OpenAI-compatible endpoint

add = tool(common.add)            # the docstring is the description, the type hints are the schema
multiply = tool(common.multiply)

calculator_agent = create_agent(model, tools=[add, multiply], system_prompt=common.CALCULATOR_SYSTEM)
writer_agent = create_agent(model, tools=[], system_prompt=common.WRITER_SYSTEM)


def ask(agent, text: str) -> str:
    return agent.invoke({"messages": [{"role": "user", "content": text}]})["messages"][-1].content


@tool("calculator", description=common.CALCULATOR_DESCRIPTION)
def calculator(task: str) -> str:
    return ask(calculator_agent, task)


@tool("writer", description=common.WRITER_DESCRIPTION)
def writer(task: str) -> str:
    return ask(writer_agent, task)


supervisor = create_agent(model, tools=[calculator, writer], system_prompt=common.SUPERVISOR_SYSTEM)


def run() -> str:
    return ask(supervisor, common.TASK)


if __name__ == "__main__":
    common.report("LangChain create_agent", run)
