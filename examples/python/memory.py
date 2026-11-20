"""Memory for agents (Module 9): short-term (trim, summarize), long-term (remember / recall) and fact memory.

Shared building block. Layers: llm_client -> agent (the loop) -> memory -> m09_* lessons. Three kinds of memory:

  SHORT-TERM  the message list of one conversation. `trim` keeps the newest turns, `compact` replaces the old ones
              by a summary. A TURN starts at a user message and holds everything up to the next one, so an
              assistant message with tool calls is never separated from the results of those calls.
  LONG-TERM   `MemoryStore`: short, self-contained statements ("Dana lives in Vienna") with an embedding, one JSON
              file per user. `remember` RECONCILES a new statement with the neighbours already stored (add, update
              or ignore); `search` finds memories by meaning (cosine similarity, as in Module 5).
  FACTS       `FactStore`: (subject, relation, object) triples with the period in which they were true, so a change
              closes the old fact instead of deleting it. The relations are a tiny ontology (Module 7, section 3).

Memories are only ever extracted from what the USER said (`extract_facts`): tool results and web pages are not a
source of memories (see section 5 of docs/09-memory.md).
"""
import json
import math
import re
import time
from pathlib import Path

from graph_store import json_reply  # the parse-validate-retry helper of Module 7
from llm_client import chat, embed, embed_model

ROOT = Path(__file__).resolve().parents[2]
MEMORY_DIR = ROOT / "examples" / ".memory"  # git-ignored: memories are personal data
SUMMARY_MARK = "\n\n[Summary of the earlier conversation]\n"


# ------------------------------------------------------------------------------------------ short-term memory

def as_dict(msg) -> dict:
    """A plain, JSON-safe message. The SDK returns objects for the assistant's messages: convert them with this."""
    d = msg if isinstance(msg, dict) else msg.model_dump(exclude_none=True)
    return {k: d[k] for k in ("role", "content", "tool_calls", "tool_call_id") if d.get(k) not in (None, [])}


def tokens(messages: list) -> int:
    """A rough estimate: 4 characters per token plus a few per message. Use a real tokenizer (tiktoken for OpenAI models) when it matters."""
    return sum(len(json.dumps(as_dict(m), ensure_ascii=False, separators=(",", ":"))) // 4 + 4 for m in messages)


def split_turns(messages: list) -> tuple[list, list[list]]:
    """(the leading system message, [turn, ...]). A turn starts at a user message and ends before the next one."""
    head = [m for m in messages[:1] if as_dict(m)["role"] == "system"]
    turns: list[list] = []
    for msg in messages[len(head):]:
        if as_dict(msg)["role"] == "user" or not turns:
            turns.append([])
        turns[-1].append(msg)
    return head, turns


def trim(messages: list, budget: int) -> list:
    """Keep the system message and as many of the newest turns as fit into `budget` tokens (at least the last one)."""
    head, turns = split_turns(messages)
    kept: list[list] = []
    for turn in reversed(turns):
        if kept and tokens(head + [m for t in [turn] + kept for m in t]) > budget:
            break
        kept.insert(0, turn)
    return head + [m for turn in kept for m in turn]


def _transcript(messages: list) -> str:
    lines = []
    for msg in map(as_dict, messages):
        if msg["role"] == "tool":
            lines.append(f"tool result: {msg['content'][:300]}")
        elif msg.get("tool_calls"):
            lines.append("assistant calls: " + ", ".join(c["function"]["name"] + c["function"]["arguments"] for c in msg["tool_calls"]))
        elif msg["role"] != "system":
            lines.append(f"{msg['role']}: {msg.get('content', '')}")
    return "\n".join(lines)


def summarize(messages: list, previous: str = "") -> str:
    """One LLM call: a summary of the old turns that keeps what the assistant will need later."""
    prompt = ("Summarize this conversation for the assistant's own later use, in at most 120 words. Keep names, numbers, dates, "
              "decisions, preferences, constraints, open tasks and exact identifiers. Leave out pleasantries and details that are repeated.\n\n")
    if previous:
        prompt += f"Summary so far:\n{previous}\n\nNew messages:\n"
    return (chat([{"role": "user", "content": prompt + _transcript(messages)}], temperature=0).content or "").strip()


def compact(messages: list, budget: int, keep_turns: int = 2) -> list:
    """If the conversation is over `budget` tokens, replace everything but the last `keep_turns` turns by a summary.

    The summary is appended to the system message (some models accept only one system message, and only first).
    Compacting again summarizes the previous summary together with the newly old turns: a rolling summary.
    """
    if tokens(messages) <= budget:
        return list(messages)
    head, turns = split_turns(messages)
    if not head or len(turns) <= keep_turns:
        return list(messages)
    system = as_dict(head[0])["content"]
    base, _, previous = system.partition(SUMMARY_MARK)
    old, recent = turns[:-keep_turns], turns[-keep_turns:]
    summary = summarize([m for turn in old for m in turn], previous)
    return [{"role": "system", "content": base + SUMMARY_MARK + summary}] + [m for turn in recent for m in turn]


def save_messages(path: Path, messages: list) -> None:
    """Persist a conversation as JSON (the SDK objects of the assistant are converted with `as_dict`)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([as_dict(m) for m in messages], indent=2, ensure_ascii=False), encoding="utf-8")


def load_messages(path: Path) -> list:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


# ------------------------------------------------------------------------------------------- long-term memory

EXTRACT_FACTS = """You read a conversation and list the durable facts about the USER that an assistant should remember in future sessions:
identity, preferences, constraints, ongoing projects, important dates. Ignore small talk and one-off requests.
Reply with JSON only: {"facts": ["Dana prefers short answers", "..."]}. Each fact is one short, self-contained sentence in the third person."""

RECONCILE = """You maintain a list of memories about a user. A new fact arrived. Compare it with the existing memories and reply with JSON only:
{"action": "ADD" | "UPDATE" | "NOOP", "id": "<id of the memory to change, for UPDATE>", "text": "<the memory text to store, for ADD or UPDATE>"}
UPDATE when the new fact replaces or refines an existing memory (a new city replaces the old one); NOOP when it is already known;
ADD when it is new. A stored memory may contain several facts: when the new fact replaces only one of them, UPDATE with the corrected
full text and keep what is still true. Write memories as the current state ("Dana lives in Vienna"), not as an event ("moved last month")
and without relative dates. A memory is one short, self-contained sentence in the third person."""


def extract_facts(messages: list, only_user: bool = True) -> list[str]:
    """One LLM call: durable facts from a conversation. By default ONLY from the user's own messages."""
    wanted = [m for m in map(as_dict, messages) if m["role"] == "user"] if only_user else messages
    data = json_reply([{"role": "system", "content": EXTRACT_FACTS}, {"role": "user", "content": _transcript(wanted)}])
    facts = data.get("facts") if isinstance(data, dict) else None
    return [f.strip() for f in facts or [] if isinstance(f, str) and f.strip()]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b)) / ((math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))) or 1.0)


