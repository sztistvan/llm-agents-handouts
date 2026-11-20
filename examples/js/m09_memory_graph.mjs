// Module 9 lesson: fact memory with history. Triples that know WHEN they were true.
//
// A text memory (m09_memory_tools) keeps one sentence per fact, and an update overwrites it: "Dana lives in Budapest" becomes
// "Dana lives in Vienna" and the past is gone. Here the facts are (subject, relation, object) triples with a validity period
// (valid_from, valid_to), extracted from the user's messages by an LLM that may use only a small list of relations (a tiny
// ontology, Module 7). A new value of a single-valued relation CLOSES the old fact instead of deleting it. That allows
// questions "as of" a date, and a walk over the connections (Module 7's neighbourhood) for "who does Dana work with?".
// Three dated sessions, 3 extraction calls and 1 answer. Run:  node examples/js/m09_memory_graph.mjs
import { rmSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { chat } from "./llm_client.mjs";
import { FactStore, MEMORY_DIR, RELATIONS, extractTriples } from "./memory.mjs";

const SESSIONS = [
  ["2025-03-01", ["I'm Dana. I live in Budapest and work at Contoso as a data engineer. I'm working on project Falcon, and I'm allergic to peanuts."]],
  ["2025-09-15", ["Big news: I moved to Vienna and I now work at Fabrikam. My colleague Marta works at Fabrikam too, and I'm working on project Osprey."]],
  ["2025-11-20", ["I got a dog called Rex, and I was promoted to senior data engineer."]],
];

const line = (f) => `${f.subject} --${f.relation}--> ${f.object}  (${f.valid_from} to ${f.valid_to ?? "now"})`;
const summary = (facts) => facts.filter((f) => f.subject === "Dana").map((f) => `${f.relation} ${f.object}`).join("; ");

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  rmSync(join(MEMORY_DIR, "dana.facts.json"), { force: true });
  const store = new FactStore("dana");
  console.log("Relations the extractor may use (true: one value at a time):", JSON.stringify(RELATIONS).replaceAll('"', "'").replaceAll(",", ", ").replaceAll(":", ": "));

  for (const [date, lines] of SESSIONS) {
    console.log(`\n${date}: ${lines[0]}`);
    for (const [subject, relation, object] of await extractTriples(lines.map((content) => ({ role: "user", content })), "Dana")) {
      console.log(`   ${store.set(subject, relation, object, date).padEnd(6)} ${subject} --${relation}--> ${object}`);
    }
  }

  console.log("\nThe history of where Dana lives and works (nothing was deleted):");
  for (const relation of ["lives_in", "works_at", "job_title"]) for (const fact of store.history("Dana", relation)) console.log("  ", line(fact));
  console.log("\nAs of 2025-06-01:", summary(store.asOf("2025-06-01")));
  console.log("Today          :", summary(store.current()));

  console.log("\nWho does Dana work with? The facts within 2 hops of 'Dana':");
  for (const fact of store.neighbourhood("Dana", 2)) console.log("  ", line(fact));

  const question = "Where did I live and work in June 2025, and where do I live and work now? Answer in two short lines.";
  const facts = store.facts.filter((f) => f.subject === "Dana" && ["lives_in", "works_at"].includes(f.relation)).map(line).join("\n");
  const reply = await chat([{ role: "system", content: "Answer only from these facts about the user:\n" + facts }, { role: "user", content: question }], { temperature: 0 });
  console.log(`\nQ: ${question}\nA: ${(reply.content ?? "").trim()}`);
}
