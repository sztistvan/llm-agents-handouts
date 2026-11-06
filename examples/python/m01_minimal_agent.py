import json

from llm_client import get_client


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
REGISTRY = {"get_time": get_time}


def run_agent(goal: str, max_steps: int = 5) -> str:
    client, model = get_client()
    messages = [
        {"role": "system", "content": "You are a helpful assistant. Use tools when needed."},
        {"role": "user", "content": goal},
    ]
    for _ in range(max_steps):
        msg = client.chat.completions.create(
            model=model, messages=messages, tools=TOOLS
        ).choices[0].message
        messages.append(msg)
        if not msg.tool_calls:
            return msg.content
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments)
                result = REGISTRY[call.function.name](**args)
            except Exception as exc:  # feed errors back so the model can retry
                result = f"Error: {exc}"
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    raise RuntimeError("Step limit reached")


if __name__ == "__main__":
    print(run_agent("What time is it in Budapest?"))
