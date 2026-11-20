// Knowledge graph for GraphRAG (Module 7): entities and relations extracted from chunks by an LLM, with provenance.
//
// Shared building block. Layers: llm_client -> retrieval (chunks) -> graph_store (graph, extraction, search) -> m07_* lessons.
// The saved graph has the same format as the Python one, so both languages can open the same file.
//
// The source of truth is one EXTRACTION RECORD per chunk (which entities and relations the LLM found in it). The graph
// (nodes, edges, neighbours) is derived from those records, so every node and edge knows which chunks it came from:
//   * updating the graph = extract new chunks, drop the records of removed chunks, rebuild (the Module 6 idea)
//   * every fact can be cited back to its text
// Local search expands from the entities of a question over the graph; global search groups the graph into
// communities, summarizes each, and answers broad questions from the summaries.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { chat, getConfig } from "./llm_client.mjs";
import { INDEX_DIR, sha } from "./retrieval.mjs";

const PROMPT_VERSION = "v1"; // part of the cache: a changed prompt means the extractions are stale
const ENTITY_TYPES = new Set(["concept", "pattern", "component", "tool", "file", "parameter", "provider", "other"]);
const SEP = "\x01"; // joins source, relation and target into one sortable edge key

export const EXTRACT_SYSTEM = `You extract a knowledge graph from a passage of technical documentation about building LLM agents.
Reply with JSON only: {"entities": [{"name": "...", "type": "..."}], "relations": [{"source": "...", "relation": "...", "target": "..."}]}
Rules:
- Entities are the important concepts, patterns, components, tools, files, parameters or products named in the passage (at most 8). Use short, canonical, lower-case names, singular, without articles (for example "supervisor", "agent loop", "evaluator-optimizer", "run_agent").
- type is one of: concept, pattern, component, tool, file, parameter, provider, other.
- Relations connect two entities from your list with a short lower-case verb phrase (for example "uses", "is a variant of", "contrasts with", "builds on", "part of", "implemented in", "limits", "solves"). At most 8, only relations the passage states or clearly implies.
- If the passage has nothing worth extracting, return empty lists.`;

/** The identity of an entity: lower case, letters and digits only. 'Evaluator-Optimizer' and 'evaluator optimizer' are one. */
export const normalize = (name) => name.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

export const singular = (word) => (word.length > 3 && word.endsWith("s") && !word.endsWith("ss") ? word.slice(0, -1) : word);

/** Entity resolution, the simple way: names that differ only by plural forms are one entity ('tool call' = 'tool calls'). */
export const resolutionKey = (entityId) => entityId.split(" ").map(singular).join(" ");

/** One cache file per chat model: a different model extracts different things. */
export const graphPath = () => join(INDEX_DIR, `graph-${getConfig().model.replace(/[^A-Za-z0-9._-]+/g, "-")}.json`);

/** Compare two arrays element by element (numbers or strings), like Python compares tuples. */
const cmp = (a, b) => {
  for (let i = 0; i < Math.min(a.length, b.length); i++) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  return a.length - b.length;
};
const minBy = (items, keyFn) => items.reduce((best, item) => (best === undefined || cmp(keyFn(item), keyFn(best)) < 0 ? item : best), undefined);

/** Run fn over the items with at most `limit` calls in flight; the results keep the order of the items. */
async function mapLimit(items, limit, fn) {
  const results = new Array(items.length);
  let next = 0;
  const worker = async () => { while (next < items.length) { const i = next++; results[i] = await fn(items[i]); } };
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}

/** Ask for JSON; on a bad reply, say so and ask again (the parse-validate-retry pattern of Module 2). */
async function jsonReply(messages, retries = 3) {
  const conversation = [...messages];
  for (let i = 0; i < retries; i++) {
    const raw = ((await chat(conversation, { temperature: 0 })).content ?? "").trim();
    try {
      return JSON.parse(raw.match(/\{[\s\S]*\}/)?.[0] ?? "");
    } catch {
      conversation.push({ role: "assistant", content: raw }, { role: "user", content: "That was not valid JSON. Reply with valid JSON only." });
    }
  }
  return null;
}

