"""Pydantic AI: the supervisor by agent delegation, and a typed result.

Agents are typed: tools are plain functions whose signature becomes the schema, and `output_type` makes the final answer a
validated Pydantic object (the parse-validate-retry of Module 2, built in). Delegation is an ordinary tool that runs another
agent and passes `usage=ctx.usage`, so that token usage is counted for the whole tree.
Run:  python examples/frameworks/f04_pydantic_ai.py        Install:  pip install "pydantic-ai-slim[openai]"
"""
import os

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")  # otherwise a banner with an advertisement for the Logfire service is printed

import common  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from pydantic_ai import Agent, RunContext  # noqa: E402
from pydantic_ai.models.openai import OpenAIChatModel  # noqa: E402
from pydantic_ai.providers.openai import OpenAIProvider  # noqa: E402

cfg = common.settings()
model = OpenAIChatModel(cfg["model"], provider=OpenAIProvider(base_url=cfg["base_url"], api_key=cfg["api_key"]))


class Announcement(BaseModel):
    """The typed result: the model must fill exactly these fields, and a wrong answer is sent back to it for correction."""
    total_coffees: int
    message: str


calculator_agent = Agent(model, instructions=common.CALCULATOR_SYSTEM, tools=[common.add, common.multiply])
writer_agent = Agent(model, instructions=common.WRITER_SYSTEM)


def make_supervisor(**options) -> Agent:
    supervisor = Agent(model, **options)

    @supervisor.tool
    async def calculator(ctx: RunContext, task: str) -> str:
        """Specialist for arithmetic. Give it a calculation to perform."""
        return (await calculator_agent.run(task, usage=ctx.usage)).output

    @supervisor.tool
    async def writer(ctx: RunContext, task: str) -> str:
        """Specialist for writing short, friendly text from facts you provide."""
        return (await writer_agent.run(task, usage=ctx.usage)).output

    return supervisor


def run() -> str:
    return make_supervisor(instructions=common.SUPERVISOR_SYSTEM).run_sync(common.TASK).output


def typed() -> str:
    supervisor = make_supervisor(
        instructions=common.SUPERVISOR_SYSTEM.replace("Return the writer's text as the final answer.",
                                                      "Return the total and the writer's text."),
        output_type=Announcement)
    result = supervisor.run_sync(common.TASK).output
    return f"{result!r}   (a validated {type(result).__name__} object: total_coffees is an int, not text)"


if __name__ == "__main__":
    common.report("Pydantic AI, agent delegation", run)
    common.report("Pydantic AI, typed result", typed)
