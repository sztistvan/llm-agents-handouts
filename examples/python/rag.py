"""RAG generation helpers (Module 5): numbered sources, an answer that cites them, and an LLM reranker.

Shared building block. Layers: llm_client.py -> retrieval.py (find chunks) -> rag.py (use them) -> m05_* lessons.
`hits` are lists of (score, chunk) pairs, as returned by Retriever.search.
"""
import json
import re

from llm_client import chat

ANSWER_SYSTEM = (
    "Answer the question using ONLY the numbered sources. Cite the sources you used like [1] or [2][3]. "
    "If the sources do not contain the answer, say that you do not know based on the handouts. Be concise."
)


def format_sources(hits: list[tuple[float, dict]], max_chars: int = 1200) -> str:
    """Number the retrieved chunks so the model can cite them: [1] file > section, then the text."""
    return "\n\n".join(
        f"[{n}] {chunk['doc_id']} > {chunk['section']}\n{chunk['text'][:max_chars]}"
        for n, (_, chunk) in enumerate(hits, start=1))


def answer_with_sources(question: str, hits: list[tuple[float, dict]], system: str = ANSWER_SYSTEM, facts: str = "") -> str:
    """Augment and generate: put the sources in the prompt and answer from them only.
    `facts` (optional): extra lines from a knowledge graph (Module 7), shown before the question."""
    if not hits:
        return "I do not know based on the handouts (nothing relevant was found)."
    graph = f"Graph facts (relations between the entities in the sources):\n{facts}\n\n" if facts else ""
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": f"Sources:\n{format_sources(hits)}\n\n{graph}Question: {question}"}]
    return (chat(messages, temperature=0.2).content or "").strip()


def rerank(question: str, hits: list[tuple[float, dict]], k: int = 5) -> list[tuple[float, dict]]:
    """Second stage: let the LLM read the candidates and score how well each answers the question (0-10).

    Retrieval is cheap and wide (many candidates); reranking is slower and precise (a few are kept).
    Returns the best k as (llm score, chunk). If the model's reply cannot be parsed, the original order stays.
    """
    if len(hits) <= 1:
        return hits[:k]
    passages = "\n\n".join(f"[{n}] {chunk['section']}\n{chunk['text'][:500]}" for n, (_, chunk) in enumerate(hits, 1))
    prompt = (f"Question: {question}\n\nPassages:\n{passages}\n\n"
              "Score each passage from 0 (irrelevant) to 10 (answers the question directly). "
              f'Reply with JSON only: {{"scores": [one number per passage, in order, {len(hits)} numbers]}}')
    for _ in range(2):
        raw = (chat([{"role": "user", "content": prompt}], temperature=0).content or "").strip()
        match = re.search(r"\{.*\}", raw, re.S)
        try:
            scores = json.loads(match.group(0))["scores"] if match else None
            if isinstance(scores, list) and len(scores) == len(hits):
                ranked = sorted(zip((float(s) for s in scores), (c for _, c in hits)), key=lambda p: -p[0])
                return ranked[:k]
        except (ValueError, KeyError, TypeError):
            pass
    return hits[:k]