/** One LLM call: the entities and relations of one chunk, validated. null if the model never gave usable JSON. */
export async function extractChunk(chunk) {
  const data = await jsonReply([{ role: "system", content: EXTRACT_SYSTEM },
    { role: "user", content: `Section: ${chunk.section}\n\nPassage:\n${chunk.text.slice(0, 3000)}` }]);
  if (!data || typeof data !== "object" || Array.isArray(data)) return null;
  const entities = new Map();
  for (const item of data.entities ?? []) {
    if (item && typeof item === "object" && typeof item.name === "string") {
      const id = normalize(item.name);
      if (id && !entities.has(id) && entities.size < 8) {
        entities.set(id, { name: item.name.trim().toLowerCase(), type: ENTITY_TYPES.has(item.type) ? item.type : "other" });
      }
    }
  }
  const relations = [];
  for (const item of data.relations ?? []) {
    if (!item || typeof item !== "object") continue;
    const { source, target, relation } = item;
    if ([source, target, relation].every((x) => typeof x === "string")) {
      const sourceId = normalize(source), targetId = normalize(target);
      const label = relation.toLowerCase().split(/\s+/).filter(Boolean).join(" ");
      if (sourceId && targetId && sourceId !== targetId && label && relations.length < 8) {
        for (const [id, name] of [[sourceId, source], [targetId, target]]) {
          if (!entities.has(id)) entities.set(id, { name: name.trim().toLowerCase(), type: "other" });
        }
        relations.push({ s: sourceId, r: label, t: targetId });
      }
    }
  }
  return { chunk_id: chunk.id, doc_id: chunk.doc_id, section: chunk.section,
    entities: [...entities].map(([id, e]) => ({ id, ...e })), relations };
}

/** Graph facts as lines for a prompt: source --relation--> target [chunks it came from]. */
export const formatFacts = (facts, limit = 30) =>
  facts.slice(0, limit).map((f) => `- ${f.source} --${f.relation}--> ${f.target}  [${f.chunks.slice(0, 2).join(", ")}]`).join("\n");

export class Graph {
  constructor(path = null) {
    this.path = path ?? graphPath();
    this.extractions = {}; // chunk hash -> extraction record (the source of truth)
    this.summaries = {}; // community signature -> {title, summary}
    this.chunks = new Map(); // chunk hash -> chunk (in memory: the texts of the facts)
    this.built = false;
  }

  // ------------------------------------------------------------ files

  static open(path = null) {
    const graph = new Graph(path);
    if (existsSync(graph.path)) {
      const data = JSON.parse(readFileSync(graph.path, "utf8"));
      if (data.prompt_version === PROMPT_VERSION) { // a changed extraction prompt invalidates the cache
        graph.extractions = data.extractions;
        graph.summaries = data.summaries ?? {};
      }
    }
    return graph;
  }

  save() {
    mkdirSync(dirname(this.path), { recursive: true });
    writeFileSync(this.path, JSON.stringify({ prompt_version: PROMPT_VERSION, extractions: this.extractions, summaries: this.summaries }), "utf8");
  }

  /** An independent in-memory copy (to try an update without touching the saved graph). */
  copy() {
    const other = new Graph(this.path);
    other.extractions = structuredClone(this.extractions);
    other.summaries = structuredClone(this.summaries);
    other.chunks = new Map(this.chunks);
    return other;
  }

  // ------------------------------------------------------------ building and updating

