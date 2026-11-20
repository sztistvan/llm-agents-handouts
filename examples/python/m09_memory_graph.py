"""Module 9 lesson: fact memory with history. Triples that know WHEN they were true.

A text memory (m09_memory_tools) keeps one sentence per fact, and an update overwrites it: "Dana lives in Budapest" becomes
"Dana lives in Vienna" and the past is gone. Here the facts are (subject, relation, object) triples with a validity period
(valid_from, valid_to), extracted from the user's messages by an LLM that may use only a small list of relations (a tiny
ontology, Module 7). A new value of a single-valued relation CLOSES the old fact instead of deleting it. That allows
questions "as of" a date, and a walk over the connections (Module 7's neighbourhood) for "who does Dana work with?".
Three dated sessions, 3 extraction calls and 1 answer. Run:  python examples/python/m09_memory_graph.py
"""
from llm_client import chat
from memory import MEMORY_DIR, RELATIONS, FactStore, extract_triples

SESSIONS = [
    ("2025-03-01", ["I'm Dana. I live in Budapest and work at Contoso as a data engineer. I'm working on project Falcon, and I'm allergic to peanuts."]),
    ("2025-09-15", ["Big news: I moved to Vienna and I now work at Fabrikam. My colleague Marta works at Fabrikam too, and I'm working on project Osprey."]),
    ("2025-11-20", ["I got a dog called Rex, and I was promoted to senior data engineer."]),
]


def line(fact: dict) -> str:
    until = fact["valid_to"] or "now"
    return f"{fact['subject']} --{fact['relation']}--> {fact['object']}  ({fact['valid_from']} to {until})"


if __name__ == "__main__":
    (MEMORY_DIR / "dana.facts.json").unlink(missing_ok=True)
    store = FactStore("dana")
    print("Relations the extractor may use (True: one value at a time):", RELATIONS)

    for date, lines in SESSIONS:
        print(f"\n{date}: {lines[0]}")
        for subject, relation, obj in extract_triples([{"role": "user", "content": t} for t in lines], user_name="Dana"):
            print(f"   {store.set(subject, relation, obj, date):6} {subject} --{relation}--> {obj}")

    print("\nThe history of where Dana lives and works (nothing was deleted):")
    for relation in ("lives_in", "works_at", "job_title"):
        for fact in store.history("Dana", relation):
            print("  ", line(fact))
    print("\nAs of 2025-06-01:", "; ".join(f"{f['relation']} {f['object']}" for f in store.as_of("2025-06-01") if f["subject"] == "Dana"))
    print("Today          :", "; ".join(f"{f['relation']} {f['object']}" for f in store.current() if f["subject"] == "Dana"))

    print("\nWho does Dana work with? The facts within 2 hops of 'Dana':")
    for fact in store.neighbourhood("Dana", hops=2):
        print("  ", line(fact))

    question = "Where did I live and work in June 2025, and where do I live and work now? Answer in two short lines."
    facts = "\n".join(line(f) for f in store.facts if f["subject"] == "Dana" and f["relation"] in ("lives_in", "works_at"))
    reply = chat([{"role": "system", "content": "Answer only from these facts about the user:\n" + facts}, {"role": "user", "content": question}], temperature=0)
    print(f"\nQ: {question}\nA: {(reply.content or '').strip()}")
