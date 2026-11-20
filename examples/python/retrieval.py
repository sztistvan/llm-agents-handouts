"""Retrieval building blocks (Module 5): chunking, a small vector store, BM25 keyword search and hybrid search.

Shared building block, no dependencies (plain Python). Layers:
  llm_client.py (embed) -> retrieval.py (index and search) -> rag.py (answer) -> the m05_* lessons.
The corpus is the handouts of Modules 1-4 (see CORPUS).
"""
import hashlib
import heapq
import json
import math
import re
from pathlib import Path

from llm_client import embed, embed_model, has_embeddings

ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = ROOT / "docs"
# The knowledge base of the examples: the handouts of Modules 1-4. Later handouts talk about RAG itself (and
# contain the example queries), which would make the examples search their own explanation.
CORPUS = "0[1-4]-*.md"
INDEX_DIR = ROOT / "examples" / ".rag_index"  # git-ignored cache of the embeddings, one file per embedding model


def index_path(model: str) -> Path:
    return INDEX_DIR / (re.sub(r"[^A-Za-z0-9._-]+", "-", model) + ".json")


def sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- documents and chunks

def load_markdown(folder: Path = DOCS_DIR, pattern: str = CORPUS) -> list[dict]:
    """The markdown files of the folder as {doc_id, title, text}. Line endings are normalized so that
    the same text always gives the same hash, on every machine and in both languages."""
    docs = []
    for path in sorted(Path(folder).glob(pattern)):
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        title = next((m.group(1) for m in re.finditer(r"^#\s+(.+)$", text, re.M)), path.stem)
        docs.append({"doc_id": path.name, "title": title.strip(), "text": text})
    return docs


def _paragraphs(lines: list[str], first_line: int = 1) -> list[tuple[int, str]]:
    """Blank-line separated paragraphs as (line number of the first line, text); a code block stays in one piece."""
    paragraphs, current, start, in_fence = [], [], first_line, False
    for number, line in enumerate(lines, start=first_line):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if not line.strip() and not in_fence:
            if current:
                paragraphs.append((start, "\n".join(current)))
                current = []
        else:
            if not current:
                start = number
            current.append(line)
    if current:
        paragraphs.append((start, "\n".join(current)))
    return paragraphs


def chunk_markdown(doc: dict, max_chars: int = 1500, overlap_paragraphs: int = 1, min_chars: int = 40) -> list[dict]:
    """Split a markdown document by its headings (structure-aware chunking).

    Each chunk keeps its section path ("Module 3: Agent Patterns > 8. Reflection"), which is added to the
    text that is embedded and searched. A section longer than max_chars is split between paragraphs, and
    consecutive pieces overlap by `overlap_paragraphs`. Diagrams (mermaid) are dropped: they are noise. Each chunk
    records `start_line`: the line of the original file where its first paragraph begins (1-based).
    """
    # A diagram is replaced by as many empty lines as it had, so that line numbers stay those of the file.
    text = re.sub(r"```mermaid.*?```", lambda m: "\n" * m.group().count("\n"), doc["text"], flags=re.S)
    stack: list[tuple[int, str]] = []  # (heading level, heading text)
    sections: list[tuple[str, int, list[str]]] = []  # (heading path, line number of the first line, lines)
    lines: list[str] = []
    first = 1
    in_fence = False

    def flush():
        if lines:
            sections.append((" > ".join(t for _, t in stack) or doc["title"], first, list(lines)))
            lines.clear()

    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        heading = None if in_fence else re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            flush()
            first = number + 1
            level = len(heading.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, heading.group(2)))
        else:
            lines.append(line)
    flush()

    chunks: list[dict] = []

    def emit(path: str, paragraphs: list[tuple[int, str]]):
        body = "\n\n".join(text for _, text in paragraphs).strip()
        if len(body) >= min_chars:
            chunks.append({"id": f"{doc['doc_id']}#{len(chunks)}", "doc_id": doc["doc_id"], "section": path,
                           "start_line": paragraphs[0][0], "text": body, "hash": sha(path + "\n" + body)})

    for path, first_line, section_lines in sections:
        current: list[tuple[int, str]] = []
        for paragraph in _paragraphs(section_lines, first_line):
            if current and len("\n\n".join(t for _, t in current + [paragraph])) > max_chars:
                emit(path, current)
                current = current[-overlap_paragraphs:] if overlap_paragraphs else []
            current.append(paragraph)
        if current:
            emit(path, current)
    return chunks


def embed_text(chunk: dict) -> str:
    """What is embedded and keyword-indexed: the section path plus the text (a 'contextual header')."""
    return f"{chunk['section']}\n{chunk['text']}"


# ---------------------------------------------------------------- dense search: a tiny vector store

def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


