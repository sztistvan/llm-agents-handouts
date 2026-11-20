// Retrieval building blocks (Module 5): chunking, a small vector store, BM25 keyword search and hybrid search.
//
// Shared building block, no dependencies. Layers:
//   llm_client.mjs (embed) -> retrieval.mjs (index and search) -> rag.mjs (answer) -> the m05_* lessons.
// The corpus is the handouts of Modules 1-4 (see CORPUS). The saved index has the same format as the Python one.
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { embed, embedModel, hasEmbeddings } from "./llm_client.mjs";

export const ROOT = fileURLToPath(new URL("../../", import.meta.url));
export const DOCS_DIR = join(ROOT, "docs");
// The knowledge base of the examples: the handouts of Modules 1-4. Later handouts talk about RAG itself (and
// contain the example queries), which would make the examples search their own explanation.
export const CORPUS = /^0[1-4]-.*\.md$/;
export const INDEX_DIR = join(ROOT, "examples", ".rag_index"); // git-ignored cache of the embeddings, one file per embedding model
export const indexPath = (model) => join(INDEX_DIR, `${model.replace(/[^A-Za-z0-9._-]+/g, "-")}.json`);

export const sha = (text) => createHash("sha1").update(text, "utf8").digest("hex").slice(0, 12);

// ---------------------------------------------------------------- documents and chunks

/** The markdown files of the folder as {doc_id, title, text}. Line endings are normalized so that the same
 *  text always gives the same hash, on every machine and in both languages. */
