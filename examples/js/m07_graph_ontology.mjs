// Module 7 lesson: an ontology-guided graph, compared with the open one.
//
// examples/ontology.json is a small ontology for the handouts: classes with a taxonomy (a WorkflowPattern is a Pattern) and
// relations that say which classes they may connect (domain -> range). The lesson puts the ontology in the extraction
// prompt and then VALIDATES every answer: unknown classes and relations are dropped, and a relation whose endpoints break
// its domain or range is rejected with a reason. It compares the result with the open extraction of the same 6 chunks and
// prints the schema and the guided graph as Mermaid diagrams. 6 LLM calls; the output varies a little from run to run.
// Run:  node examples/js/m07_graph_ontology.mjs
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { Graph, jsonReply, mermaidDiagram, normalize } from "./graph_store.mjs";
import { ROOT, chunkMarkdown, loadMarkdown } from "./retrieval.mjs";

const ONTOLOGY = join(ROOT, "examples", "ontology.json");
const SECTIONS = ["Reflection vs. evaluator-optimizer", "9. Example: supervisor with workers as tools", "6. The agent loop, made reusable",
  "5. Swarm / handoff", "6. ReAct (reason + act)", "7. Debate and critic"];
const PALETTE = { Pattern: ["#dcfce7", "#15803d"], WorkflowPattern: ["#bbf7d0", "#15803d"], AgentPattern: ["#d9f99d", "#4d7c0f"],
  MultiAgentStructure: ["#a7f3d0", "#047857"], Component: ["#fef9c3", "#a16207"], File: ["#f1f5f9", "#475569"],
  Parameter: ["#ffedd5", "#c2410c"], Concept: ["#e0f2fe", "#0369a1"] };

/** A class and all its parents: a WorkflowPattern is also a Pattern. */
function ancestors(ontology, name) {
  const found = new Set();
  while (name) { found.add(name); name = ontology.classes[name].parent; }
  return found;
}

function systemPrompt(ontology) {
  const classes = Object.entries(ontology.classes).map(([name, spec]) => `- ${name}: ${spec.description}`).join("\n");
  const relations = Object.entries(ontology.relations)
    .map(([name, spec]) => `- ${name} (${spec.domain.join(" or ")} -> ${spec.range.join(" or ")}): ${spec.description}`).join("\n");
  return "You extract a knowledge graph from a passage of technical documentation about building LLM agents. Use ONLY this ontology.\n" +
    `Classes:\n${classes}\nRelations (name, domain -> range):\n${relations}\n` +
    'Reply with JSON only: {"entities": [{"name": "...", "class": "..."}], "relations": [{"source": "...", "relation": "...", "target": "..."}]}\n' +
    "Rules: at most 8 entities with short, canonical, lower-case, singular names; every entity gets exactly one class from the list " +
    "(Concept only if nothing else fits); every relation uses exactly one relation name from the list and two of your entities; " +
    "leave out anything that does not fit the ontology.";
}

/** Keep what follows the ontology. Returns { entities, accepted, rejected, notes }. */
function validate(data, ontology) {
  const byLower = new Map(Object.keys(ontology.classes).map((name) => [name.toLowerCase(), name]));
  const entities = new Map();
  const notes = [];
  for (const item of data.entities ?? []) {
    if (item && typeof item === "object" && typeof item.name === "string") {
      const id = normalize(item.name);
      let cls = byLower.get(String(item.class ?? "").trim().toLowerCase());
      if (id && !entities.has(id)) {
        if (!cls) { notes.push(`class '${item.class}' of '${item.name}' is not in the ontology: it became Concept`); cls = "Concept"; }
        entities.set(id, [item.name.trim().toLowerCase(), cls]);
      }
    }
  }
  const accepted = [];
  const rejected = [];
  for (const item of data.relations ?? []) {
    if (!item || typeof item !== "object" || !["source", "relation", "target"].every((k) => typeof item[k] === "string")) continue;
    const triple = [item.source, item.relation, item.target];
    const name = item.relation.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
    const source = normalize(item.source), target = normalize(item.target);
    const spec = ontology.relations[name];
    if (!spec) {
      rejected.push([triple, `'${item.relation}' is not a relation of the ontology`]);
    } else if (!entities.has(source) || !entities.has(target)) {
      rejected.push([triple, "an endpoint is not one of the extracted entities"]);
    } else if (!spec.domain.some((d) => ancestors(ontology, entities.get(source)[1]).has(d))) {
      rejected.push([triple, `domain: a ${entities.get(source)[1]} cannot be the source of ${name} (needs ${spec.domain.join(" or ")})`]);
    } else if (!spec.range.some((r) => ancestors(ontology, entities.get(target)[1]).has(r))) {
      rejected.push([triple, `range: a ${entities.get(target)[1]} cannot be the target of ${name} (needs ${spec.range.join(" or ")})`]);
    } else {
      accepted.push([source, name, target]);
    }
  }
  return { entities, accepted, rejected, notes };
}

/** The ontology as a Mermaid class diagram: inheritance for the taxonomy, an arrow per allowed domain -> range. */
function schemaDiagram(ontology) {
  const lines = ["classDiagram"];
  for (const [name, spec] of Object.entries(ontology.classes)) if (spec.parent) lines.push(`    ${spec.parent} <|-- ${name}`);
  for (const [name, spec] of Object.entries(ontology.relations)) {
    for (const d of spec.domain) for (const r of spec.range) lines.push(`    ${d} --> ${r} : ${name}`);
  }
  return lines.join("\n");
}

