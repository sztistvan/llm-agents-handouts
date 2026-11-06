"""Supervisor pattern: specialist agents exposed as tools to a supervisor agent."""
from m02_agent_loop import Tool, run_agent

TASK_SCHEMA = {
    "type": "object",
    "properties": {"task": {"type": "string", "description": "What the specialist should do."}},
    "required": ["task"],
}


def add(a: float, b: float):
    return a + b


def multiply(a: float, b: float):
    return a * b


NUM = {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}
MATH_TOOLS = [Tool(add, "Add two numbers.", NUM), Tool(multiply, "Multiply two numbers.", NUM)]


def make_worker_tool(name: str, description: str, system: str, tools: list) -> Tool:
    def worker(task: str) -> str:
        return run_agent(task, tools, system=system, max_steps=5)

    worker.__name__ = name
    return Tool(worker, description, TASK_SCHEMA)


calculator = make_worker_tool(
    "calculator", "Specialist for arithmetic. Give it a calculation to perform.",
    "You are a calculator. Always use the tools for arithmetic and reply with the number only.", MATH_TOOLS)
writer = make_worker_tool(
    "writer", "Specialist for writing short, friendly text from facts you provide.",
    "You write short, friendly text. Use only the facts you are given.", [])

SUPERVISOR = (
    "You are a supervisor. Delegate work to your specialists and never calculate or write "
    "the final text yourself. First get numbers from the calculator, then ask the writer "
    "to phrase the result. Return the writer's text as the final answer."
)

if __name__ == "__main__":
    print(run_agent("A team has 4 people and each gets 3 coffees. Announce the total coffees.",
                    [calculator, writer], system=SUPERVISOR, max_steps=8))
