"""Module 5 lesson: agentic RAG. Retrieval as a tool: the model decides WHEN to search and WITH WHAT query.

Compare with m05_rag_basic, which always retrieves exactly once. Here the agent loop (agent.py) may search
zero, one or several times. Run:  python examples/python/m05_rag_tool.py
"""
from agent import Tool, run_agent
from rag import format_sources
from retrieval import load_retriever

_retriever = None


def search_docs(query: str) -> str:
    """Tool: the 4 best chunks of the handouts for a query, numbered so the model can cite them."""
    global _retriever
    if _retriever is None:
        _retriever = load_retriever()
    hits = _retriever.search(query, k=4, mode="hybrid")
    return format_sources(hits, max_chars=800) if hits else "No results."


TOOLS = [Tool(
    search_docs,
    "Search the tutorial handouts about LLM agents (tool calling, patterns, multi-agent, RAG). "
    "Use it for any question about their content. Use short, specific queries; search again with a different query if needed.",
    {"type": "object", "properties": {"query": {"type": "string", "description": "What to look for"}}, "required": ["query"]})]

SYSTEM = ("You answer questions about the tutorial handouts. Use search_docs to find the facts and cite the sources "
          "you used like [1]. If you search and the results do not contain the answer, say you do not know. "
          "For questions that are not about the handouts, answer directly without searching.")

if __name__ == "__main__":
    for question in [
        "How do I continue a conversation across several run_agent calls?",          # one search
        "How does reflection differ from evaluator-optimizer, and which one has a loop?",  # may search twice
        "What is 17 * 3?",                                                            # no search needed
    ]:
        print(f"\nQ: {question}")
        print("A:", run_agent(question, TOOLS, system=SYSTEM, max_steps=6))