  /**
   * Bring the graph in line with the chunks: extract the new ones (an LLM call each, a few in parallel), drop the
   * records of chunks that are gone, keep the rest. Nothing is saved until save().
   */
  async sync(chunks, workers = 4) {
    this.chunks = new Map(chunks.map((c) => [c.hash, c]));
    const removed = Object.keys(this.extractions).filter((h) => !this.chunks.has(h));
    for (const h of removed) delete this.extractions[h];
    const todo = [...this.chunks.values()].filter((c) => !(c.hash in this.extractions));
    for (const [h, chunk] of this.chunks) { // a kept chunk may have moved: refresh where it lives
      if (h in this.extractions) Object.assign(this.extractions[h], { chunk_id: chunk.id, doc_id: chunk.doc_id, section: chunk.section });
    }
    const started = Date.now();
    const results = await mapLimit(todo, workers, extractChunk);
    let failed = 0;
    todo.forEach((chunk, i) => {
      if (results[i] === null) failed++; // not stored, so the next sync tries again
      else this.extractions[chunk.hash] = results[i];
    });
    this.built = false;
    return { chunks: chunks.length, kept: chunks.length - todo.length, extracted: todo.length - failed,
      removed: removed.length, failed, seconds: (Date.now() - started) / 1000 };
  }

  /** Derive nodes, edges and neighbours from the extraction records (in a fixed order, so it is deterministic). */
  #index() {
    if (this.built) return;
    // Entity resolution on the derived graph (the records stay untouched): merge variants of one name
    // into the one that occurs in most chunks.
    const hashes = Object.keys(this.extractions).sort();
    const counts = new Map();
    for (const h of hashes) for (const e of this.extractions[h].entities) counts.set(e.id, (counts.get(e.id) ?? 0) + 1);
    const groups = new Map();
    for (const id of [...counts.keys()].sort()) {
      const key = resolutionKey(id);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(id);
    }
    const canon = new Map();
    for (const members of groups.values()) {
      const best = minBy(members, (i) => [-counts.get(i), i.length, i]);
      for (const m of members) canon.set(m, best);
    }
    this.merged = [...canon].filter(([m, c]) => m !== c).sort((a, b) => cmp(a, b));

