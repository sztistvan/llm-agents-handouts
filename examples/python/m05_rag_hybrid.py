"""Module 5 lesson: better retrieval. Dense vs keyword (BM25) vs hybrid, a metadata filter, and reranking.

Run:  python examples/python/m05_rag_hybrid.py
"""
from rag import answer_with_sources, rerank
from retrieval import load_retriever

QUERIES = [
    ("meaning, few shared words", "how does the model remember earlier turns of a conversation?"),
    ("an exact identifier", "model_dump"),
]


def show(label: str, hits) -> None:
    print(f"  {label:6}", " | ".join(f"{score:.2f} {chunk['doc_id'][:2]}:{chunk['section'].split(' > ')[-1][:32]}"
                                    for score, chunk in hits))


if __name__ == "__main__":
    retriever = load_retriever()

    modes = ("dense", "bm25", "hybrid") if retriever.store else ("bm25",)  # without embeddings only keywords exist
    print("1. Three ways to search (top 3 per method; score scales differ: cosine, BM25, RRF)")
    if len(modes) == 1:
        print("   (no embedding model configured: only the keyword row is real here)")
    for kind, query in QUERIES:
        print(f"\nQ ({kind}): {query}")
        for mode in modes:
            show(mode, retriever.search(query, k=3, mode=mode))

    print("\n2. A metadata filter: only chunks of the patterns handout (03-patterns.md)")
    only_patterns = lambda chunk: chunk["doc_id"] == "03-patterns.md"
    show("hybrid", retriever.search("when should a second call check the first answer?", k=3, where=only_patterns))

    print("\n3. Two stages: retrieve wide (20 candidates), let the LLM rerank, keep the best 4, answer")
    question = "What is the difference between reflection and evaluator-optimizer?"
    candidates = retriever.search(question, k=20, mode="hybrid")
    best = rerank(question, candidates, k=4)
    show("before", candidates[:4])
    show("after", best)
    print("A:", answer_with_sources(question, best))