class VectorStore:
    """Chunks with their embeddings. Vectors are normalized, so cosine similarity is a dot product.

    Brute force: it compares the query with every vector. Fine up to roughly 10^5 chunks; beyond that
    you need an approximate nearest neighbour index (see the handout).
    """

    def __init__(self, model: str = "", key: str = ""):
        self.model, self.key = model, key  # key identifies the corpus + model this index was built from
        self.chunks: list[dict] = []
        self.vectors: list[list[float]] = []

    def add(self, chunks: list[dict], vectors: list[list[float]]) -> None:
        self.chunks += chunks
        self.vectors += [_normalize(v) for v in vectors]

    def search(self, query_vector: list[float], k: int = 5, where=None) -> list[tuple[float, dict]]:
        """Top k chunks as (cosine score, chunk). `where`: optional function chunk -> bool (a metadata filter)."""
        q = _normalize(query_vector)
        scored = ((sum(a * b for a, b in zip(q, v)), c) for c, v in zip(self.chunks, self.vectors)
                  if where is None or where(c))
        return heapq.nlargest(k, scored, key=lambda pair: pair[0])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"model": self.model, "key": self.key, "chunks": self.chunks,
                "vectors": [[round(x, 6) for x in v] for v in self.vectors]}
        path.write_text(json.dumps(data), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "VectorStore":
        data = json.loads(path.read_text(encoding="utf-8"))
        store = cls(data["model"], data["key"])
        store.chunks, store.vectors = data["chunks"], data["vectors"]
        return store


# ---------------------------------------------------------------- sparse search: BM25 keyword search

def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


class BM25:
    """Classic keyword ranking. Strong on exact terms (names, identifiers, error codes) where embeddings are weak."""

    def __init__(self, chunks: list[dict], k1: float = 1.5, b: float = 0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        self.lengths, self.postings = [], {}  # postings: term -> [(chunk index, term frequency)]
        for i, chunk in enumerate(chunks):
            tokens = tokenize(embed_text(chunk))
            self.lengths.append(len(tokens))
            for term in set(tokens):
                self.postings.setdefault(term, []).append((i, tokens.count(term)))
        self.avg_length = sum(self.lengths) / max(len(chunks), 1)

    def search(self, query: str, k: int = 5, where=None) -> list[tuple[float, dict]]:
        n, scores = len(self.chunks), {}
        for term in set(tokenize(query)):
            posting = self.postings.get(term, [])
            idf = math.log(1 + (n - len(posting) + 0.5) / (len(posting) + 0.5))
            for i, tf in posting:
                norm = tf + self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avg_length)
                scores[i] = scores.get(i, 0.0) + idf * tf * (self.k1 + 1) / norm
        ranked = ((s, self.chunks[i]) for i, s in scores.items() if where is None or where(self.chunks[i]))
        return heapq.nlargest(k, ranked, key=lambda pair: pair[0])


# ---------------------------------------------------------------- hybrid search

def rrf(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal rank fusion: merge ranked lists of ids without comparing their (incompatible) scores.
    An id ranked r-th in a list earns 1 / (k + r); the sums decide."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return fused


class Retriever:
    """Dense, keyword and hybrid search over the same chunks. Without a vector store (no embedding model
    configured) only keyword search is available."""

    def __init__(self, chunks: list[dict], store: VectorStore | None = None):
        self.chunks, self.store, self.bm25 = chunks, store, BM25(chunks)
        self._query_vectors: dict[str, list[float]] = {}  # the same question is often searched more than once

    def search(self, query: str, k: int = 5, mode: str = "hybrid", where=None, pool: int = 30) -> list[tuple[float, dict]]:
        """mode: 'dense' (embeddings), 'bm25' (keywords) or 'hybrid' (both, merged with RRF).
        For hybrid, each method contributes its top `pool` results before merging."""
        if mode == "bm25" or self.store is None:  # no embeddings available: keywords only
            return self.bm25.search(query, k, where)
        if query not in self._query_vectors:
            self._query_vectors[query] = embed([query], kind="query")[0]
        query_vector = self._query_vectors[query]
        if mode == "dense":
            return self.store.search(query_vector, k, where)
        dense = self.store.search(query_vector, pool, where)
        sparse = self.bm25.search(query, pool, where)
        fused = rrf([[c["id"] for _, c in dense], [c["id"] for _, c in sparse]])
        by_id = {c["id"]: c for _, c in dense + sparse}
        ranked = heapq.nlargest(k, fused.items(), key=lambda kv: kv[1])
        return [(score, by_id[chunk_id]) for chunk_id, score in ranked]


# ---------------------------------------------------------------- evaluation helpers

GOLDEN = ROOT / "examples" / "rag_golden.json"  # questions with the sections that answer them


def load_golden() -> list[dict]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def is_hit(chunk: dict, expect: list[list[str]]) -> bool:
    """Is this chunk one of the expected [file, section name] pairs?"""
    return any(chunk["doc_id"] == doc and section.lower() in chunk["section"].lower() for doc, section in expect)


def first_hit_rank(hits: list[tuple[float, dict]], expect: list[list[str]]) -> int | None:
    return next((rank for rank, (_, chunk) in enumerate(hits, start=1) if is_hit(chunk, expect)), None)


def recall_at_k(retriever: Retriever, golden: list[dict], k: int = 5, mode: str = "hybrid") -> float:
    """The share of golden questions whose expected section is among the top k chunks."""
    found = sum(1 for item in golden
                if first_hit_rank(retriever.search(item["question"], k=k, mode=mode), item["expect"]) is not None)
    return found / len(golden)


# ---------------------------------------------------------------- building the index

def load_or_build_index(chunks: list[dict], path: Path | None = None) -> VectorStore:
    """Embed all chunks, or load the saved index if neither the chunks nor the embedding model changed."""
    model = embed_model()
    path = path or index_path(model)
    key = sha(model + "|" + "".join(c["hash"] for c in chunks))
    if path.exists():
        store = VectorStore.load(path)
        if store.key == key:
            return store
    print(f"Embedding {len(chunks)} chunks with {model} ...")
    store = VectorStore(model, key)
    store.add(chunks, embed([embed_text(c) for c in chunks], kind="document"))
    store.save(path)
    return store


def load_retriever(folder: Path = DOCS_DIR) -> Retriever:
    """Load and chunk the handouts and build the search indexes. Uses embeddings if an embedding model is
    configured (<PROVIDER>_EMBED_MODEL), otherwise keyword search only."""
    chunks = [c for doc in load_markdown(folder) for c in chunk_markdown(doc)]
    if not has_embeddings():
        print("(no embedding model configured: keyword search only; see .env.example)")
        return Retriever(chunks)
    return Retriever(chunks, load_or_build_index(chunks))
