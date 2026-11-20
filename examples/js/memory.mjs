// Memory for agents (Module 9): short-term (trim, summarize), long-term (remember / recall) and fact memory.
//
// Shared building block. Layers: llm_client -> agent (the loop) -> memory -> m09_* lessons. Three kinds of memory:
//
//   SHORT-TERM  the message array of one conversation. `trim` keeps the newest turns, `compact` replaces the old ones
//               by a summary. A TURN starts at a user message and holds everything up to the next one, so an
//               assistant message with tool calls is never separated from the results of those calls.
//   LONG-TERM   `MemoryStore`: short, self-contained statements ("Dana lives in Vienna") with an embedding, one JSON
//               file per user. `remember` RECONCILES a new statement with the neighbours already stored (add, update
//               or ignore); `search` finds memories by meaning (cosine similarity, as in Module 5).
//   FACTS       `FactStore`: (subject, relation, object) triples with the period in which they were true, so a change
//               closes the old fact instead of deleting it. The relations are a tiny ontology (Module 7, section 3).
//
// Memories are only ever extracted from what the USER said (`extractFacts`): tool results and web pages are not a
// source of memories (see section 5 of docs/09-memory.md).
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chat, embed, embedModel } from "./llm_client.mjs";
import { jsonReply } from "./graph_store.mjs"; // the parse-validate-retry helper of Module 7

export const ROOT = fileURLToPath(new URL("../../", import.meta.url));
export const MEMORY_DIR = join(ROOT, "examples", ".memory"); // git-ignored: memories are personal data
export const SUMMARY_MARK = "\n\n[Summary of the earlier conversation]\n";
const today = () => new Date().toISOString().slice(0, 10);
const readJson = (path, fallback) => (existsSync(path) ? JSON.parse(readFileSync(path, "utf8")) : fallback);
const writeJson = (path, data, indent) => { mkdirSync(join(path, ".."), { recursive: true }); writeFileSync(path, JSON.stringify(data, null, indent), "utf8"); };

// ------------------------------------------------------------------------------------------ short-term memory

/** A plain, JSON-safe message (the same shape the Python version produces). */
export function asDict(msg) {
  const out = {};
  for (const key of ["role", "content", "tool_calls", "tool_call_id"]) {
    const value = msg[key];
    if (value !== undefined && value !== null && !(Array.isArray(value) && value.length === 0)) out[key] = value;
  }
  return out;
}

/** A rough estimate: 4 characters per token plus a few per message. Use a real tokenizer when it matters. */
export const tokens = (messages) => messages.reduce((sum, m) => sum + Math.floor(JSON.stringify(asDict(m)).length / 4) + 4, 0);

/** [the leading system message, turns]. A turn starts at a user message and ends before the next one. */
export function splitTurns(messages) {
  const head = messages.slice(0, 1).filter((m) => m.role === "system");
  const turns = [];
  for (const msg of messages.slice(head.length)) {
    if (msg.role === "user" || turns.length === 0) turns.push([]);
    turns[turns.length - 1].push(msg);
  }
  return [head, turns];
}

/** Keep the system message and as many of the newest turns as fit into `budget` tokens (at least the last one). */
export function trim(messages, budget) {
  const [head, turns] = splitTurns(messages);
  let kept = [];
  for (const turn of [...turns].reverse()) {
    if (kept.length && tokens([...head, ...turn, ...kept.flat()]) > budget) break;
    kept = [turn, ...kept];
  }
  return [...head, ...kept.flat()];
}

function transcript(messages) {
  const lines = [];
  for (const msg of messages.map(asDict)) {
    if (msg.role === "tool") lines.push(`tool result: ${msg.content.slice(0, 300)}`);
    else if (msg.tool_calls) lines.push("assistant calls: " + msg.tool_calls.map((c) => c.function.name + c.function.arguments).join(", "));
    else if (msg.role !== "system") lines.push(`${msg.role}: ${msg.content ?? ""}`);
  }
  return lines.join("\n");
}

/** One LLM call: a summary of the old turns that keeps what the assistant will need later. */
export async function summarize(messages, previous = "") {
  let prompt = "Summarize this conversation for the assistant's own later use, in at most 120 words. Keep names, numbers, dates, " +
    "decisions, preferences, constraints, open tasks and exact identifiers. Leave out pleasantries and details that are repeated.\n\n";
  if (previous) prompt += `Summary so far:\n${previous}\n\nNew messages:\n`;
  return ((await chat([{ role: "user", content: prompt + transcript(messages) }], { temperature: 0 })).content ?? "").trim();
}

/**
 * If the conversation is over `budget` tokens, replace everything but the last `keepTurns` turns by a summary.
 * The summary is appended to the system message (some models accept only one system message, and only first).
 * Compacting again summarizes the previous summary together with the newly old turns: a rolling summary.
 */
