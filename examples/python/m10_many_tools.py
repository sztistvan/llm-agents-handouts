"""Module 10 lesson: what happens when an agent has MANY tools, and how to give it fewer.

examples/tools_catalog.json describes 36 office tools (calendar, e-mail, files, tasks, CRM, ...) and 12 questions with the
tool that should be called first. Every question is sent to the model once with the tool definitions and we look at the
FIRST tool call (nothing is executed). Strategy A sends all 36 definitions; strategy B embeds the descriptions (Module 5),
retrieves the 5 closest tools for the question and sends only those. Part 3 measures how often the right tool is among the
k closest, without any LLM call; part 4 triples the catalog (the same tools from three "servers"). Needs an embedding model. 36 chat calls. Run:  python examples/python/m10_many_tools.py
"""
import json
import math
import time

from llm_client import chat, embed
from retrieval import ROOT

SYSTEM = "You are an office assistant. Use the tools to help the user. Call the single most appropriate tool first."
K = 5


def schemas(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": t} for t in tools]


def first_tool(question: str, tools: list[dict]) -> tuple[str | None, float]:
    """The name of the first tool the model calls (None if it answers without a tool), and the seconds it took."""
    started = time.time()
    msg = chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}], tools=schemas(tools), temperature=0)
    return (msg.tool_calls[0].function.name if msg.tool_calls else None), time.time() - started


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


if __name__ == "__main__":
    catalog = json.loads((ROOT / "examples" / "tools_catalog.json").read_text(encoding="utf-8"))
    tools, questions = catalog["tools"], catalog["questions"]
    by_name = {t["name"]: t for t in tools}
    size = lambda subset: len(json.dumps(schemas(subset), separators=(",", ":"))) // 4

    print(f"1. {len(tools)} tools; their definitions alone are about {size(tools)} tokens, sent with EVERY request")
    print(f"   {K} tools would be about {size(tools[:K])} tokens")

    vectors = embed([f"{t['name'].replace('_', ' ')}: {t['description']}" for t in tools])
    query_vectors = embed([q["question"] for q in questions], kind="query")

    def closest(i: int, k: int) -> list[str]:
        ranked = sorted(range(len(tools)), key=lambda j: -cosine(query_vectors[i], vectors[j]))
        return [tools[j]["name"] for j in ranked[:k]]

    print(f"\n2. The first tool call: all {len(tools)} tools (A) against the {K} closest by embedding (B)")
    print(f"   {'question':58}{'expected':20}{'A: all':22}{'B: top-' + str(K)}")
    score = {"A": 0, "B": 0}
    seconds = {"A": 0.0, "B": 0.0}
    for i, item in enumerate(questions):
        a, a_time = first_tool(item["question"], tools)
        shortlist = closest(i, K)
        b, b_time = first_tool(item["question"], [by_name[n] for n in shortlist])
        score["A"] += a == item["expected"]
        score["B"] += b == item["expected"]
        seconds["A"] += a_time
        seconds["B"] += b_time
        mark = lambda got: str(got) + ("" if got == item["expected"] else "  <-- wrong")
        print(f"   {item['question'][:56]:58}{item['expected']:20}{mark(a):22}{mark(b)}")
    n = len(questions)
    print(f"\n   correct first tool: A {score['A']}/{n}, B {score['B']}/{n};  mean seconds per call: A {seconds['A'] / n:.2f}, B {seconds['B'] / n:.2f}")
    print(f"   tool tokens per request: A {size(tools)}, B about {size([by_name[n] for n in closest(0, K)])}")

    print("\n3. Retrieval alone: how often is the right tool among the k closest? (no LLM call)")
    for k in (1, 3, 5, 8):
        hits = sum(item["expected"] in closest(i, k) for i, item in enumerate(questions))
        print(f"   top-{k}: {hits}/{n}")
    misses = [(item["question"], closest(i, K)) for i, item in enumerate(questions) if item["expected"] not in closest(i, K)]
    for question, shortlist in misses:
        print(f"   missed at top-{K}: {question!r} -> {shortlist}")

    # Several servers often expose the same kind of tool: copy the whole catalog for two accounts (108 tools)
    many = tools + [{**t, "name": f"{account}_{t['name']}", "description": f"{t['description']} ({account} account)"} for account in ("work", "personal") for t in tools]
    print(f"\n4. Three copies of the catalog, as if three servers (own, work account, personal account) exposed the same tools: {len(many)} tools, about {size(many)} tokens")
    strip = lambda name: name.split("_", 1)[1] if name and name.split("_", 1)[0] in ("work", "personal") else name
    right, prefixed, seconds_many = 0, 0, 0.0
    for item in questions:
        got, took = first_tool(item["question"], many)
        right += strip(got) == item["expected"]
        prefixed += bool(got) and got != strip(got)
        seconds_many += took
    print(f"   right tool (ignoring the account): {right}/{n}; one of the account copies chosen: {prefixed}/{n} (nothing told the model which account to use); mean seconds per call {seconds_many / n:.2f}")