const block = (title, text) => console.log(`\n${title}\n\`\`\`mermaid\n${text}\n\`\`\``);
const cmp3 = (a, b) => (a.join("\x01") < b.join("\x01") ? -1 : a.join("\x01") > b.join("\x01") ? 1 : 0);

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const ontology = JSON.parse(readFileSync(ONTOLOGY, "utf8"));
  const chunks = loadMarkdown().flatMap((doc) => chunkMarkdown(doc));
  const graph = Graph.open();
  await graph.sync(chunks);
  const picked = SECTIONS.map((s) => chunks.find((c) => c.section.endsWith(s)));
  const tail = (c) => c.section.split(" > ").pop();

  console.log(`1. The ontology (${Object.keys(ontology.classes).length} classes, ${Object.keys(ontology.relations).length} relations)`);
  for (const [name, spec] of Object.entries(ontology.classes)) {
    if (spec.parent) continue;
    const children = Object.entries(ontology.classes).filter(([, s]) => s.parent === name).map(([n]) => n);
    console.log(`   ${name}${children.length ? `  (subclasses: ${children.join(", ")})` : ""}`);
  }
  for (const [name, spec] of Object.entries(ontology.relations)) console.log(`   ${name}: ${spec.domain.join(" or ")} -> ${spec.range.join(" or ")}`);
  block("   As a diagram:", schemaDiagram(ontology));

  console.log(`\n2. Open extraction (Modules 7.4) vs ontology-guided extraction of the same ${picked.length} chunks`);
  console.log(`   ${"chunk".padEnd(44)}${"open: ent / rel".padStart(17)}${"guided: ent / ok / rejected".padStart(30)}`);
  const allEntities = new Map();
  const allEdges = new Map();
  const perChunk = new Map();
  const rejections = [];
  const openLabels = new Set(), guidedLabels = new Set();
  const totals = { openE: 0, openR: 0, e: 0, ok: 0, bad: 0, fixed: 0 };
  for (const chunk of picked) {
    const record = graph.extractions[chunk.hash];
    const data = await jsonReply([{ role: "system", content: systemPrompt(ontology) },
      { role: "user", content: `Section: ${chunk.section}\n\nPassage:\n${chunk.text.slice(0, 3000)}` }]);
    const { entities, accepted, rejected, notes } = validate(data && typeof data === "object" ? data : {}, ontology);
    perChunk.set(chunk.hash, { entities, accepted });
    for (const [id, value] of entities) if (!allEntities.has(id)) allEntities.set(id, value);
    for (const edge of accepted) allEdges.set(edge.join("\x01"), edge);
    rejections.push(...rejected.map(([t, why]) => [tail(chunk), t, why]));
    for (const r of record.relations) openLabels.add(r.r.split(/[-_\s]+/).filter(Boolean).join(" "));
    for (const [, name] of accepted) guidedLabels.add(name);
    totals.openE += record.entities.length; totals.openR += record.relations.length;
    totals.e += entities.size; totals.ok += accepted.length; totals.bad += rejected.length; totals.fixed += notes.length;
    console.log(`   ${tail(chunk).slice(0, 42).padEnd(44)}${String(record.entities.length).padStart(8)} /${String(record.relations.length).padStart(3)}` +
      `${String(entities.size).padStart(14)} /${String(accepted.length).padStart(3)} /${String(rejected.length).padStart(3)}`);
  }
  console.log(`   ${"total".padEnd(44)}${String(totals.openE).padStart(8)} /${String(totals.openR).padStart(3)}${String(totals.e).padStart(14)} /${String(totals.ok).padStart(3)} /${String(totals.bad).padStart(3)}`);
  console.log(`\n   distinct relation labels: open ${openLabels.size} (free text), guided ${guidedLabels.size} (at most ${Object.keys(ontology.relations).length})`);
  const classes = {};
  for (const [, cls] of allEntities.values()) classes[cls] = (classes[cls] ?? 0) + 1;
  console.log("   guided entities by class:", Object.entries(classes).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).map(([k, v]) => `${k} ${v}`).join(", "));
  console.log(`   relations rejected by the validator: ${totals.bad} of ${totals.ok + totals.bad}; classes the model invented and the validator repaired: ${totals.fixed}`);
  console.log("   some rejections (this is where the ontology bites):");
  for (const [section, triple, why] of rejections.slice(0, 6)) console.log(`     [${section.slice(0, 28)}] ${triple[0]} --${triple[1]}--> ${triple[2]}: ${why}`);

  const first = perChunk.get(picked[0].hash);
  const edgesOf = (edges) => [...edges].sort(cmp3).map(([s, r, t]) => [s, r.replaceAll("_", " "), t]);
  block("\n3. The guided graph of the first chunk (colours are ontology classes; compare it with the open graph of m07_graph_diagrams):",
    mermaidDiagram([...first.entities].sort(cmp3).map(([id, [name, cls]]) => [id, name, cls]), edgesOf(new Map(first.accepted.map((e) => [e.join("\x01"), e])).values()), "LR", PALETTE));
  const used = [...new Set([...allEdges.values()].flatMap(([s, , t]) => [s, t]))].sort();
  block(`\n4. The guided graph of all ${picked.length} chunks together:`,
    mermaidDiagram(used.map((id) => [id, allEntities.get(id)[0], allEntities.get(id)[1]]), edgesOf(allEdges.values()), "LR", PALETTE));
}
