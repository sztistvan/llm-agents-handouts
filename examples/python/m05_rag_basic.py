"""Module 5 lesson: naive RAG, end to end.

Index the handouts (chunk, embed), retrieve the chunks closest to the question, put them in the prompt,
answer with citations. Run:  python examples/python/m05_rag_basic.py ["your question"]
"""
import os
import sys

from rag import answer_with_sources
from retrieval import load_retriever

# Cosine scores are only comparable within ONE embedding model: unrelated text scores about 0.1 with
# Azure text-embedding-3-small but about 0.4 with nomic. Calibrate the threshold for your model.
MIN_SCORE = float(os.environ.get("RAG_MIN_SCORE", "0.25"))


def ask(retriever, question: str, k: int = 4) -> str:
    dense = retriever.store is not None
    hits = retriever.search(question, k=k, mode="dense" if dense else "bm25")
    if dense:
        hits = [(score, chunk) for score, chunk in hits if score >= MIN_SCORE]  # too weak a match = not found
    print(f"\nQ: {question}")
    for n, (score, chunk) in enumerate(hits, start=1):
        print(f"  [{n}] {score:.2f}  {chunk['doc_id']} > {chunk['section']}")
    if not hits:
        print("  (nothing above the score threshold)")
    answer = answer_with_sources(question, hits)
    print(f"A: {answer}")
    return answer


if __name__ == "__main__":
    retriever = load_retriever()
    questions = sys.argv[1:] or [
        "What is the difference between reflection and evaluator-optimizer?",
        "How can I continue a conversation across several run_agent calls?",
        "What is the capital of Australia?",  # not in the handouts: the right answer is "I do not know"
    ]
    for question in questions:
        ask(retriever, question)
