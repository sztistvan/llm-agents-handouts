"""Module 7 lesson: look at the graph. Mermaid diagrams generated from the real graph of the handouts.

Five pictures: one chunk's extraction; two chunks that merge through an entity they share; the neighbourhood of one
entity; how the graph grows as chunks are added (numbers, because the whole graph cannot be drawn); and what entity
resolution does. Each diagram is printed as a ```mermaid block: paste it into a markdown file (GitHub renders it) or
into https://mermaid.live. No LLM calls if the graph was built before (see m07_graph_build).
Run:  python examples/python/m07_graph_diagrams.py
"""
import re

from graph_store import Graph, mermaid_diagram
from retrieval import chunk_markdown, load_markdown


def show(title: str, text: str) -> None:
    print(f"\n{title}\n```mermaid\n{text}\n```")


if __name__ == "__main__":
    chunks = [c for doc in load_markdown() for c in chunk_markdown(doc)]
    graph = Graph.open()
    graph.sync(chunks)
    graph.stats()
    first = lambda suffix: next(c for c in chunks if c["section"].endswith(suffix))

    one = first("Reflection vs. evaluator-optimizer")
    record = graph.extractions[one["hash"]]
    print(f"1. One chunk ({one['doc_id']} > {one['section'].split(' > ')[-1]}): "
          f"{len(record['entities'])} entities, {len(record['relations'])} relations")
    show("   Its extraction as a graph:", graph.mermaid_chunks([one["hash"]]))

    a, b = first("9. Example: supervisor with workers as tools"), first("6. The agent loop, made reusable")
    shared = sorted(set(graph.chunk_entities[a["hash"]]) & set(graph.chunk_entities[b["hash"]]))
    print(f"\n2. Two chunks from different handouts: {a['doc_id']} > {a['section'].split(' > ')[-1]} (solid) and "
          f"{b['doc_id']} > {b['section'].split(' > ')[-1]} (dashed)")
    print(f"   entities in both, where the two extractions grow together: {', '.join(shared) or 'none'}")
    show("   The merged graph (thick lines: a fact found in both chunks):", graph.mermaid_chunks([a["hash"], b["hash"]]))

    show("\n3. The neighbourhood of one entity, 'supervisor', one hop (the best supported facts):",
         graph.mermaid_neighbourhood("supervisor", hops=1, max_edges=24))

    print("\n4. Growth: the graph as chunks are added in document order (the whole graph is too big to draw)")
    print(f"   {'chunks':>7}{'entities':>10}{'relations':>11}{'relations/entity':>18}{'connected parts':>17}{'largest part':>14}")
    for count in (1, 4, 16, 33, len(chunks)):
        part = Graph(graph.path)
        part.extractions = {c["hash"]: graph.extractions[c["hash"]] for c in chunks[:count] if c["hash"] in graph.extractions}
        stats, sizes = part.stats(), part.components()
        print(f"   {count:>7}{stats['entities']:>10}{stats['relations']:>11}{stats['relations'] / stats['entities']:>18.2f}"
              f"{len(sizes):>17}{sizes[0]:>14}")

    # entity resolution: the pair of variants with the most facts (up to 10) before and after merging
    raw_names: dict[str, tuple[str, str]] = {}
    raw_facts: set[tuple[str, str, str]] = set()
    for chunk_hash in sorted(graph.extractions):
        for entity in graph.extractions[chunk_hash]["entities"]:
            raw_names.setdefault(entity["id"], (entity["name"], entity["type"]))
        for relation in graph.extractions[chunk_hash]["relations"]:
            raw_facts.add((relation["s"], " ".join(re.split(r"[-_\s]+", relation["r"])), relation["t"]))

    def facts_of(*ids):
        return sorted(f for f in raw_facts if f[0] in ids or f[2] in ids)

    candidates = [(len(facts_of(alias, canon)), alias, canon) for alias, canon in graph.merged if len(facts_of(alias, canon)) <= 10]
    _, alias, canon = max(candidates, key=lambda c: (c[0], c[1]))
    before = facts_of(alias, canon)
    ids = sorted({e for f in before for e in (f[0], f[2])} | {alias, canon})
    show(f"\n5. Entity resolution: '{raw_names[alias][0]}' and '{raw_names[canon][0]}' are two nodes before merging",
         mermaid_diagram([(i, raw_names[i][0], raw_names[i][1]) for i in ids], before))
    merged_facts = sorted({(canon if s == alias else s, r, canon if t == alias else t) for s, r, t in before})
    ids_after = sorted({e for f in merged_facts for e in (f[0], f[2])} | {canon})
    show("   ... and one node after merging (the facts of both are now together):",
         mermaid_diagram([(i, raw_names[i][0], raw_names[i][1]) for i in ids_after], merged_facts))