export async function compact(messages, budget, keepTurns = 2) {
  if (tokens(messages) <= budget) return [...messages];
  const [head, turns] = splitTurns(messages);
  if (!head.length || turns.length <= keepTurns) return [...messages];
  const cut = head[0].content.indexOf(SUMMARY_MARK);
  const base = cut < 0 ? head[0].content : head[0].content.slice(0, cut);
  const previous = cut < 0 ? "" : head[0].content.slice(cut + SUMMARY_MARK.length);
  const old = turns.slice(0, -keepTurns), recent = turns.slice(-keepTurns);
  const summary = await summarize(old.flat(), previous);
  return [{ role: "system", content: base + SUMMARY_MARK + summary }, ...recent.flat()];
}

/** Persist a conversation as JSON. */
export const saveMessages = (path, messages) => writeJson(path, messages.map(asDict), 2);
export const loadMessages = (path) => readJson(path, []);

// ------------------------------------------------------------------------------------------- long-term memory

const EXTRACT_FACTS = `You read a conversation and list the durable facts about the USER that an assistant should remember in future sessions:
identity, preferences, constraints, ongoing projects, important dates. Ignore small talk and one-off requests.
Reply with JSON only: {"facts": ["Dana prefers short answers", "..."]}. Each fact is one short, self-contained sentence in the third person.`;

const RECONCILE = `You maintain a list of memories about a user. A new fact arrived. Compare it with the existing memories and reply with JSON only:
{"action": "ADD" | "UPDATE" | "NOOP", "id": "<id of the memory to change, for UPDATE>", "text": "<the memory text to store, for ADD or UPDATE>"}
UPDATE when the new fact replaces or refines an existing memory (a new city replaces the old one); NOOP when it is already known;
ADD when it is new. A stored memory may contain several facts: when the new fact replaces only one of them, UPDATE with the corrected
full text and keep what is still true. Write memories as the current state ("Dana lives in Vienna"), not as an event ("moved last month")
and without relative dates. A memory is one short, self-contained sentence in the third person.`;

/** One LLM call: durable facts from a conversation. By default ONLY from the user's own messages. */
export async function extractFacts(messages, onlyUser = true) {
  const wanted = onlyUser ? messages.filter((m) => m.role === "user") : messages;
  const data = await jsonReply([{ role: "system", content: EXTRACT_FACTS }, { role: "user", content: transcript(wanted) }]);
  const facts = data && typeof data === "object" ? data.facts : null;
  return (Array.isArray(facts) ? facts : []).filter((f) => typeof f === "string" && f.trim()).map((f) => f.trim());
}

const cosine = (a, b) => {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
  return dot / (Math.sqrt(na) * Math.sqrt(nb) || 1);
};
const fileName = (user) => user.replace(/[^A-Za-z0-9._-]+/g, "_");

/** Long-term memories of ONE user in one JSON file: examples/.memory/<user>.json (the user id is the isolation boundary). */
export class MemoryStore {
  constructor(user, directory = MEMORY_DIR) {
    this.path = join(directory, `${fileName(user)}.json`);
    const data = readJson(this.path, {});
    this.model = data.embed_model || embedModel();
    if (this.model !== embedModel()) throw new Error(`${fileName(user)}.json was embedded with '${this.model}', not '${embedModel()}': re-embed it (Module 6, model changes).`);
    this.items = data.memories ?? [];
    this.nextId = data.next_id ?? 1;
  }

  save() { writeJson(this.path, { embed_model: this.model, next_id: this.nextId, memories: this.items }); }

  /** The memories closest in meaning to `query` (cosine similarity), best first; weak matches are dropped. */
  async search(query, k = 4, minScore = 0.2) {
    if (!this.items.length) return [];
    const [vector] = await embed([query], "query");
    return this.items.map((m) => [cosine(vector, m.vector), m]).sort((a, b) => b[0] - a[0]).slice(0, k).filter(([score]) => score >= minScore);
  }

  async add(text, source = "") {
    const item = { id: `m${this.nextId}`, text, created: today(), updated: today(), source, vector: (await embed([text]))[0] };
    this.nextId += 1;
    this.items.push(item);
    this.save();
    return item;
  }

  async update(memoryId, text) {
    const item = this.items.find((m) => m.id === memoryId);
    if (!item) return null;
    Object.assign(item, { text, updated: today(), vector: (await embed([text]))[0] });
    this.save();
    return item;
  }

  delete(memoryId) {
    const before = this.items.length;
    this.items = this.items.filter((m) => m.id !== memoryId);
    this.save();
    return this.items.length < before;
  }

