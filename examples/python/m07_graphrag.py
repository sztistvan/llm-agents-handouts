"""Module 7 lesson: GraphRAG local search, compared honestly with plain RAG.

Local search uses the graph in two ways: the RELATIONS around the entities of the question go into the prompt as compact
facts, and the graph's entity-to-chunk links make sure that every entity named in the question brings its own best chunk.
Part 1 follows one multi-hop question. Part 2 measures, on 13 questions that need evidence from several sections, whether
the context covers ALL of the evidence (no LLM calls needed). Plain retrieval is shown at several context sizes, because
more context is the obvious competitor.  Run:  python examples/python/m07_graphrag.py
"""
import json

from graph_store import Graph, format_facts
from rag import answer_with_sources
from retrieval import ROOT, is_hit, load_retriever

GOLDEN = ROOT / "examples" / "graph_golden.json"
QUESTION = "Which Module 2 component runs each worker of the Module 4 supervisor?"  # chosen because plain top-5 misses it


def evidence(chunks: list[dict], expect_all: list[list[str]]) -> tuple[bool, float]:
    """Does the context contain ALL the sections needed (and what share of them)?"""
    covered = [any(is_hit(c, [pair]) for c in chunks) for pair in expect_all]
    return all(covered), sum(covered) / len(covered)


if __name__ == "__main__":
    retriever = load_retriever()
    graph = Graph.open()
    report = graph.sync(retriever.chunks)
    if report["extracted"]:
        print(f"(extracted {report['extracted']} chunks first, see m07_graph_build)")
        graph.save()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    item = next(g for g in golden if g["question"] == QUESTION)

    print(f"1. One multi-hop question\n   {QUESTION}")
    plain = retriever.search(QUESTION, 5)
    context = graph.local_context(QUESTION, retriever)
    print("   entities found in the question and in the top-5 chunks (the seeds):", ", ".join(context["seeds"][:8]))
    print("   the graph's facts around them (best 8 of", len(context["facts"]), "):")
    print("\n".join("     " + line for line in format_facts(context["facts"], 8).splitlines()))
    top5 = {c["hash"] for _, c in plain}
    print("   context chunks (top-5 by search, plus the ones the graph added):")
    for chunk in context["chunks"]:
        print(f"     {'top-5' if chunk['hash'] in top5 else 'GRAPH'}  {chunk['doc_id'][:2]} > {chunk['section'].split(' > ')[-1]}")
    plain_ok = evidence([c for _, c in plain], item["expect_all"])[0]
    graph_ok = evidence(context["chunks"], item["expect_all"])[0]
    print(f"   needed: {[f'{d[:2]} > {s}' for d, s in item['expect_all']]}")
    print(f"   all needed sections present: plain top-5 {'yes' if plain_ok else 'NO'}, graph local {'yes' if graph_ok else 'NO'}")
    print("\n   Plain RAG answer:\n   ", answer_with_sources(QUESTION, plain).replace("\n", "\n    "))
    graph_hits = [(0.0, c) for c in context["chunks"]]
    print("\n   GraphRAG answer (facts + chunks):\n   ",
          answer_with_sources(QUESTION, graph_hits, facts=format_facts(context["facts"], 15)).replace("\n", "\n    "))

    print("\n2. Evidence coverage on the golden questions (every needed section must be in the context)")
    methods = {
        "plain top-5": lambda q: [c for _, c in retriever.search(q, 5)],
        "plain top-8": lambda q: [c for _, c in retriever.search(q, 8)],
        "plain top-10": lambda q: [c for _, c in retriever.search(q, 10)],
        "graph local (5 + up to 5)": lambda q: graph.local_context(q, retriever)["chunks"],
    }
    print(f"   {'method':27}{'multi-hop: all evidence':>25}{'evidence recall':>17}{'avg context':>13}{'single-hop':>12}")
    for name, find in methods.items():
        row = {}
        for kind in ("multi-hop", "single"):
            results = []
            for g in (g for g in golden if g["kind"] == kind):
                chunks = find(g["question"])
                ok, share = evidence(chunks, g["expect_all"])
                results.append((ok, share, sum(len(c["text"]) for c in chunks)))
            row[kind] = results
        multi, single = row["multi-hop"], row["single"]
        print(f"   {name:27}{sum(r[0] for r in multi):>19}/{len(multi):<5}{sum(r[1] for r in multi) / len(multi):>17.2f}"
              f"{sum(r[2] for r in multi) // len(multi):>9} chars{sum(r[0] for r in single):>8}/{len(single)}")
    print("\n   Read it with care: 10 questions are few, and 'more context' (top-8, top-10) is the obvious competitor.")
