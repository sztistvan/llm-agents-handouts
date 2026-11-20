"""Module 9 lesson: short-term memory. A long conversation does not fit; what do you keep?

A scripted 10-turn conversation about a trip is built WITHOUT calling the model (canned answers), so the lesson spends
only a handful of calls. The first message plants facts (a name, an allergy, a group size). Then three strategies face
the same final question: keep everything, keep the newest turns (trim), summarize the old ones (compact). Part 3 shows
what happens when a cut separates a tool call from its result; part 4 saves a conversation and continues it later.
Run:  python examples/python/m09_short_term.py
"""
from agent import Tool, run_agent
from llm_client import chat
from memory import MEMORY_DIR, compact, load_messages, save_messages, tokens, trim

BUDGET = 450  # tokens we allow ourselves for the history (tiny, so that the effect shows on a short conversation)
SYSTEM = "You are a travel planning assistant. Answer briefly."
PAIRS = [
    ("Hi, I'm Dana. I'm planning a team trip to Lisbon in May for 6 people, and I'm allergic to peanuts.",
     "Nice to meet you, Dana. Lisbon in May is lovely: warm, not yet crowded. A group of six fits most restaurants if you book ahead. I'll keep your peanut allergy in mind."),
    ("Which neighbourhood should we stay in?",
     "Baixa and Chiado are central and walkable, with metro access. Alfama is atmospheric but hilly, with narrow streets that are tiring with luggage. For six people, an apartment hotel in Baixa is a good compromise between price and location."),
    ("How do we get from the airport to Baixa?",
     "The red metro line runs from the airport to Saldanha, where you change to the yellow line towards Baixa-Chiado: about 30 minutes. A taxi or ride-hailing car takes 20 minutes and costs around 20 euros, which is cheaper than six metro tickets only if you split it."),
    ("What about getting around inside the city?",
     "Walk where you can, and use the metro for the longer hops. The famous tram 28 is crowded with tourists, so ride it early in the morning or choose the less busy tram 12. A 24-hour card covers metro, trams and buses."),
    ("Suggest a day trip.",
     "Sintra is the classic one: palaces and gardens, 40 minutes by train from Rossio. Start early, because Pena Palace queues build up by ten. Cascais is the relaxed alternative if the group wants a beach and seafood lunch."),
    ("What should we eat?",
     "Pastel de nata for breakfast, grilled sardines in summer, bacalhau in all its forms, and caldo verde as a starter. Ginjinha is the local cherry liqueur, served in tiny cups. Many Portuguese desserts contain almonds or other nuts, so ask."),
    ("Any tips for the evenings?",
     "Bairro Alto is lively but loud; Alfama has fado houses where dinner and music come together, and they need a reservation. Miradouros, the viewpoints, are good for a drink at sunset and cost nothing."),
    ("Is Lisbon safe?",
     "Yes, generally. Pickpockets work the trams and the busy squares, so keep bags closed in front of you. Taxis are safe if you use the meter or an app; agree on the price before you leave the airport."),
    ("Should we rent a car?",
     "Not for the city: parking is hard and the old streets are narrow. For Sintra, Cascais or the coast, the train is easier. Rent a car only if you plan to leave the Lisbon region for several days."),
    ("What do we pack?",
     "Layers: the evenings are cool in May. Comfortable shoes with grip, because the cobblestones are slippery, a light rain jacket, sun protection and a reusable bottle. Bring a plug adapter if your devices have a different plug."),
]
FINAL = "Before I send the restaurant bookings: which allergy must I mention, and for how many people?"


def history() -> list[dict]:
    messages = [{"role": "system", "content": SYSTEM}]
    for user, assistant in PAIRS:
        messages += [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]
    return messages


def answer(messages: list[dict]) -> str:
    return (chat(messages + [{"role": "user", "content": FINAL}], temperature=0).content or "").strip().replace("\n", " ")


def add(a: float, b: float) -> str:
    return str(a + b)


if __name__ == "__main__":
    full = history()
    trimmed = trim(full, BUDGET)
    compacted = compact(full, BUDGET)

    print(f"1. The conversation: {len(PAIRS)} turns, about {tokens(full)} tokens; budget {BUDGET}")
    print("\n2. The same final question after each strategy:", f'"{FINAL}"')
    for name, messages in [("keep everything", full), ("trim (newest turns)", trimmed), ("compact (summary + 2 newest)", compacted)]:
        kept = sum(1 for m in messages if m["role"] == "user")
        print(f"\n   {name}: {kept} user turns kept, {tokens(messages)} tokens")
        print(f"   -> {answer(messages)[:260]}")
    print("\n   The summary the compacted conversation carries:")
    print("   " + compacted[0]["content"].split("\n[Summary of the earlier conversation]\n")[1].replace("\n", " "))

    print("\n3. A cut in the wrong place: the history starts with a tool result whose tool call was cut away")
    call = {"id": "call_1", "type": "function", "function": {"name": "add", "arguments": '{"a": 2, "b": 3}'}}
    whole = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": "What is 2 + 3?"},
             {"role": "assistant", "content": None, "tool_calls": [call]}, {"role": "tool", "tool_call_id": "call_1", "content": "5"},
             {"role": "assistant", "content": "5"}, {"role": "user", "content": "And times 2?"}]
    broken = [whole[0]] + whole[3:]
    try:
        chat(broken)
        print("   this provider accepted it (others reject it)")
    except Exception as exc:
        print(f"   rejected: {type(exc).__name__}: {str(exc)[:200]}")
    print(f"   `trim` cuts only before a user message, so a tool call and its result stay together or go together: "
          f"{[m['role'] for m in trim(whole, 40)]} for a tiny budget, {[m['role'] for m in trim(whole, 400)]} for a large one")

    print("\n4. Persisting a conversation: save the list, load it in a later run, continue")
    tools = [Tool(add, "Add two numbers.", {"type": "object", "properties": {"a": {"type": "number"}, "b": {"type": "number"}}, "required": ["a", "b"]})]
    session = []
    print("   run 1:", run_agent("My favorite number is 7. Add 3 to it.", tools, messages=session))
    path = MEMORY_DIR / "chat_demo.json"
    save_messages(path, session)  # the assistant's messages are SDK objects: save_messages converts them (as_dict)
    print(f"   saved {len(session)} messages to {path.relative_to(path.parents[2])}")
    session = load_messages(path)  # ... a later run starts here
    print("   run 2:", run_agent("What was my favorite number?", tools, messages=session))
