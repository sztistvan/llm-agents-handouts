"""Reusable agent loop (Module 2): `Tool` and `run_agent`.

Shared building block: the later modules import it (the supervisor in Module 4 uses it for its workers).
Layers: llm_client.py (talk to the model) -> agent.py (the loop) -> the mNN_*.py lessons.
The lessons show how it is built; see docs/02-building-blocks.md, section 6.
"""
import json

from llm_client import get_client, show, trace_mode

MAX_TOOL_OUTPUT = 2000


class Tool:
    """A function the model may call: the Python function, a description, and a JSON Schema of its arguments.

    The name the model sees is the function's name unless you pass `name`
    (needed for tools that are created dynamically, for example wrapped agents or MCP tools).
    """

    def __init__(self, fn, description, parameters, name=None):
        self.fn, self.description, self.parameters = fn, description, parameters
        self.name = name or fn.__name__

    def schema(self):
        return {"type": "function", "function": {
            "name": self.name, "description": self.description, "parameters": self.parameters}}


def run_agent(goal, tools, system="You are a helpful assistant.", max_steps=8, messages=None):
    """Run the agent loop and return the final answer (a string).

    messages: optional conversation so far. The list is extended in place (the system message is
    added only if the list is empty), so pass the same list again to continue the conversation.
    """
    client, model = get_client()
    registry = {t.name: t for t in tools}  # mapping of tool names to their corresponding Tool instances
    mode = trace_mode()  # off by default; LLM_TRACE=1 one line per message, LLM_TRACE=raw full JSON
    if messages is None:
        messages = []
    if not messages:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": goal})
    for step in range(1, max_steps + 1):
        msg = client.chat.completions.create(
            model=model, messages=messages, tools=[t.schema() for t in tools], temperature=0.2
        ).choices[0].message
        messages.append(msg)
        show(msg, step, mode)
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
            tool_msg = {"role": "tool", "tool_call_id": call.id, "content": result[:MAX_TOOL_OUTPUT]}
            messages.append(tool_msg)
            show(tool_msg, step, mode)
    return "Stopped: step limit reached."
