import json

from llm_client import get_client, show, trace_mode


def get_time(city: str) -> str:
    return f"It is 12:00 in {city}."  # stub; replace with a real API


TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_time",
        "description": "Get the current time in a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
    },
}]
REGISTRY = {"get_time": get_time} # mapping of tool names to their corresponding functions


def run_agent(goal: str, max_steps: int = 5) -> str:
    client, model = get_client()
    mode = trace_mode(default="compact")  # LLM_TRACE=raw: full JSON; LLM_TRACE=off: silent
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Use tools when needed."},
        {"role": "user", "content": goal},
    ]
    for step in range(1, max_steps + 1):
        msg = client.chat.completions.create(
            model=model, messages=messages, tools=TOOLS
        ).choices[0].message 
        messages.append(msg)
        show(msg, step, mode)
        if not msg.tool_calls:  # no tool call = the model has given its final answer
            return msg.content
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments)
                result = REGISTRY[call.function.name](**args) # call the registered tool function with the provided arguments
            except Exception as exc:  # feed errors back so the model can retry
                result = f"Error: {exc}"
            tool_msg = {"role": "tool", "tool_call_id": call.id, "content": result}
            messages.append(tool_msg)
            show(tool_msg, step, mode)
    raise RuntimeError("Step limit reached")


if __name__ == "__main__":
    print(run_agent("What time is it in Budapest?"))
