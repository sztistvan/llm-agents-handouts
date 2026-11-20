"""Knowledge graph for GraphRAG (Module 7): entities and relations extracted from chunks by an LLM, with provenance.

Shared building block. Layers: llm_client -> retrieval (chunks) -> graph_store (graph, extraction, search) -> m07_* lessons.

The source of truth is one EXTRACTION RECORD per chunk (which entities and relations the LLM found in it). The graph
(nodes, edges, neighbours) is derived from those records, so every node and edge knows which chunks it came from:
  * updating the graph = extract new chunks, drop the records of removed chunks, rebuild (the Module 6 idea)
  * every fact can be cited back to its text
Local search expands from the entities of a question over the graph; global search groups the graph into
communities, summarizes each, and answers broad questions from the summaries.
"""
import copy
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from llm_client import chat, get_config
from retrieval import INDEX_DIR, sha

PROMPT_VERSION = "v1"  # part of the cache: a changed prompt means the extractions are stale
ENTITY_TYPES = {"concept", "pattern", "component", "tool", "file", "parameter", "provider", "other"}
SEP = "\x01"  # joins source, relation and target into one sortable edge key

EXTRACT_SYSTEM = """You extract a knowledge graph from a passage of technical documentation about building LLM agents.
Reply with JSON only: {"entities": [{"name": "...", "type": "..."}], "relations": [{"source": "...", "relation": "...", "target": "..."}]}
Rules:
- Entities are the important concepts, patterns, components, tools, files, parameters or products named in the passage (at most 8). Use short, canonical, lower-case names, singular, without articles (for example "supervisor", "agent loop", "evaluator-optimizer", "run_agent").
- type is one of: concept, pattern, component, tool, file, parameter, provider, other.
- Relations connect two entities from your list with a short lower-case verb phrase (for example "uses", "is a variant of", "contrasts with", "builds on", "part of", "implemented in", "limits", "solves"). At most 8, only relations the passage states or clearly implies.
- If the passage has nothing worth extracting, return empty lists."""