class MemoryStore:
    """Long-term memories of ONE user in one JSON file: examples/.memory/<user>.json (the user id is the isolation boundary)."""

    def __init__(self, user: str, directory: Path = MEMORY_DIR):
        self.path = directory / (re.sub(r"[^A-Za-z0-9._-]+", "_", user) + ".json")
        data = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.model = data.get("embed_model") or embed_model()
        if self.model != embed_model():
            raise RuntimeError(f"{self.path.name} was embedded with '{self.model}', not '{embed_model()}': re-embed it (Module 6, model changes).")
        self.items: list[dict] = data.get("memories", [])
        self.next_id: int = data.get("next_id", 1)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"embed_model": self.model, "next_id": self.next_id, "memories": self.items}, ensure_ascii=False), encoding="utf-8")

    def search(self, query: str, k: int = 4, min_score: float = 0.2) -> list[tuple[float, dict]]:
        """The memories closest in meaning to `query` (cosine similarity), best first; weak matches are dropped."""
        if not self.items:
            return []
        vector = embed([query], kind="query")[0]
        scored = sorted(((_cosine(vector, m["vector"]), m) for m in self.items), key=lambda pair: -pair[0])
        return [(score, m) for score, m in scored[:k] if score >= min_score]

    def add(self, text: str, source: str = "") -> dict:
        item = {"id": f"m{self.next_id}", "text": text, "created": time.strftime("%Y-%m-%d"), "updated": time.strftime("%Y-%m-%d"),
                "source": source, "vector": embed([text])[0]}
        self.next_id += 1
        self.items.append(item)
        self.save()
        return item

    def update(self, memory_id: str, text: str) -> dict | None:
        for item in self.items:
            if item["id"] == memory_id:
                item.update(text=text, updated=time.strftime("%Y-%m-%d"), vector=embed([text])[0])
                self.save()
                return item
        return None

    def delete(self, memory_id: str) -> bool:
        before = len(self.items)
        self.items = [m for m in self.items if m["id"] != memory_id]
        self.save()
        return len(self.items) < before

    def remember(self, fact: str, source: str = "") -> tuple[str, dict | None]:
        """Reconcile a new fact with the stored neighbours: returns ("ADD" | "UPDATE" | "NOOP", the memory)."""
        neighbours = self.search(fact, k=3, min_score=0.2)
        if not neighbours:
            return "ADD", self.add(fact, source)
        listing = "\n".join(f"{m['id']}: {m['text']}" for _, m in neighbours)
        data = json_reply([{"role": "system", "content": RECONCILE},
                           {"role": "user", "content": f"Existing memories:\n{listing}\n\nNew fact: {fact}"}])
        data = data if isinstance(data, dict) else {}
        action, text = str(data.get("action", "ADD")).upper(), str(data.get("text") or fact).strip()
        if action == "NOOP":
            return "NOOP", next((m for _, m in neighbours if m["id"] == data.get("id")), None)
        if action == "UPDATE":
            changed = self.update(str(data.get("id")), text)
            if changed:
                return "UPDATE", changed
        return "ADD", self.add(text, source)  # also the fallback when the model's answer cannot be applied

    def context_block(self, query: str, k: int = 4, everything: bool = False) -> str:
        """What to put into the system prompt of a new session: the memories relevant to `query`, or ALL of them
        (a small store fits into the prompt, and standing preferences are not "relevant" to any particular question)."""
        texts = [m["text"] for m in self.items] if everything else [m["text"] for _, m in self.search(query, k=k)]
        return "What you know about the user from earlier sessions:\n" + "\n".join(f"- {t}" for t in texts) if texts else ""