export function loadMarkdown(folder = DOCS_DIR, pattern = CORPUS) {
  return readdirSync(folder).filter((f) => pattern.test(f)).sort().map((name) => {
    const text = readFileSync(join(folder, name), "utf8").replace(/\r\n/g, "\n");
    const title = text.match(/^#\s+(.+)$/m)?.[1] ?? name.replace(/\.md$/, "");
    return { doc_id: name, title: title.trim(), text };
  });
}

/** Blank-line separated paragraphs; a code block stays in one piece. */
function paragraphs(lines) {
  const result = [];
  let current = [];
  let inFence = false;
  for (const line of lines) {
    if (line.trim().startsWith("```")) inFence = !inFence;
    if (!line.trim() && !inFence) {
      if (current.length) { result.push(current.join("\n")); current = []; }
    } else {
      current.push(line);
    }
  }
  if (current.length) result.push(current.join("\n"));
  return result;
}

/**
 * Split a markdown document by its headings (structure-aware chunking).
 * Each chunk keeps its section path ("Module 3: Agent Patterns > 8. Reflection"), which is added to the text
 * that is embedded and searched. A section longer than maxChars is split between paragraphs, and consecutive
 * pieces overlap by `overlapParagraphs`. Diagrams (mermaid) are dropped: they are noise.
 */
export function chunkMarkdown(doc, { maxChars = 1500, overlapParagraphs = 1, minChars = 40 } = {}) {
  const text = doc.text.replace(/```mermaid[\s\S]*?```/g, "");
  const stack = []; // [heading level, heading text]
  const sections = []; // [path, lines]
  let lines = [];
  let inFence = false;
  const flush = () => {
    if (lines.length) {
      sections.push([stack.map(([, t]) => t).join(" > ") || doc.title, lines]);
      lines = [];
    }
  };
  for (const line of text.split("\n")) {
    if (line.trim().startsWith("```")) inFence = !inFence;
    const heading = inFence ? null : line.match(/^(#{1,6})\s+(.+?)\s*$/);
    if (heading) {
      flush();
      const level = heading[1].length;
      while (stack.length && stack[stack.length - 1][0] >= level) stack.pop();
      stack.push([level, heading[2]]);
    } else {
      lines.push(line);
    }
  }
  flush();

  const chunks = [];
  const emit = (path, paras) => {
    const body = paras.join("\n\n").trim();
    if (body.length >= minChars) {
      chunks.push({ id: `${doc.doc_id}#${chunks.length}`, doc_id: doc.doc_id, section: path, text: body, hash: sha(`${path}\n${body}`) });
    }
  };
  for (const [path, sectionLines] of sections) {
    let current = [];
    for (const paragraph of paragraphs(sectionLines)) {
      if (current.length && [...current, paragraph].join("\n\n").length > maxChars) {
        emit(path, current);
        current = overlapParagraphs ? current.slice(-overlapParagraphs) : [];
      }
      current.push(paragraph);
    }
    if (current.length) emit(path, current);
  }
  return chunks;
}

/** What is embedded and keyword-indexed: the section path plus the text (a 'contextual header'). */
export const embedText = (chunk) => `${chunk.section}\n${chunk.text}`;

// ---------------------------------------------------------------- helpers

/** The k best items by score; ties keep their original order (like Python's heapq.nlargest). */
const top = (pairs, k) => pairs.map((p, i) => [p, i]).sort((a, b) => b[0][0] - a[0][0] || a[1] - b[1]).slice(0, k).map(([p]) => p);

const normalize = (vector) => {
  const norm = Math.sqrt(vector.reduce((s, x) => s + x * x, 0)) || 1;
  return vector.map((x) => x / norm);
};

// ---------------------------------------------------------------- dense search: a tiny vector store

/**
 * Chunks with their embeddings. Vectors are normalized, so cosine similarity is a dot product.
 * Brute force: it compares the query with every vector. Fine up to roughly 10^5 chunks; beyond that you need
 * an approximate nearest neighbour index (see the handout).
 */
export class VectorStore {
  constructor(model = "", key = "") {
    this.model = model;
    this.key = key; // identifies the corpus + model this index was built from
    this.chunks = [];
    this.vectors = [];
  }

  add(chunks, vectors) {
    this.chunks.push(...chunks);
    this.vectors.push(...vectors.map(normalize));
  }

  /** Top k chunks as [cosine score, chunk]. `where`: optional function chunk -> bool (a metadata filter). */
  search(queryVector, k = 5, where = null) {
    const q = normalize(queryVector);
    const scored = [];
    this.chunks.forEach((chunk, i) => {
      if (!where || where(chunk)) scored.push([this.vectors[i].reduce((s, x, j) => s + x * q[j], 0), chunk]);
    });
    return top(scored, k);
  }

  save(path) {
    mkdirSync(dirname(path), { recursive: true });
    const vectors = this.vectors.map((v) => v.map((x) => Math.round(x * 1e6) / 1e6));
    writeFileSync(path, JSON.stringify({ model: this.model, key: this.key, chunks: this.chunks, vectors }), "utf8");
  }

  static load(path) {
    const data = JSON.parse(readFileSync(path, "utf8"));
    const store = new VectorStore(data.model, data.key);
    store.chunks = data.chunks;
    store.vectors = data.vectors;
    return store;
  }
}

// ---------------------------------------------------------------- sparse search: BM25 keyword search

export const tokenize = (text) => text.toLowerCase().match(/[\p{L}\p{N}_]+/gu) ?? [];

/** Classic keyword ranking. Strong on exact terms (names, identifiers, error codes) where embeddings are weak. */
export class BM25 {
  constructor(chunks, k1 = 1.5, b = 0.75) {
    this.chunks = chunks;
    this.k1 = k1;
    this.b = b;
    this.lengths = [];
    this.postings = new Map(); // term -> [[chunk index, term frequency]]
    chunks.forEach((chunk, i) => {
      const tokens = tokenize(embedText(chunk));
      this.lengths.push(tokens.length);
      const counts = new Map();
      for (const t of tokens) counts.set(t, (counts.get(t) ?? 0) + 1);
      for (const [term, tf] of counts) {
        if (!this.postings.has(term)) this.postings.set(term, []);
        this.postings.get(term).push([i, tf]);
      }
    });
    this.avgLength = this.lengths.reduce((s, x) => s + x, 0) / Math.max(chunks.length, 1);
  }

  search(query, k = 5, where = null) {
    const n = this.chunks.length;
    const scores = new Map();
    for (const term of new Set(tokenize(query))) {
      const posting = this.postings.get(term) ?? [];
      const idf = Math.log(1 + (n - posting.length + 0.5) / (posting.length + 0.5));
      for (const [i, tf] of posting) {
        const norm = tf + this.k1 * (1 - this.b + (this.b * this.lengths[i]) / this.avgLength);
        scores.set(i, (scores.get(i) ?? 0) + (idf * tf * (this.k1 + 1)) / norm);
      }
    }
    const ranked = [...scores].filter(([i]) => !where || where(this.chunks[i])).map(([i, s]) => [s, this.chunks[i]]);
    return top(ranked, k);
  }
}

// ---------------------------------------------------------------- hybrid search

/** Reciprocal rank fusion: merge ranked lists of ids without comparing their (incompatible) scores.
 *  An id ranked r-th in a list earns 1 / (k + r); the sums decide. */
export function rrf(rankings, k = 60) {
  const fused = new Map();
  for (const ranking of rankings) {
    ranking.forEach((id, i) => fused.set(id, (fused.get(id) ?? 0) + 1 / (k + i + 1)));
  }
  return fused;
}

/** Dense, keyword and hybrid search over the same chunks. Without a vector store (no embedding model
 *  configured) only keyword search is available. */
export class Retriever {
  constructor(chunks, store = null) {
    this.chunks = chunks;
    this.store = store;
    this.bm25 = new BM25(chunks);
    this.queryVectors = new Map(); // the same question is often searched more than once
  }

  /** mode: 'dense' (embeddings), 'bm25' (keywords) or 'hybrid' (both, merged with RRF).
   *  For hybrid, each method contributes its top `pool` results before merging. */
  async search(query, k = 5, { mode = "hybrid", where = null, pool = 30 } = {}) {
    if (mode === "bm25" || !this.store) return this.bm25.search(query, k, where); // no embeddings: keywords only
    if (!this.queryVectors.has(query)) this.queryVectors.set(query, (await embed([query], "query"))[0]);
    const queryVector = this.queryVectors.get(query);
    if (mode === "dense") return this.store.search(queryVector, k, where);
    const dense = this.store.search(queryVector, pool, where);
    const sparse = this.bm25.search(query, pool, where);
    const fused = rrf([dense.map(([, c]) => c.id), sparse.map(([, c]) => c.id)]);
    const byId = new Map([...dense, ...sparse].map(([, c]) => [c.id, c]));
    return top([...fused].map(([id, score]) => [score, byId.get(id)]), k);
  }
}

// ---------------------------------------------------------------- evaluation helpers

export const GOLDEN = join(ROOT, "examples", "rag_golden.json"); // questions with the sections that answer them

export const loadGolden = () => JSON.parse(readFileSync(GOLDEN, "utf8"));

/** Is this chunk one of the expected [file, section name] pairs? */
export const isHit = (chunk, expect) =>
  expect.some(([doc, section]) => chunk.doc_id === doc && chunk.section.toLowerCase().includes(section.toLowerCase()));

export const firstHitRank = (hits, expect) => {
  const i = hits.findIndex(([, chunk]) => isHit(chunk, expect));
  return i === -1 ? null : i + 1;
};

/** The share of golden questions whose expected section is among the top k chunks. */
export async function recallAtK(retriever, golden, k = 5, mode = "hybrid") {
  let found = 0;
  for (const item of golden) {
    if (firstHitRank(await retriever.search(item.question, k, { mode }), item.expect) !== null) found++;
  }
  return found / golden.length;
}

// ---------------------------------------------------------------- building the index

/** Embed all chunks, or load the saved index if neither the chunks nor the embedding model changed. */
export async function loadOrBuildIndex(chunks, path = null) {
  const model = embedModel();
  path ??= indexPath(model);
  const key = sha(`${model}|${chunks.map((c) => c.hash).join("")}`);
  if (existsSync(path)) {
    const store = VectorStore.load(path);
    if (store.key === key) return store;
  }
  console.log(`Embedding ${chunks.length} chunks with ${model} ...`);
  const store = new VectorStore(model, key);
  store.add(chunks, await embed(chunks.map(embedText), "document"));
  store.save(path);
  return store;
}

/** Load and chunk the handouts and build the search indexes. Uses embeddings if an embedding model is
 *  configured (<PROVIDER>_EMBED_MODEL), otherwise keyword search only. */
export async function loadRetriever(folder = DOCS_DIR) {
  const chunks = loadMarkdown(folder).flatMap((doc) => chunkMarkdown(doc));
  if (!hasEmbeddings()) {
    console.log("(no embedding model configured: keyword search only; see .env.example)");
    return new Retriever(chunks);
  }
  return new Retriever(chunks, await loadOrBuildIndex(chunks));
}
