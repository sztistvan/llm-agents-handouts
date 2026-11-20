"""OpenAI Agents SDK: the supervisor with `agent.as_tool`, and a handoff variant.

Agents are small objects (name, instructions, model, tools). A specialist can become a tool of another agent
(`as_tool`: the supervisor stays in control, like m04_supervisor) or a handoff target (`handoffs=[...]`: control moves to the
specialist, the pattern of Module 4's swarm). The SDK uses the Responses API of OpenAI by default; here we point it at any
OpenAI-compatible endpoint through the Chat Completions model class, and switch tracing (to OpenAI's servers) off.
Run:  python examples/frameworks/f03_openai_agents.py        Install:  pip install openai-agents
"""
import common
from agents import Agent, OpenAIChatCompletionsModel, Runner, function_tool, set_tracing_disabled
from openai import AsyncOpenAI

set_tracing_disabled(True)  # traces would go to platform.openai.com; there is no OpenAI key here
cfg = common.settings()
model = OpenAIChatCompletionsModel(model=cfg["model"], openai_client=AsyncOpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"]))

calculator = Agent(name="calculator", instructions=common.CALCULATOR_SYSTEM, model=model,
                   tools=[function_tool(common.add), function_tool(common.multiply)],
                   handoff_description=common.CALCULATOR_DESCRIPTION)
writer = Agent(name="writer", instructions=common.WRITER_SYSTEM, model=model, handoff_description=common.WRITER_DESCRIPTION)

supervisor = Agent(
    name="supervisor", instructions=common.SUPERVISOR_SYSTEM, model=model,
    tools=[calculator.as_tool(tool_name="calculator", tool_description=common.CALCULATOR_DESCRIPTION),
           writer.as_tool(tool_name="writer", tool_description=common.WRITER_DESCRIPTION)])

# the handoff variant: the triage agent does not do the work, it passes the conversation to the right specialist
triage = Agent(name="triage", instructions="Pass each request to the right specialist and do not answer it yourself.",
               model=model, handoffs=[calculator, writer])


def run() -> str:
    return Runner.run_sync(supervisor, common.TASK).final_output


def handoff() -> str:
    result = Runner.run_sync(triage, "What is 17 times 23?")
    return f"{result.final_output}   (answered by: {result.last_agent.name})"


if __name__ == "__main__":
    common.report("OpenAI Agents SDK, agents as tools", run)
    common.report("OpenAI Agents SDK, handoff to a specialist", handoff)
