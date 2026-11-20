"""Shared pieces of the framework comparison (Module 11): the task, the prompts, the model settings, a call counter.

Every framework example solves the SAME task with the SAME prompts and the SAME two tools, so that what differs is
the framework and not the problem: the supervisor of Module 4 (a supervisor that delegates to a calculator and a writer).
The model settings come from the .env of the course (llm_client.py); every framework below talks to the same
OpenAI-compatible endpoint (Azure OpenAI by default). The call counter patches the HTTP library under all of them (httpx, or httpx2 in recent openai packages),
so the number of model calls is measured the same way for each framework.
"""
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))  # the course's llm_client, agent, m04_supervisor
from llm_client import get_config  # noqa: E402

TASK = "A team has 4 people and each gets 3 coffees. Announce the total coffees."
SUPERVISOR_SYSTEM = ("You are a supervisor. Delegate work to your specialists and never calculate or write "
                     "the final text yourself. First get numbers from the calculator, then ask the writer "
                     "to phrase the result. Return the writer's text as the final answer.")
CALCULATOR_SYSTEM = "You are a calculator. Always use the tools for arithmetic and reply with the number only."
WRITER_SYSTEM = "You write short, friendly text. Use only the facts you are given."
CALCULATOR_DESCRIPTION = "Specialist for arithmetic. Give it a calculation to perform."
WRITER_DESCRIPTION = "Specialist for writing short, friendly text from facts you provide."


def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


def settings() -> dict:
    """base_url, api_key and model (the deployment name on Azure) of the provider chosen in .env."""
    return get_config()


# ------------------------------------------------------------------------------------ counting the model calls
CALLS = {"n": 0}


def _count(request) -> None:
    if request.method == "POST" and request.url.path.endswith("/chat/completions"):
        CALLS["n"] += 1


def _patch(library) -> None:
    """Count the requests that go through this HTTP library (the openai package 3.x uses `httpx2`, older ones `httpx`)."""
    send, async_send = library.Client.send, library.AsyncClient.send

    def counting_send(self, request, **kwargs):
        _count(request)
        return send(self, request, **kwargs)

    async def counting_async_send(self, request, **kwargs):
        _count(request)
        return await async_send(self, request, **kwargs)

    library.Client.send, library.AsyncClient.send = counting_send, counting_async_send


_patch(httpx)
try:
    import httpx2
    _patch(httpx2)
except ImportError:
    pass


def report(name: str, run) -> str:
    """Run the example, then print the answer, the number of model calls and the seconds it took."""
    CALLS["n"] = 0
    started = time.time()
    answer = str(run())
    print(f"{name}\n  answer: {answer.strip()}\n  model calls: {CALLS['n']}, seconds: {time.time() - started:.1f}")
    return answer
