"""Baseline (Module 4): the supervisor with the course's own 30-line agent loop, no framework.

m04_supervisor.py builds two worker "agents" as tools and hands them to a supervisor; run_agent (agent.py) is the loop of
Module 2. Nothing to install beyond the `openai` package. Run:  python examples/frameworks/f00_plain.py
"""
import common
from agent import run_agent
from m04_supervisor import SUPERVISOR, calculator, writer


def run() -> str:
    return run_agent(common.TASK, [calculator, writer], system=SUPERVISOR, max_steps=8)


if __name__ == "__main__":
    common.report("Plain Python (agent.py)", run)
