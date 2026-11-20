"""Module 7 lesson: GraphRAG global search. Questions about the WHOLE document set.

"What are the main themes?" has no answer in any single chunk, and top-k retrieval returns only a few chunks. GraphRAG
groups the graph into communities (label propagation here, Leiden in production systems), has an LLM summarize each, and
answers broad questions from the summaries. A real system maps the question over each summary and combines the partial
answers; here all summaries fit one prompt. Summaries are cached by the content of their community.
Run:  python examples/python/m07_graphrag_global.py
"""
from graph_store import Graph
from llm_client import chat
from rag import answer_with_sources
from retrieval import load_retriever

QUESTION = "What are the main themes of the handouts as a whole?"
TOP = 8  # how many of the largest communities to summarize


def answer_global(question: str, summaries: list[dict]) -> str:
    context = "\n\n".join(f"[{n}] {s['title']}: {s['summary']}" for n, s in enumerate(summaries, start=1))
    messages = [{"role": "system", "content": "Answer the question using ONLY the community summaries below, which together "
                                              "cover the whole document set. Name the themes you use by their title. Be concise."},
                {"role": "user", "content": f"Community summaries:\n{context}\n\nQuestion: {question}"}]
    return (chat(messages, temperature=0.2).content or "").strip()


if __name__ == "__main__":
    retriever = load_retriever()
    graph = Graph.open()
    report = graph.sync(retriever.chunks)
    if report["extracted"]:
        print(f"(extracted {report['extracted']} chunks first, see m07_graph_build)")

    groups = graph.communities()
    print(f"1. Communities: {len(groups)} groups of at least 3 entities; sizes of the largest: {[len(g) for g in groups[:10]]}")
    for number, members in enumerate(groups[:TOP], start=1):
        print(f"   {number}. {len(members):2} entities, e.g. {', '.join(graph.member_names(members))}")

    print(f"\n2. One LLM call per community writes a title and a summary (cached; {TOP} communities)")
    summaries = [s for s in (graph.summarize(members) for members in groups[:TOP]) if s]
    graph.save()
    for summary in summaries[:4]:
        print(f"   - {summary['title']}: {summary['summary']}")

    print(f"\n3. A global question: {QUESTION}")
    print("\n   Plain RAG (top-5 chunks):\n   ", answer_with_sources(QUESTION, retriever.search(QUESTION, 5)).replace("\n", "\n    "))
    print("\n   GraphRAG global (community summaries):\n   ", answer_global(QUESTION, summaries).replace("\n", "\n    "))
