"""Swarm-style handoff: agents are peers; a special tool transfers control."""
from llm_client import chat

AGENTS = {
    "triage": {
        "system": "You are a triage agent. Hand off billing questions to billing and technical ones to support. Answer nothing yourself.",
        "handoffs": ["billing", "support"],
    },
    "billing": {"system": "You are a billing agent. Answer billing questions in one or two sentences.", "handoffs": []},
    "support": {"system": "You are a technical support agent. Answer in one or two sentences.", "handoffs": []},
}


def handoff_tools(names: list[str]) -> list[dict]:
    return [{
        "type": "function",
        "function": {
            "name": f"transfer_to_{n}",
            "description": f"Hand the conversation to the {n} agent.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    } for n in names]


def run_swarm(user_text: str, start: str = "triage", max_hops: int = 4) -> str:
    """max_hops = maximum number of handoffs; the agent reached after the last one still gets to answer.
    Only the user's message travels with a handoff (a trimmed history); tool calls stay local."""
    active, hops = start, 0
    history = [{"role": "user", "content": user_text}]
    while True:
        agent = AGENTS[active]
        messages = [{"role": "system", "content": agent["system"]}, *history]
        tools = handoff_tools(agent["handoffs"])
        msg = chat(messages, temperature=0.2, **({"tools": tools} if tools else {}))
        target = msg.tool_calls[0].function.name.removeprefix("transfer_to_") if msg.tool_calls else None
        if target in AGENTS:
            hops += 1
            if hops > max_hops:
                return "Stopped: hop limit reached."
            active = target
            continue
        if not (msg.content or "").strip():
            return f"[{active}] (no answer and no valid handoff)"
        return f"[{active}] {msg.content}"


if __name__ == "__main__":
    print(run_swarm("I was charged twice for my subscription."))