  /** Reconcile a new fact with the stored neighbours: returns ["ADD" | "UPDATE" | "NOOP", the memory]. */
  async remember(fact, source = "") {
    const neighbours = await this.search(fact, 3, 0.2);
    if (!neighbours.length) return ["ADD", await this.add(fact, source)];
    const listing = neighbours.map(([, m]) => `${m.id}: ${m.text}`).join("\n");
    let data = await jsonReply([{ role: "system", content: RECONCILE }, { role: "user", content: `Existing memories:\n${listing}\n\nNew fact: ${fact}` }]);
    data = data && typeof data === "object" ? data : {};
    const action = String(data.action ?? "ADD").toUpperCase();
    const text = String(data.text || fact).trim();
    if (action === "NOOP") return ["NOOP", neighbours.find(([, m]) => m.id === data.id)?.[1] ?? null];
    if (action === "UPDATE") {
      const changed = await this.update(String(data.id), text);
      if (changed) return ["UPDATE", changed];
    }
    return ["ADD", await this.add(text, source)]; // also the fallback when the model's answer cannot be applied
  }

  /**
   * What to put into the system prompt of a new session: the memories relevant to `query`, or ALL of them
   * (a small store fits into the prompt, and standing preferences are not "relevant" to any particular question).
   */
  async contextBlock(query, k = 4, everything = false) {
    const texts = everything ? this.items.map((m) => m.text) : (await this.search(query, k)).map(([, m]) => m.text);
    return texts.length ? "What you know about the user from earlier sessions:\n" + texts.map((t) => `- ${t}`).join("\n") : "";
  }
}

// ----------------------------------------------------------------------------------- fact memory with history

export const RELATIONS = { lives_in: true, works_at: true, job_title: true, // true: one value at a time
  works_on: false, likes: false, allergic_to: false, has_pet: false, knows: false };

const extractTriplesSystem = (userName) => `You read what a user said and extract facts about them as triples. Reply with JSON only:
{"facts": [{"subject": "...", "relation": "...", "object": "..."}]}
relation is one of: ${Object.keys(RELATIONS).join(", ")}. The subject of facts about the speaker is "${userName}"; facts about another person use that person's name as subject.
Objects are short and lower-case, except names. Only facts the user states; nothing else.`;

/** One LLM call: [subject, relation, object] triples from the user's messages; relations outside RELATIONS are dropped. */
export async function extractTriples(messages, userName) {
  const data = await jsonReply([{ role: "system", content: extractTriplesSystem(userName) },
    { role: "user", content: transcript(messages.filter((m) => m.role === "user")) }]);
  const triples = [];
  for (const item of (data && typeof data === "object" && Array.isArray(data.facts) ? data.facts : [])) {
    if (item && typeof item === "object" && ["subject", "relation", "object"].every((k) => typeof item[k] === "string" && item[k].trim()) && item.relation in RELATIONS) {
      triples.push([item.subject.trim(), item.relation, item.object.trim()]);
    }
  }
  return triples;
}

/** Triples with validity periods: a new value of a single-valued relation CLOSES the old fact (valid_to) instead of deleting it. */
export class FactStore {
  constructor(user, directory = MEMORY_DIR) {
    this.path = join(directory, `${fileName(user)}.facts.json`);
    this.facts = readJson(this.path, []);
  }

  save() { writeJson(this.path, this.facts, 1); }

  /** Record a fact that became true on `when` (an ISO date). Returns "ADD", "CHANGE" (an old value was closed) or "NOOP". */
  set(subject, relation, object, when) {
    const current = this.facts.filter((f) => f.subject.toLowerCase() === subject.toLowerCase() && f.relation === relation && f.valid_to === null);
    if (current.some((f) => f.object.toLowerCase() === object.toLowerCase())) return "NOOP";
    if (RELATIONS[relation]) for (const fact of current) fact.valid_to = when;
    this.facts.push({ subject, relation, object, valid_from: when, valid_to: null });
    this.save();
    return RELATIONS[relation] && current.length ? "CHANGE" : "ADD";
  }

  /** The facts that were true on `date` (ISO dates compare as strings). */
  asOf(date) { return this.facts.filter((f) => f.valid_from <= date && (f.valid_to === null || date < f.valid_to)); }

  current() { return this.facts.filter((f) => f.valid_to === null); }

  history(subject, relation) { return this.facts.filter((f) => f.subject.toLowerCase() === subject.toLowerCase() && f.relation === relation); }

  /** Current facts within `hops` steps of an entity (edges are followed in both directions, as in Module 7). */
  neighbourhood(entity, hops = 2) {
    const seen = new Set([entity.toLowerCase()]);
    let frontier = new Set(seen);
    const found = [];
    for (let i = 0; i < hops; i++) {
      const next = new Set();
      for (const fact of this.current()) {
        const a = fact.subject.toLowerCase(), b = fact.object.toLowerCase();
        if ((frontier.has(a) || frontier.has(b)) && !found.includes(fact)) {
          found.push(fact);
          for (const name of [a, b]) if (!seen.has(name)) next.add(name);
        }
      }
      for (const name of next) seen.add(name);
      frontier = next;
    }
    return found;
  }
}
