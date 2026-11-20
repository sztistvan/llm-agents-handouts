"""Module 5 lesson: measure retrieval instead of guessing. Recall@k and MRR on a golden question set.

examples/rag_golden.json lists questions and the sections that answer them. A retrieval "hit" means one of the
expected sections is among the top k chunks. Run:  python examples/python/m05_rag_eval.py [--rerank]
(--rerank adds the LLM reranker: one extra model call per question.)
"""
import sys

from rag import rerank
from retrieval import first_hit_rank, load_golden, load_retriever

KS = (1, 3, 5)


def evaluate(retriever, golden: list[dict], method: str) -> tuple[dict, list]:
    ranks = []
    for item in golden:
        if method == "hybrid+rerank":
            hits = rerank(item["question"], retriever.search(item["question"], k=20, mode="hybrid"), k=5)
        else:
            hits = retriever.search(item["question"], k=5, mode=method)
        ranks.append((item["question"], first_hit_rank(hits, item["expect"]), hits))
    n = len(ranks)
    scores = {f"recall@{k}": sum(1 for _, r, _ in ranks if r and r <= k) / n for k in KS}
    scores["MRR"] = sum(1 / r for _, r, _ in ranks if r) / n
    return scores, ranks


if __name__ == "__main__":
    retriever = load_retriever()
    golden = load_golden()
    methods = ["bm25"] + (["dense", "hybrid"] if retriever.store else [])
    if "--rerank" in sys.argv and retriever.store:
        methods.append("hybrid+rerank")
    print(f"{len(golden)} golden questions, {len(retriever.chunks)} chunks\n")
    print(f"{'method':14}" + "".join(f"{'recall@' + str(k):>10}" for k in KS) + f"{'MRR':>8}")
    results = {}
    for method in methods:
        scores, ranks = evaluate(retriever, golden, method)
        results[method] = ranks
        print(f"{method:14}" + "".join(f"{scores[f'recall@{k}']:>10.2f}" for k in KS) + f"{scores['MRR']:>8.2f}")

    best = methods[-1]
    misses = [(question, hits) for question, rank, hits in results[best] if rank is None]
    print(f"\nQuestions where '{best}' misses the expected section in the top 5 "
          f"({'read these: they show what to fix' if misses else 'none: the golden set no longer discriminates, add harder questions'}):")
    for question, hits in misses:
        print(f"- {question}")
        for _, chunk in hits[:3]:
            print(f"    got: {chunk['doc_id']} > {chunk['section'].split(' > ')[-1]}")