# ----------------------------------------------------------------------------------- fact memory with history

RELATIONS = {"lives_in": True, "works_at": True, "job_title": True,                    # True: one value at a time
             "works_on": False, "likes": False, "allergic_to": False, "has_pet": False, "knows": False}
EXTRACT_TRIPLES = """You read what a user said and extract facts about them as triples. Reply with JSON only:
{"facts": [{"subject": "...", "relation": "...", "object": "..."}]}
relation is one of: %s. The subject of facts about the speaker is "%s"; facts about another person use that person's name as subject.
Objects are short and lower-case, except names. Only facts the user states; nothing else."""


def extract_triples(messages: list, user_name: str) -> list[tuple[str, str, str]]:
    """One LLM call: (subject, relation, object) triples from the user's messages; relations outside RELATIONS are dropped."""
    system = EXTRACT_TRIPLES % (", ".join(RELATIONS), user_name)
    data = json_reply([{"role": "system", "content": system}, {"role": "user", "content": _transcript([m for m in map(as_dict, messages) if m["role"] == "user"])}])
    triples = []
    for item in (data.get("facts") if isinstance(data, dict) else None) or []:
        if isinstance(item, dict) and all(isinstance(item.get(k), str) and item[k].strip() for k in ("subject", "relation", "object")) \
                and item["relation"] in RELATIONS:
            triples.append((item["subject"].strip(), item["relation"], item["object"].strip()))
    return triples


class FactStore:
    """Triples with validity periods: a new value of a single-valued relation CLOSES the old fact (valid_to) instead of deleting it."""

    def __init__(self, user: str, directory: Path = MEMORY_DIR):
        self.path = directory / (re.sub(r"[^A-Za-z0-9._-]+", "_", user) + ".facts.json")
        self.facts: list[dict] = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.facts, indent=1, ensure_ascii=False), encoding="utf-8")

    def set(self, subject: str, relation: str, obj: str, when: str) -> str:
        """Record a fact that became true on `when` (an ISO date). Returns "ADD", "CHANGE" (an old value was closed) or "NOOP"."""
        is_open = lambda f: f["subject"].lower() == subject.lower() and f["relation"] == relation and f["valid_to"] is None
        current = [f for f in self.facts if is_open(f)]
        if any(f["object"].lower() == obj.lower() for f in current):
            return "NOOP"
        if RELATIONS[relation]:
            for fact in current:
                fact["valid_to"] = when
        self.facts.append({"subject": subject, "relation": relation, "object": obj, "valid_from": when, "valid_to": None})
        self.save()
        return "CHANGE" if RELATIONS[relation] and current else "ADD"

    def as_of(self, date: str) -> list[dict]:
        """The facts that were true on `date` (ISO dates compare as strings)."""
        return [f for f in self.facts if f["valid_from"] <= date and (f["valid_to"] is None or date < f["valid_to"])]

    def current(self) -> list[dict]:
        return [f for f in self.facts if f["valid_to"] is None]

    def history(self, subject: str, relation: str) -> list[dict]:
        return [f for f in self.facts if f["subject"].lower() == subject.lower() and f["relation"] == relation]

    def neighbourhood(self, entity: str, hops: int = 2) -> list[dict]:
        """Current facts within `hops` steps of an entity (edges are followed in both directions, as in Module 7)."""
        seen, frontier, found = {entity.lower()}, {entity.lower()}, []
        for _ in range(hops):
            nxt = set()
            for fact in self.current():
                a, b = fact["subject"].lower(), fact["object"].lower()
                if (a in frontier or b in frontier) and fact not in found:
                    found.append(fact)
                    nxt |= {a, b} - seen
            seen |= nxt
            frontier = nxt
        return found
