// Module 9 lesson: long-term memory as tools. The agent itself decides what to remember, recall and forget.
//
// Four SESSIONS with the same user: every session starts with an empty message list, so anything the agent knows beyond
// the current conversation comes from the memory store (examples/.memory/demo.json, deleted at the start so that the lesson
// is repeatable). `remember` reconciles: a new city UPDATES the old one instead of adding a contradiction. Run:
//     node examples/js/m09_memory_tools.mjs
import { rmSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { runAgent } from "./agent.mjs";
import { MemoryStore } from "./memory.mjs";

let store = null; // opened below; the tools use it

const SYSTEM = "You are a personal assistant with long-term memory that lasts across sessions. " +
  "When the user tells you something worth keeping (identity, preferences, constraints, plans), call remember once per fact, with ONE short fact in the third person, stated as a current state (not an event). " +
  "Before you answer anything personal (suggestions, planning), call recall first. " +
  "When the user asks you to forget something, call recall to find the memory and then forget with its id. " +
  "Do not store small talk or one-off requests.";

const tools = [
  { name: "remember", description: "Store one durable fact about the user. Reconciles with what is already known (an update replaces an old fact).",
    parameters: { type: "object", properties: { fact: { type: "string", description: "One short sentence in the third person, e.g. 'Dana lives in Vienna'" } }, required: ["fact"] },
    async run({ fact }) {
      const [action, item] = await store.remember(fact, "chat");
      console.log(`      [remember] '${fact}' -> ${action}` + (item ? ` ${item.id}: '${item.text}'` : ""));
      return item ? `${action}: ${item.text}` : action;
    } },
  { name: "recall", description: "Search the long-term memory about the user by meaning. Returns memories with their ids.",
    parameters: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
    async run({ query }) {
      const hits = await store.search(query, 4);
      console.log(`      [recall] '${query}' -> ${hits.length} memories`);
      return hits.map(([, m]) => `[${m.id}] ${m.text}`).join("\n") || "No memories found.";
    } },
  { name: "forget", description: "Delete one memory by its id (get the id from recall).",
    parameters: { type: "object", properties: { memory_id: { type: "string" } }, required: ["memory_id"] },
    run({ memory_id }) {
      const deleted = store.delete(memory_id);
      console.log(`      [forget] ${memory_id} -> ${deleted ? "deleted" : "not found"}`);
      return deleted ? "Forgotten." : "Not found.";
    } },
];

const SESSIONS = [
  ["Session 1: the user introduces themself", ["Hi! I'm Dana, I live in Budapest and I'm vegetarian.", "I'm preparing a talk about RAG for September."]],
  ["Session 2: a new conversation, nothing in the message list", ["Suggest a dinner idea for tonight."]],
  ["Session 3: something changes", ["By the way, I moved to Vienna last month."]],
  ["Session 4: the user asks to forget", ["Please forget what you know about my diet."]],
];

const showStore = () => console.log("   memory file now:", store.items.map((m) => `${m.id}='${m.text}'`).join("; ") || "(empty)");

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  rmSync(new MemoryStore("demo").path, { force: true });
  store = new MemoryStore("demo");
  for (const [title, turns] of SESSIONS) {
    console.log(`\n${title}`);
    const messages = []; // a NEW conversation each time: only the memory store connects the sessions
    for (const turn of turns) {
      console.log(`   user: ${turn}`);
      console.log("   agent:", (await runAgent(turn, tools, { system: SYSTEM, maxSteps: 6, messages })).replaceAll("\n", " ").slice(0, 300));
    }
    showStore();
  }
}
