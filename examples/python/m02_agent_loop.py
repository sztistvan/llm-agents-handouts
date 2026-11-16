import json

from llm_client import get_client

MAX_TOOL_OUTPUT = 2000


class Tool:
    def __init__(self, fn, description, parameters):
        self.fn, self.description, self.parameters = fn, description, parameters

    def schema(self):
        return {"type": "function", "function": {
            "name": self.fn.__name__, "description": self.description, "parameters": self.parameters}}


def run_agent(goal, tools, system="You are a helpful assistant.", max_steps=8):
    client, model = get_client()
    registry = {t.fn.__name__: t for t in tools}
    messages = [{"role": "system", "content": system}, {"role": "user", "content": goal}]
    for _ in range(max_steps):
        msg = client.chat.completions.create(
            model=model, messages=messages, tools=[t.schema() for t in tools], temperature=0.2
        ).choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content
        for call in msg.tool_calls:
            name = call.function.name
            try:
                if name not in registry:
                    raise ValueError(f"unknown tool '{name}'")
                result = str(registry[name].fn(**json.loads(call.function.arguments)))
            except Exception as exc:
                result = f"Error: {exc}"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result[:MAX_TOOL_OUTPUT]})
    return "Stopped: step limit reached."


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
