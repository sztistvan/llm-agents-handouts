"""CrewAI: the same supervisor as a "crew" with roles. CODE TO READ, NOT RUN.

This file is NOT part of the measured comparison: crewai is not installed by examples/frameworks/requirements.txt (it brings a
large dependency tree) and this code was not executed for the tutorial. It follows the examples of the CrewAI documentation
of 2026-11-20 (version 1.15.x); check the current documentation before you use it. Read it to see the model of the framework:

  Agent  = a ROLE: role, goal and backstory are the prompt, plus tools and a model
  Task   = a unit of work: a description and the expected output (required)
  Crew   = agents + tasks + a PROCESS: "sequential" (tasks in order) or "hierarchical" (a manager agent plans and delegates)

To try it:  pip install crewai   and set the environment variables of your Azure OpenAI deployment
            (AZURE_API_KEY, AZURE_ENDPOINT, AZURE_API_VERSION); CREWAI_DISABLE_TELEMETRY=true switches the anonymous telemetry off.
"""
from crewai import LLM, Agent, Crew, Process, Task
from crewai.tools import tool

llm = LLM(model="azure/YOUR-DEPLOYMENT-NAME")   # "provider/model"; for Azure the deployment name; other providers need an extra


@tool("add")
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


@tool("multiply")
def multiply(a: float, b: float) -> float:
    """Multiply two numbers."""
    return a * b


calculator = Agent(
    role="Calculator",
    goal="Do arithmetic exactly, always with the tools",
    backstory="You are a calculator. Always use the tools for arithmetic and reply with the number only.",
    tools=[add, multiply], llm=llm, allow_delegation=False)

writer = Agent(
    role="Writer",
    goal="Write short, friendly text from the facts you are given",
    backstory="You write short, friendly text. Use only the facts you are given.",
    llm=llm, allow_delegation=False)

# 1. HIERARCHICAL: a manager (here the llm acts as manager) splits the task and delegates to the agents by role.
announce = Task(
    description="A team has {people} people and each gets {coffees} coffees. Announce the total coffees.",
    expected_output="One short, friendly sentence that states the total number of coffees.")
crew = Crew(agents=[calculator, writer], tasks=[announce], process=Process.hierarchical, manager_llm=llm)
result = crew.kickoff(inputs={"people": 4, "coffees": 3})
print(result.raw)

# 2. SEQUENTIAL: no manager; the tasks run in order and the output of one is the context of the next.
count = Task(description="Calculate how many coffees {people} people need if each gets {coffees}.",
             expected_output="The number only.", agent=calculator)
write = Task(description="Announce the number of coffees in one short, friendly sentence.",
             expected_output="One short sentence.", agent=writer, context=[count])
print(Crew(agents=[calculator, writer], tasks=[count, write], process=Process.sequential).kickoff(
    inputs={"people": 4, "coffees": 3}).raw)
