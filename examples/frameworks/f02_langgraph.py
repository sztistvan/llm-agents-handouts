"""LangGraph: the same supervisor as an explicit graph with state, and a checkpointer for memory.

LangGraph does not hide the loop: you declare the state, the nodes (functions) and the edges (including the conditional one
that decides "call a tool or finish"), compile, and invoke. Three things come with it that a plain loop does not give you:
the graph can be drawn (printed below as Mermaid), its state is saved after every step (a checkpointer, per thread id), and
a run can be paused and resumed (interrupt, not used here). Run:  python examples/frameworks/f02_langgraph.py
Install:  pip install langgraph langchain langchain-openai
"""
import common
from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

cfg = common.settings()
model = ChatOpenAI(model=cfg["model"], base_url=cfg["base_url"], api_key=cfg["api_key"])

# the two workers: small agents of their own, wrapped as tools (see f01_langchain.py)
calculator_agent = create_agent(model, tools=[tool(common.add), tool(common.multiply)], system_prompt=common.CALCULATOR_SYSTEM)
writer_agent = create_agent(model, tools=[], system_prompt=common.WRITER_SYSTEM)


def ask(agent, text: str) -> str:
    return agent.invoke({"messages": [{"role": "user", "content": text}]})["messages"][-1].content


@tool("calculator", description=common.CALCULATOR_DESCRIPTION)
def calculator(task: str) -> str:
    return ask(calculator_agent, task)


@tool("writer", description=common.WRITER_DESCRIPTION)
def writer(task: str) -> str:
    return ask(writer_agent, task)


supervisor_model = model.bind_tools([calculator, writer])


def supervisor(state: MessagesState) -> dict:
    """A node: one model call that either asks for a worker (a tool call) or gives the final answer."""
    return {"messages": [supervisor_model.invoke([SystemMessage(common.SUPERVISOR_SYSTEM)] + state["messages"])]}


builder = StateGraph(MessagesState)                            # the state: a list of messages
builder.add_node("supervisor", supervisor)
builder.add_node("workers", ToolNode([calculator, writer]))    # runs the requested worker
builder.add_edge(START, "supervisor")
builder.add_conditional_edges("supervisor", tools_condition, {"tools": "workers", END: END})  # tool call -> workers, else finish
builder.add_edge("workers", "supervisor")
graph = builder.compile(checkpointer=InMemorySaver())          # state is saved per thread_id after every step


def run() -> str:
    config = {"configurable": {"thread_id": "coffee"}}
    return graph.invoke({"messages": [("user", common.TASK)]}, config)["messages"][-1].content


def follow_up() -> str:
    """The same thread again: the checkpointer restores the conversation, so "the same" is understood."""
    config = {"configurable": {"thread_id": "coffee"}}
    return graph.invoke({"messages": [("user", "Now the same for 6 people.")]}, config)["messages"][-1].content


if __name__ == "__main__":
    common.report("LangGraph StateGraph", run)
    common.report("LangGraph, second turn on the same thread (memory from the checkpointer)", follow_up)
    print("\nThe graph as Mermaid:\n" + graph.get_graph().draw_mermaid())