def normalize(name: str) -> str:
    """The identity of an entity: lower case, letters and digits only. 'Evaluator-Optimizer' and 'evaluator optimizer' are one."""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def singular(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


def resolution_key(entity_id: str) -> str:
    """Entity resolution, the simple way: names that differ only by plural forms are one entity ('tool call' = 'tool calls')."""
    return " ".join(singular(w) for w in entity_id.split())


def graph_path() -> Path:
    """One cache file per chat model: a different model extracts different things."""
    return INDEX_DIR / ("graph-" + re.sub(r"[^A-Za-z0-9._-]+", "-", get_config()["model"]) + ".json")


def _json_reply(messages: list[dict], retries: int = 3):
    """Ask for JSON; on a bad reply, say so and ask again (the parse-validate-retry pattern of Module 2)."""
    messages = list(messages)
    for _ in range(retries):
        raw = (chat(messages, temperature=0).content or "").strip()
        match = re.search(r"\{.*\}", raw, re.S)
        try:
            return json.loads(match.group(0))
        except (ValueError, AttributeError):
            messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": "That was not valid JSON. Reply with valid JSON only."}]
    return None


def extract_chunk(chunk: dict) -> dict | None:
    """One LLM call: the entities and relations of one chunk, validated. None if the model never gave usable JSON."""
    data = _json_reply([{"role": "system", "content": EXTRACT_SYSTEM},
                        {"role": "user", "content": f"Section: {chunk['section']}\n\nPassage:\n{chunk['text'][:3000]}"}])
    if not isinstance(data, dict):
        return None
    entities: dict[str, dict] = {}
    for item in data.get("entities") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            entity_id = normalize(item["name"])
            if entity_id and entity_id not in entities and len(entities) < 8:
                kind = item.get("type") if item.get("type") in ENTITY_TYPES else "other"
                entities[entity_id] = {"name": item["name"].strip().lower(), "type": kind}
    relations = []
    for item in data.get("relations") or []:
        if not isinstance(item, dict):
            continue
        source, target, relation = item.get("source"), item.get("target"), item.get("relation")
        if all(isinstance(x, str) for x in (source, target, relation)):
            source_id, target_id, relation = normalize(source), normalize(target), " ".join(relation.lower().split())
            if source_id and target_id and source_id != target_id and relation and len(relations) < 8:
                for entity_id, name in ((source_id, source), (target_id, target)):
                    entities.setdefault(entity_id, {"name": name.strip().lower(), "type": "other"})
                relations.append({"s": source_id, "r": relation, "t": target_id})
    return {"chunk_id": chunk["id"], "doc_id": chunk["doc_id"], "section": chunk["section"],
            "entities": [{"id": k, **v} for k, v in entities.items()], "relations": relations}


def format_facts(facts: list[dict], limit: int = 30) -> str:
    """Graph facts as lines for a prompt: source --relation--> target [chunks it came from]."""
    return "\n".join(f"- {f['source']} --{f['relation']}--> {f['target']}  [{', '.join(f['chunks'][:2])}]" for f in facts[:limit])


class Graph:
    def __init__(self, path: Path | None = None):
        self.path = path or graph_path()
        self.extractions: dict[str, dict] = {}  # chunk hash -> extraction record (the source of truth)
        self.summaries: dict[str, dict] = {}  # community signature -> {title, summary}
        self.chunks: dict[str, dict] = {}  # chunk hash -> chunk (in memory: the texts of the facts)
        self._built = False

    # ------------------------------------------------------------ files

    @classmethod
    def open(cls, path: Path | None = None) -> "Graph":
        graph = cls(path)
        if graph.path.exists():
            data = json.loads(graph.path.read_text(encoding="utf-8"))
            if data.get("prompt_version") == PROMPT_VERSION:  # a changed extraction prompt invalidates the cache
                graph.extractions, graph.summaries = data["extractions"], data.get("summaries", {})
        return graph

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"prompt_version": PROMPT_VERSION, "extractions": self.extractions,
                                         "summaries": self.summaries}), encoding="utf-8")

    def copy(self) -> "Graph":
        """An independent in-memory copy (to try an update without touching the saved graph)."""
        other = Graph(self.path)
        other.extractions, other.summaries = copy.deepcopy(self.extractions), copy.deepcopy(self.summaries)
        other.chunks = dict(self.chunks)
        return other

    # ------------------------------------------------------------ building and updating

    def sync(self, chunks: list[dict], workers: int = 4) -> dict:
        """Bring the graph in line with the chunks: extract the new ones (an LLM call each, a few in parallel),
        drop the records of chunks that are gone, keep the rest. Nothing is saved until save()."""
        self.chunks = {c["hash"]: c for c in chunks}
        removed = [h for h in self.extractions if h not in self.chunks]
        for h in removed:
            del self.extractions[h]
        todo = [c for h, c in self.chunks.items() if h not in self.extractions]
        for h, chunk in self.chunks.items():  # a kept chunk may have moved: refresh where it lives
            if h in self.extractions:
                self.extractions[h].update(chunk_id=chunk["id"], doc_id=chunk["doc_id"], section=chunk["section"])
        started = time.time()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(extract_chunk, todo))
        failed = 0
        for chunk, result in zip(todo, results):
            if result is None:
                failed += 1  # not stored, so the next sync tries again
            else:
                self.extractions[chunk["hash"]] = result
        self._built = False
        return {"chunks": len(chunks), "kept": len(chunks) - len(todo), "extracted": len(todo) - failed,
                "removed": len(removed), "failed": failed, "seconds": time.time() - started}

    def _index(self) -> None:
        """Derive nodes, edges and neighbours from the extraction records (in a fixed order, so it is deterministic)."""
        if self._built:
            return
        # Entity resolution on the derived graph (the records stay untouched): merge variants of one name
        # into the one that occurs in most chunks.
        counts: dict[str, int] = {}
        for chunk_hash in sorted(self.extractions):
            for entity in self.extractions[chunk_hash]["entities"]:
                counts[entity["id"]] = counts.get(entity["id"], 0) + 1
        groups: dict[str, list[str]] = {}
        for entity_id in sorted(counts):
            groups.setdefault(resolution_key(entity_id), []).append(entity_id)
        canon = {}
        for members in groups.values():
            best = min(members, key=lambda i: (-counts[i], len(i), i))
            canon.update({m: best for m in members})
        self.merged = sorted((m, c) for m, c in canon.items() if m != c)  # alias -> the entity it was merged into

        nodes: dict[str, dict] = {}
        edges: dict[str, list[str]] = {}
        names: dict[str, str] = {}
        self.chunk_entities = {}
        for chunk_hash in sorted(self.extractions):
            record = self.extractions[chunk_hash]
            self.chunk_entities[chunk_hash] = list(dict.fromkeys(canon[e["id"]] for e in record["entities"]))
            for entity in record["entities"]:
                cid = canon[entity["id"]]
                node = nodes.setdefault(cid, {"types": {}, "chunks": []})
                if entity["id"] == cid or cid not in names:  # the display name of the canonical spelling wins
                    names[cid] = entity["name"]
                node["types"][entity["type"]] = node["types"].get(entity["type"], 0) + 1
                if chunk_hash not in node["chunks"]:
                    node["chunks"].append(chunk_hash)
            for relation in record["relations"]:
                source, target = canon[relation["s"]], canon[relation["t"]]
                if source != target:
                    label = " ".join(re.split(r"[-_\s]+", relation["r"]))  # 'implemented-in' = 'implemented in'
                    key = SEP.join((source, label, target))
                    if chunk_hash not in edges.setdefault(key, []):
                        edges[key].append(chunk_hash)
        for cid, node in nodes.items():
            node["name"] = names[cid]
        for node in nodes.values():
            node["type"] = min(node["types"], key=lambda t: (-node["types"][t], t))
        self.nodes, self.edges = nodes, edges
        self.adj = {entity_id: [] for entity_id in nodes}
        for key in sorted(edges):
            source, _, target = key.split(SEP)
            self.adj[source].append((target, key))
            self.adj[target].append((source, key))
        self._built = True

    def stats(self) -> dict:
        self._index()
        types: dict[str, int] = {}
        for node in self.nodes.values():
            types[node["type"]] = types.get(node["type"], 0) + 1
        return {"chunks": len(self.extractions), "entities": len(self.nodes), "relations": len(self.edges),
                "merged_variants": len(self.merged), "types": types}

    def top_entities(self, n: int = 10) -> list[tuple[str, int, int]]:
        """(name, number of relations, number of chunks) of the best connected entities."""
        self._index()
        ranked = sorted(self.nodes, key=lambda i: (-len(self.adj[i]), i))[:n]
        return [(self.nodes[i]["name"], len(self.adj[i]), len(self.nodes[i]["chunks"])) for i in ranked]

    def near_duplicates(self, threshold: float = 0.6, limit: int = 10) -> list[tuple[float, str, str]]:
        """Entity pairs whose names share most of their words: candidates for entity resolution (a hard part of GraphRAG)."""
        self._index()
        tokens = {i: {singular(w) for w in i.split()} for i in self.nodes}
        ids, pairs = sorted(self.nodes), []
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                union = tokens[ids[a]] | tokens[ids[b]]
                similarity = len(tokens[ids[a]] & tokens[ids[b]]) / len(union) if union else 0.0
                if similarity >= threshold:
                    pairs.append((similarity, ids[a], ids[b]))
        return sorted(pairs, key=lambda p: (-p[0], p[1], p[2]))[:limit]

    # ------------------------------------------------------------ local search

    def local_context(self, question: str, retriever, k: int = 5, hops: int = 2, max_facts: int = 30,
                      extra_chunks: int = 5, max_seeds: int = 6) -> dict:
        """Local search. The graph is used in two ways:
          1. FACTS: start from the entities of the question and of the top-k retrieved chunks, walk `hops` steps over
             the graph, and keep the best relations (they go into the prompt as compact facts).
          2. CHUNKS: the graph links every entity to the chunks that mention it, so each entity NAMED in the question
             gets its own best chunk (a retrieval filtered by that entity). This is what brings in the second and third
             part of a multi-part question. Remaining room is filled with the chunks the kept facts came from.
        Returns the seeds, the facts and the context chunks (the top-k plus at most `extra_chunks` more)."""
        self._index()
        hits = retriever.search(question, k=k)
        padded = f" {normalize(question)} "
        named = [i for i in sorted(self.nodes) if f" {i} " in padded]  # entities named in the question
        seeds = list(named)
        for _, chunk in hits:  # entities of the retrieved chunks
            for entity_id in self.chunk_entities.get(chunk["hash"], []):
                if entity_id not in seeds:
                    seeds.append(entity_id)
        distance, frontier, found = {s: 0 for s in seeds}, list(seeds), []
        for level in range(hops):
            following = []
            for entity_id in frontier:
                for neighbour, key in self.adj[entity_id]:
                    if key not in found:
                        found.append(key)
                    if neighbour not in distance:
                        distance[neighbour] = level + 1
                        following.append(neighbour)
            frontier = following

        named_set = set(named)

        def rank(key: str):
            """Facts that touch an entity named in the question come first, then the nearest, then the best supported."""
            source, _, target = key.split(SEP)
            touches_question = 0 if source in named_set or target in named_set else 1
            return (touches_question, max(distance[source], distance[target]), -len(self.edges[key]), key)

        kept = sorted(found, key=rank)[:max_facts]
        facts = []
        for key in kept:
            source, relation, target = key.split(SEP)
            ids = [self.extractions[h]["chunk_id"] for h in self.edges[key]]
            facts.append({"source": self.nodes[source]["name"], "relation": relation, "target": self.nodes[target]["name"], "chunks": ids})
        have = {chunk["hash"] for _, chunk in hits}
        extra: list[dict] = []
        for entity_id in sorted(named, key=lambda i: (len(self.nodes[i]["chunks"]), i))[:max_seeds]:  # specific entities first
            if len(extra) >= extra_chunks:
                break
            allowed = set(self.nodes[entity_id]["chunks"])
            for _, chunk in retriever.search(question, k=4, where=lambda c, a=allowed: c["hash"] in a):
                if chunk["hash"] not in have:
                    extra.append(chunk)
                    have.add(chunk["hash"])
                    break
        support: dict[str, int] = {}
        for key in kept:
            for chunk_hash in self.edges[key]:
                if chunk_hash not in have:
                    support[chunk_hash] = support.get(chunk_hash, 0) + 1
        for chunk_hash in sorted(support, key=lambda h: (-support[h], h)):
            if len(extra) >= extra_chunks:
                break
            if chunk_hash in self.chunks:
                extra.append(self.chunks[chunk_hash])
        return {"seeds": [self.nodes[s]["name"] for s in seeds], "facts": facts, "chunks": [c for _, c in hits] + extra}

    # ------------------------------------------------------------ global search

    def communities(self, min_size: int = 3, rounds: int = 10) -> list[list[str]]:
        """Group the graph by label propagation: every entity repeatedly takes the label most common among its
        neighbours (ties: the smallest), in a fixed order, so the result is the same on every run. A simple
        stand-in for the Leiden algorithm that production GraphRAG systems use."""
        self._index()
        labels = {i: i for i in self.nodes}
        order = sorted(self.nodes)
        for _ in range(rounds):
            changed = False
            for entity_id in order:
                counts: dict[str, int] = {}
                for neighbour, _ in self.adj[entity_id]:
                    counts[labels[neighbour]] = counts.get(labels[neighbour], 0) + 1
                if counts:
                    best = min(counts, key=lambda label: (-counts[label], label))
                    if best != labels[entity_id]:
                        labels[entity_id], changed = best, True
            if not changed:
                break
        groups: dict[str, list[str]] = {}
        for entity_id in order:
            groups.setdefault(labels[entity_id], []).append(entity_id)
        return sorted((g for g in groups.values() if len(g) >= min_size), key=lambda g: (-len(g), g[0]))

    def member_names(self, members: list[str], n: int = 5) -> list[str]:
        """The best connected entities of a community, by name."""
        self._index()
        return [self.nodes[i]["name"] for i in sorted(members, key=lambda i: (-len(self.adj[i]), i))[:n]]

    def community_facts(self, members: list[str], limit: int = 30) -> list[str]:
        inside = set(members)
        keys = [k for k in self.edges if k.split(SEP)[0] in inside and k.split(SEP)[2] in inside]
        keys = sorted(keys, key=lambda k: (-len(self.edges[k]), k))[:limit]
        return [f"{self.nodes[k.split(SEP)[0]]['name']} --{k.split(SEP)[1]}--> {self.nodes[k.split(SEP)[2]]['name']}" for k in keys]

    def summarize(self, members: list[str]) -> dict | None:
        """A title and a short summary of one community, written by the LLM from its entities and relations.
        Cached by a signature of the content, so only changed communities are summarized again."""
        facts = self.community_facts(members)
        signature = sha("|".join(sorted(members)) + "#" + "|".join(facts))
        if signature not in self.summaries:
            names = [self.nodes[i]["name"] for i in sorted(members, key=lambda i: (-len(self.adj[i]), i))[:15]]
            data = _json_reply([{"role": "user", "content":
                                 "These entities and relations come from documentation about building LLM agents.\n"
                                 f"Entities: {', '.join(names)}\nRelations:\n" + "\n".join(facts) +
                                 '\n\nName the theme these belong to and summarize it in 2 or 3 sentences. '
                                 'Reply with JSON only: {"title": "...", "summary": "..."}'}])
            if not isinstance(data, dict) or not isinstance(data.get("summary"), str):
                return None
            self.summaries[signature] = {"title": str(data.get("title", "")).strip(), "summary": data["summary"].strip()}
        return self.summaries[signature]
