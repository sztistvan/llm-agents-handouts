"""Text-based ReAct: works for models without native tool calling (no `tools` parameter)."""
import re

from llm_client import chat

TOOLS = {
    "get_weather": lambda city: f"14C and cloudy in {city}",  # stub; replace with a real API
}

SYSTEM = """Answer using this format, one step at a time:
Thought: <reasoning>
Action: tool_name("argument")
Then stop and wait for the Observation.
When done reply with: Final Answer: <answer>
Tools: get_weather(city)"""


def react_text(question: str, max_steps: int = 5) -> str:
    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    for _ in range(max_steps):
        raw = chat(messages, temperature=0).content or ""
        # Not using the `stop` parameter: some models (e.g. Azure gpt-5 family) reject it.
        # Instead cut the reply at "Observation:" ourselves, in case the model invents one.
        text = raw.split("Observation:")[0].strip()
        messages.append({"role": "assistant", "content": text})
        final = re.search(r"Final Answer:\s*([\s\S]*)", text)
        if final:
            return final.group(1).strip()
        action = re.search(r'Action:\s*(\w+)\("?([^")]*)"?\)', text)
        if not action or action.group(1) not in TOOLS:
            observation = "Error: invalid or unknown action. Use the given format."
        else:
            observation = TOOLS[action.group(1)](action.group(2))
        messages.append({"role": "user", "content": f"Observation: {observation}"})
    return "Stopped: step limit reached."


if __name__ == "__main__":
    print(react_text("What is the weather in Paris?"))
