// Module 7 lesson: build a knowledge graph from the handouts.
//
// An LLM reads every chunk once and lists the entities (concepts, patterns, components, files, ...) and the relations
// between them. The result is a graph in which every node and edge remembers the chunks it came from. This lesson shows
// the cost, what comes out, what is still wrong (entity resolution), and how an update touches only the changed chunk.
// The first run makes one LLM call per chunk (about a minute on Azure); later runs reuse the saved graph.
// Run:  node examples/js/m07_graph_build.mjs
import { basename } from "node:path";
import { pathToFileURL } from "node:url";
import { Graph } from "./graph_store.mjs";
import { chunkMarkdown, loadMarkdown, sha } from "./retrieval.mjs";

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const chunks = loadMarkdown().flatMap((doc) => chunkMarkdown(doc));
  const graph = Graph.open();

  console.log(`1. Extraction: one LLM call per chunk (${chunks.length} chunks), cached by chunk hash in ${basename(graph.path)}`);
  const report = await graph.sync(chunks);
  graph.save();
  console.log(`   ${report.extracted} chunks extracted, ${report.kept} reused from the cache, ${report.failed} failed, ${report.seconds.toFixed(1)} s`);

  const stats = graph.stats();
  console.log("\n2. What came out");
  console.log(`   ${stats.entities} entities and ${stats.relations} relations from ${stats.chunks} chunks ` +
    `(${(stats.entities / stats.chunks).toFixed(1)} entities and ${(stats.relations / stats.chunks).toFixed(1)} relations per chunk)`);
  console.log("   entity types:", Object.entries(stats.types).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).map(([kind, n]) => `${kind} ${n}`).join(", "));
  console.log("   best connected entities (name: relations, chunks):");
  for (const [name, relations, inChunks] of graph.topEntities(8)) {
    console.log(`     ${name.padEnd(22)} ${String(relations).padStart(3)} relations, in ${inChunks} chunks`);
  }
  const target = chunks.find((c) => c.section.endsWith("Reflection vs. evaluator-optimizer"));
  const record = graph.extractions[target.hash];
  console.log(`   one chunk's extraction (${target.section.split(" > ").pop()}):`);
  console.log("     entities: ", record.entities.map((e) => `${e.name} (${e.type})`).join(", "));
  console.log("     relations:", record.relations.slice(0, 5).map((r) => `${r.s} --${r.r}--> ${r.t}`).join("; "));

  console.log("\n3. Entity resolution: the same thing under several names is the main quality problem");
  console.log(`   merged automatically (plural forms): ${stats.merged_variants}, for example`,
    graph.merged.slice(0, 4).map(([a, b]) => `'${a}' -> '${b}'`).join(", "));
  console.log("   still suspicious (a person, a rule or an LLM has to decide whether these are one entity):");
  for (const [similarity, a, b] of graph.nearDuplicates(0.6, 6)) console.log(`     ${similarity.toFixed(2)}  '${a}'  ~  '${b}'`);

  console.log("\n4. An update: change ONE chunk and only that chunk is extracted again (on a copy; the saved graph stays)");
  const text = `${target.text}\n\nA third variant, tree of thought, explores several candidate answers in parallel and keeps the best one.`;
  const changed = chunks.map((c) => (c.hash === target.hash ? { ...c, text, hash: sha(`${c.section}\n${text}`) } : c));
  const trial = graph.copy();
  const update = await trial.sync(changed);
  console.log(`   re-extracted ${update.extracted}, kept ${update.kept}, removed the record of ${update.removed} (the old text)`);
  const before = new Set([...graph.nodes.values()].map((n) => n.name));
  trial.stats();
  const after = new Set([...trial.nodes.values()].map((n) => n.name));
  const fmt = (set) => (set.length ? `[${set.map((x) => `'${x}'`).join(", ")}]` : "none");
  console.log(`   entities ${stats.entities} -> ${after.size}; new: ${fmt([...after].filter((x) => !before.has(x)).sort())}; ` +
    `no longer in the graph: ${fmt([...before].filter((x) => !after.has(x)).sort())}`);
  console.log("   (re-extracting the chunk can change more than the sentence you added: an LLM does not give the same answer twice)");
  console.log("   every fact knows its source chunk, so nothing else had to be touched: the same idea as the sync of Module 6");
}