    const nodes = new Map();
    const edges = new Map();
    const names = new Map();
    this.chunkEntities = new Map();
    for (const h of hashes) {
      const record = this.extractions[h];
      this.chunkEntities.set(h, [...new Set(record.entities.map((e) => canon.get(e.id)))]);
      for (const entity of record.entities) {
        const cid = canon.get(entity.id);
        if (!nodes.has(cid)) nodes.set(cid, { types: new Map(), chunks: [] });
        const node = nodes.get(cid);
        if (entity.id === cid || !names.has(cid)) names.set(cid, entity.name); // the display name of the canonical spelling wins
        node.types.set(entity.type, (node.types.get(entity.type) ?? 0) + 1);
        if (!node.chunks.includes(h)) node.chunks.push(h);
      }
      for (const relation of record.relations) {
        const source = canon.get(relation.s), target = canon.get(relation.t);
        if (source !== target) {
          const label = relation.r.split(/[-_\s]+/).filter(Boolean).join(" "); // 'implemented-in' = 'implemented in'
          const key = [source, label, target].join(SEP);
          if (!edges.has(key)) edges.set(key, []);
          if (!edges.get(key).includes(h)) edges.get(key).push(h);
        }
      }
    }
    for (const [cid, node] of nodes) {
      node.name = names.get(cid);
      node.type = minBy([...node.types.keys()], (t) => [-node.types.get(t), t]);
    }
    this.nodes = nodes;
    this.edges = edges;
    this.adj = new Map([...nodes.keys()].map((id) => [id, []]));
    for (const key of [...edges.keys()].sort()) {
      const [source, , target] = key.split(SEP);
      this.adj.get(source).push([target, key]);
      this.adj.get(target).push([source, key]);
    }
    this.built = true;
  }

  stats() {
    this.#index();
    const types = {};
    for (const node of this.nodes.values()) types[node.type] = (types[node.type] ?? 0) + 1;
    return { chunks: Object.keys(this.extractions).length, entities: this.nodes.size, relations: this.edges.size,
      merged_variants: this.merged.length, types };
  }

  /** [name, number of relations, number of chunks] of the best connected entities. */
  topEntities(n = 10) {
    this.#index();
    const ranked = [...this.nodes.keys()].sort((a, b) => cmp([-this.adj.get(a).length, a], [-this.adj.get(b).length, b])).slice(0, n);
    return ranked.map((i) => [this.nodes.get(i).name, this.adj.get(i).length, this.nodes.get(i).chunks.length]);
  }

  /** Entity pairs whose names share most of their words: candidates for entity resolution (a hard part of GraphRAG). */
  nearDuplicates(threshold = 0.6, limit = 10) {
    this.#index();
    const ids = [...this.nodes.keys()].sort();
    const tokens = new Map(ids.map((i) => [i, new Set(i.split(" ").map(singular))]));
    const pairs = [];
    for (let a = 0; a < ids.length; a++) {
      for (let b = a + 1; b < ids.length; b++) {
        const ta = tokens.get(ids[a]), tb = tokens.get(ids[b]);
        const union = new Set([...ta, ...tb]);
        const shared = [...ta].filter((w) => tb.has(w)).length;
        const similarity = union.size ? shared / union.size : 0;
        if (similarity >= threshold) pairs.push([similarity, ids[a], ids[b]]);
      }
    }
    return pairs.sort((p, q) => cmp([-p[0], p[1], p[2]], [-q[0], q[1], q[2]])).slice(0, limit);
  }

  // ------------------------------------------------------------ local search

  /**
   * Local search. The graph is used in two ways:
   *   1. FACTS: start from the entities of the question and of the top-k retrieved chunks, walk `hops` steps over
   *      the graph, and keep the best relations (they go into the prompt as compact facts).
   *   2. CHUNKS: the graph links every entity to the chunks that mention it, so each entity NAMED in the question
   *      gets its own best chunk (a retrieval filtered by that entity). This is what brings in the second and third
   *      part of a multi-part question. Remaining room is filled with the chunks the kept facts came from.
   * Returns the seeds, the facts and the context chunks (the top-k plus at most `extraChunks` more).
   */
  async localContext(question, retriever, { k = 5, hops = 2, maxFacts = 30, extraChunks = 5, maxSeeds = 6 } = {}) {
    this.#index();
    const hits = await retriever.search(question, k);
    const padded = ` ${normalize(question)} `;
    const named = [...this.nodes.keys()].sort().filter((i) => padded.includes(` ${i} `)); // entities named in the question
    const seeds = [...named];
    for (const [, chunk] of hits) { // entities of the retrieved chunks
      for (const entityId of this.chunkEntities.get(chunk.hash) ?? []) if (!seeds.includes(entityId)) seeds.push(entityId);
    }
    const distance = new Map(seeds.map((s) => [s, 0]));
    let frontier = [...seeds];
    const found = [];
    const foundSet = new Set();
    for (let level = 0; level < hops; level++) {
      const following = [];
      for (const entityId of frontier) {
        for (const [neighbour, key] of this.adj.get(entityId)) {
          if (!foundSet.has(key)) { foundSet.add(key); found.push(key); }
          if (!distance.has(neighbour)) { distance.set(neighbour, level + 1); following.push(neighbour); }
        }
      }
      frontier = following;
    }
    const namedSet = new Set(named);
    const rank = (key) => { // facts that touch an entity named in the question come first, then the nearest, then the best supported
      const [source, , target] = key.split(SEP);
      const touchesQuestion = namedSet.has(source) || namedSet.has(target) ? 0 : 1;
      return [touchesQuestion, Math.max(distance.get(source), distance.get(target)), -this.edges.get(key).length, key];
    };
    const kept = [...found].sort((a, b) => cmp(rank(a), rank(b))).slice(0, maxFacts);
    const facts = kept.map((key) => {
      const [source, relation, target] = key.split(SEP);
      return { source: this.nodes.get(source).name, relation, target: this.nodes.get(target).name,
        chunks: this.edges.get(key).map((h) => this.extractions[h].chunk_id) };
    });
    const have = new Set(hits.map(([, chunk]) => chunk.hash));
    const extra = [];
    const specific = [...named].sort((a, b) => cmp([this.nodes.get(a).chunks.length, a], [this.nodes.get(b).chunks.length, b])).slice(0, maxSeeds);
    for (const entityId of specific) { // specific entities first
      if (extra.length >= extraChunks) break;
      const allowed = new Set(this.nodes.get(entityId).chunks);
      for (const [, chunk] of await retriever.search(question, 4, { where: (c) => allowed.has(c.hash) })) {
        if (!have.has(chunk.hash)) { extra.push(chunk); have.add(chunk.hash); break; }
      }
    }
    const support = new Map();
    for (const key of kept) for (const h of this.edges.get(key)) if (!have.has(h)) support.set(h, (support.get(h) ?? 0) + 1);
    for (const h of [...support.keys()].sort((a, b) => cmp([-support.get(a), a], [-support.get(b), b]))) {
      if (extra.length >= extraChunks) break;
      if (this.chunks.has(h)) extra.push(this.chunks.get(h));
    }
    return { seeds: seeds.map((s) => this.nodes.get(s).name), facts, chunks: [...hits.map(([, c]) => c), ...extra] };
  }

  // ------------------------------------------------------------ global search

  /**
   * Group the graph by label propagation: every entity repeatedly takes the label most common among its
   * neighbours (ties: the smallest), in a fixed order, so the result is the same on every run. A simple
   * stand-in for the Leiden algorithm that production GraphRAG systems use.
   */
  communities(minSize = 3, rounds = 10) {
    this.#index();
    const order = [...this.nodes.keys()].sort();
    const labels = new Map(order.map((i) => [i, i]));
    for (let round = 0; round < rounds; round++) {
      let changed = false;
      for (const entityId of order) {
        const counts = new Map();
        for (const [neighbour] of this.adj.get(entityId)) counts.set(labels.get(neighbour), (counts.get(labels.get(neighbour)) ?? 0) + 1);
        if (counts.size) {
          const best = minBy([...counts.keys()], (label) => [-counts.get(label), label]);
          if (best !== labels.get(entityId)) { labels.set(entityId, best); changed = true; }
        }
      }
      if (!changed) break;
    }
    const groups = new Map();
    for (const entityId of order) {
      if (!groups.has(labels.get(entityId))) groups.set(labels.get(entityId), []);
      groups.get(labels.get(entityId)).push(entityId);
    }
    return [...groups.values()].filter((g) => g.length >= minSize).sort((a, b) => cmp([-a.length, a[0]], [-b.length, b[0]]));
  }

  /** The best connected entities of a community, by name. */
  memberNames(members, n = 5) {
    this.#index();
    return [...members].sort((a, b) => cmp([-this.adj.get(a).length, a], [-this.adj.get(b).length, b])).slice(0, n).map((i) => this.nodes.get(i).name);
  }

  communityFacts(members, limit = 30) {
    const inside = new Set(members);
    const keys = [...this.edges.keys()].filter((k) => { const [s, , t] = k.split(SEP); return inside.has(s) && inside.has(t); })
      .sort((a, b) => cmp([-this.edges.get(a).length, a], [-this.edges.get(b).length, b])).slice(0, limit);
    return keys.map((k) => { const [s, r, t] = k.split(SEP); return `${this.nodes.get(s).name} --${r}--> ${this.nodes.get(t).name}`; });
  }

  /**
   * A title and a short summary of one community, written by the LLM from its entities and relations.
   * Cached by a signature of the content, so only changed communities are summarized again.
   */
  async summarize(members) {
    const facts = this.communityFacts(members);
    const signature = sha(`${[...members].sort().join("|")}#${facts.join("|")}`);
    if (!(signature in this.summaries)) {
      const names = [...members].sort((a, b) => cmp([-this.adj.get(a).length, a], [-this.adj.get(b).length, b]))
        .slice(0, 15).map((i) => this.nodes.get(i).name);
      const data = await jsonReply([{ role: "user", content:
        "These entities and relations come from documentation about building LLM agents.\n" +
        `Entities: ${names.join(", ")}\nRelations:\n${facts.join("\n")}\n\n` +
        'Name the theme these belong to and summarize it in 2 or 3 sentences. Reply with JSON only: {"title": "...", "summary": "..."}' }]);
      if (!data || typeof data.summary !== "string") return null;
      this.summaries[signature] = { title: String(data.title ?? "").trim(), summary: data.summary.trim() };
    }
    return this.summaries[signature];
  }
}
