"""Module 9 lesson: long-term memory as tools. The agent itself decides what to remember, recall and forget.

Four SESSIONS with the same user: every session starts with an empty message list, so anything the agent knows beyond
the current conversation comes from the memory store (examples/.memory/demo.json, deleted at the start so that the lesson
is repeatable). `remember` reconciles: a new city UPDATES the old one instead of adding a contradiction. Run:
    python examples/python/m09_memory_tools.py
"""
from agent import Tool, run_agent
from memory import MemoryStore

STORE: MemoryStore | None = None  # opened in __main__; the tools below use it

SYSTEM = ("You are a personal assistant with long-term memory that lasts across sessions. "
          "When the user tells you something worth keeping (identity, preferences, constraints, plans), call remember once per fact, with ONE short fact in the third person, stated as a current state (not an event). "
          "Before you answer anything personal (suggestions, planning), call recall first. "
          "When the user asks you to forget something, call recall to find the memory and then forget with its id. "
          "Do not store small talk or one-off requests.")


def remember(fact: str) -> str:
    action, item = STORE.remember(fact, source="chat")
    print(f"      [remember] {fact!r} -> {action}" + (f" {item['id']}: {item['text']!r}" if item else ""))
    return f"{action}: {item['text']}" if item else action


def recall(query: str) -> str:
    hits = STORE.search(query, k=4)
    print(f"      [recall] {query!r} -> {len(hits)} memories")
    return "\n".join(f"[{m['id']}] {m['text']}" for _, m in hits) or "No memories found."


def forget(memory_id: str) -> str:
    deleted = STORE.delete(memory_id)
    print(f"      [forget] {memory_id} -> {'deleted' if deleted else 'not found'}")
    return "Forgotten." if deleted else "Not found."


TOOLS = [
    Tool(remember, "Store one durable fact about the user. Reconciles with what is already known (an update replaces an old fact).",
         {"type": "object", "properties": {"fact": {"type": "string", "description": "One short sentence in the third person, e.g. 'Dana lives in Vienna'"}}, "required": ["fact"]}),
    Tool(recall, "Search the long-term memory about the user by meaning. Returns memories with their ids.",
         {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}),
    Tool(forget, "Delete one memory by its id (get the id from recall).",
         {"type": "object", "properties": {"memory_id": {"type": "string"}}, "required": ["memory_id"]}),
]

SESSIONS = [
    ("Session 1: the user introduces themself", ["Hi! I'm Dana, I live in Budapest and I'm vegetarian.", "I'm preparing a talk about RAG for September."]),
    ("Session 2: a new conversation, nothing in the message list", ["Suggest a dinner idea for tonight."]),
    ("Session 3: something changes", ["By the way, I moved to Vienna last month."]),
    ("Session 4: the user asks to forget", ["Please forget what you know about my diet."]),
]


def show_store() -> None:
    print("   memory file now:", "; ".join(f"{m['id']}={m['text']!r}" for m in STORE.items) or "(empty)")


if __name__ == "__main__":
    MemoryStore("demo").path.unlink(missing_ok=True)
    STORE = MemoryStore("demo")
    for title, turns in SESSIONS:
        print(f"\n{title}")
        messages: list = []  # a NEW conversation each time: only the memory store connects the sessions
        for turn in turns:
            print(f"   user: {turn}")
            print("   agent:", run_agent(turn, TOOLS, system=SYSTEM, max_steps=6, messages=messages).replace("\n", " ")[:300])
        show_store()
