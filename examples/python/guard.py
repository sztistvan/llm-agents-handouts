"""A small production-style agent loop (Module 12): budgets, a permission gate, an audit trail and a trace.

Shared building block. Layers: llm_client -> agent (Tool) -> guard -> m12_* lessons. `run_guarded` is the loop of Module 2
with the things a real deployment adds around it, which makes it a harness in miniature (see docs/glossary.md):

  BUDGETS      a maximum of model calls (steps), tool calls, tokens and (optionally) money per run; when one is used up the
               run stops with a reason instead of looping or spending without limit
  PERMISSIONS  tools on the read-only list run; every other tool needs `policy.approve(name, arguments)` to say yes, and a
               "no" is returned to the model as the tool's result. The decision is made in code, never by the model
  AUDIT TRAIL  every tool call with its outcome (ran, denied, error), in `result.audit`
  TRACE        one span per model call and per tool call with timings and token counts, in `result.spans`. The attribute
               names follow the OpenTelemetry GenAI conventions (status: Development), so the spans can be exported later

Prices for the cost estimate come from PRICE_INPUT_PER_M and PRICE_OUTPUT_PER_M (dollars per million tokens), optionally
prefixed by the provider (AZURE_PRICE_INPUT_PER_M); without them the cost is None.
"""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable

from agent import Tool
from llm_client import chat_full, get_config, get_provider

MAX_TOOL_OUTPUT = 2000


def prices() -> tuple[float, float] | None:
    """(input, output) dollars per million tokens from the environment, or None when not set."""
    def read(name: str):
        return os.environ.get(f"{get_provider().upper()}_{name}") or os.environ.get(name)
    low, high = read("PRICE_INPUT_PER_M"), read("PRICE_OUTPUT_PER_M")
    return (float(low), float(high)) if low and high else None


def estimate_cost(input_tokens: int, output_tokens: int) -> float | None:
    rate = prices()
    return None if rate is None else (input_tokens * rate[0] + output_tokens * rate[1]) / 1_000_000


@dataclass
class Policy:
    read_only: set = field(default_factory=set)                       # tools that run without asking
    approve: Callable[[str, dict], bool] = lambda name, arguments: False  # asked for every other tool
    max_steps: int = 8                                                # model calls
    max_tool_calls: int = 12
    max_tokens: int = 30_000                                          # input + output tokens of the whole run
    max_cost: float | None = None                                     # dollars, needs prices()


@dataclass
class Result:
    answer: str
    stop_reason: str                                                  # final | max_steps | max_tool_calls | max_tokens | max_cost
    spans: list = field(default_factory=list)
    audit: list = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    @property
    def tool_calls(self) -> list[dict]:
        return [a for a in self.audit if a["outcome"] != "unknown_tool"]

    @property
    def cost(self) -> float | None:
        return estimate_cost(self.input_tokens, self.output_tokens)


def run_guarded(goal: str, tools: list[Tool], system: str = "You are a helpful assistant.", policy: Policy | None = None,
                messages: list | None = None) -> Result:
    policy = policy or Policy()
    registry = {t.name: t for t in tools}
    model = get_config()["model"]
    messages = messages if messages is not None else []
    if not messages:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": goal})
    result = Result(answer="", stop_reason="final")

    def over_budget(step: int, calls: int) -> str | None:
        if step >= policy.max_steps:
            return "max_steps"
        if calls >= policy.max_tool_calls:
            return "max_tool_calls"
        if result.input_tokens + result.output_tokens >= policy.max_tokens:
            return "max_tokens"
        if policy.max_cost is not None and (result.cost or 0) >= policy.max_cost:
            return "max_cost"
        return None

    calls = 0
    for step in range(policy.max_steps + 1):
        reason = over_budget(step, calls)
        if reason:
            result.stop_reason, result.answer = reason, f"Stopped: {reason.replace('_', ' ')} reached."
            return result
        started = time.time()
        message, usage = chat_full(messages, tools=[t.schema() for t in tools], temperature=0.2)
        cached = ((usage.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
        result.input_tokens += usage.get("prompt_tokens", 0)
        result.output_tokens += usage.get("completion_tokens", 0)
        result.cached_tokens += cached
        result.spans.append({"name": "chat", "duration_s": time.time() - started, "attributes": {
            "gen_ai.operation.name": "chat", "gen_ai.request.model": model,
            "gen_ai.usage.input_tokens": usage.get("prompt_tokens", 0), "gen_ai.usage.output_tokens": usage.get("completion_tokens", 0),
            "cached_tokens": cached, "tool_calls_requested": len(message.tool_calls or [])}})
        messages.append(message)
        if not message.tool_calls:
            result.answer = message.content or ""
            return result
        for call in message.tool_calls:
            name = call.function.name
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            started = time.time()
            if name not in registry:
                outcome, text = "unknown_tool", f"Error: unknown tool '{name}'"
            elif name not in policy.read_only and not policy.approve(name, arguments):
                outcome, text = "denied", "Error: this action needs the user's approval and was not approved."
            else:
                calls += 1
                try:
                    outcome, text = "ran", str(registry[name].fn(**arguments))
                except Exception as exc:
                    outcome, text = "error", f"Error: {exc}"
            result.audit.append({"tool": name, "arguments": arguments, "outcome": outcome})
            result.spans.append({"name": "execute_tool", "duration_s": time.time() - started, "attributes": {
                "gen_ai.operation.name": "execute_tool", "tool": name, "outcome": outcome, "result_chars": len(text)}})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": text[:MAX_TOOL_OUTPUT]})
    result.stop_reason, result.answer = "max_steps", "Stopped: max steps reached."
    return result
