"""Module 2 lesson: the reusable agent loop (Tool + run_agent live in agent.py) with two demo tools."""
from agent import Tool, run_agent


def add(a: float, b: float):
    return a + b


def word_count(text: str):
    return len(text.split())


TOOLS = [
    Tool(add, "Add two numbers.",
         {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]}),
    Tool(word_count, "Count words in a text.",
         {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}),
]

if __name__ == "__main__":
    print(run_agent("How many words are in 'the quick brown fox'? Then add 10 to that count.", TOOLS))
