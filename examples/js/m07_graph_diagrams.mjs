// Module 7 lesson: look at the graph. Mermaid diagrams generated from the real graph of the handouts.
//
// Five pictures: one chunk's extraction; two chunks that merge through an entity they share; the neighbourhood of one
// entity; how the graph grows as chunks are added (numbers, because the whole graph cannot be drawn); and what entity
// resolution does. Each diagram is printed as a ```mermaid block: paste it into a markdown file (GitHub renders it) or
// into https://mermaid.live. No LLM calls if the graph was built before (see m07_graph_build).
// Run:  node examples/js/m07_graph_diagrams.mjs
import { pathToFileURL } from "node:url";
import { Graph, mermaidDiagram } from "./graph_store.mjs";
import { chunkMarkdown, loadMarkdown } from "./retrieval.mjs";

const show = (title, text) => console.log(`\n${title}\n\`\`\`mermaid\n${text}\n\`\`\``);
const cmpFact = (a, b) => (a.join("\x01") < b.join("\x01") ? -1 : a.join("\x01") > b.join("\x01") ? 1 : 0);

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const chunks = loadMarkdown().flatMap((doc) => chunkMarkdown(doc));
  const graph = Graph.open();
  await graph.sync(chunks);
  graph.stats();
  const first = (suffix) => chunks.find((c) => c.section.endsWith(suffix));
  const last = (c) => c.section.split(" > ").pop();

  const one = first("Reflection vs. evaluator-optimizer");
  const record = graph.extractions[one.hash];
  console.log(`1. One chunk (${one.doc_id} > ${last(one)}): ${record.entities.length} entities, ${record.relations.length} relations`);
  show("   Its extraction as a graph:", graph.mermaidChunks([one.hash]));

  const a = first("9. Example: supervisor with workers as tools"), b = first("6. The agent loop, made reusable");
  const inB = new Set(graph.chunkEntities.get(b.hash));
  const shared = graph.chunkEntities.get(a.hash).filter((e) => inB.has(e)).sort();
  console.log(`\n2. Two chunks from different handouts: ${a.doc_id} > ${last(a)} (solid) and ${b.doc_id} > ${last(b)} (dashed)`);
  console.log(`   entities in both, where the two extractions grow together: ${shared.join(", ") || "none"}`);
  show("   The merged graph (thick lines: a fact found in both chunks):", graph.mermaidChunks([a.hash, b.hash]));

  show("\n3. The neighbourhood of one entity, 'supervisor', one hop (the best supported facts):",
    graph.mermaidNeighbourhood("supervisor", 1, 24));

  console.log("\n4. Growth: the graph as chunks are added in document order (the whole graph is too big to draw)");
  console.log(`   ${"chunks".padStart(7)}${"entities".padStart(10)}${"relations".padStart(11)}${"relations/entity".padStart(18)}${"connected parts".padStart(17)}${"largest part".padStart(14)}`);
  for (const count of [1, 4, 16, 33, chunks.length]) {
    const part = new Graph(graph.path);
    part.extractions = Object.fromEntries(chunks.slice(0, count).filter((c) => c.hash in graph.extractions).map((c) => [c.hash, graph.extractions[c.hash]]));
    const stats = part.stats(), sizes = part.components();
    console.log(`   ${String(count).padStart(7)}${String(stats.entities).padStart(10)}${String(stats.relations).padStart(11)}` +
      `${(stats.relations / stats.entities).toFixed(2).padStart(18)}${String(sizes.length).padStart(17)}${String(sizes[0]).padStart(14)}`);
  }

  // entity resolution: the pair of variants with the most facts (up to 10) before and after merging
  const rawNames = new Map();
  const rawFacts = new Map();
  for (const h of Object.keys(graph.extractions).sort()) {
    for (const e of graph.extractions[h].entities) if (!rawNames.has(e.id)) rawNames.set(e.id, [e.name, e.type]);
    for (const r of graph.extractions[h].relations) {
      const fact = [r.s, r.r.split(/[-_\s]+/).filter(Boolean).join(" "), r.t];
      rawFacts.set(fact.join("\x01"), fact);
    }
  }
  const factsOf = (...ids) => [...rawFacts.values()].filter((f) => ids.includes(f[0]) || ids.includes(f[2])).sort(cmpFact);
  const candidates = graph.merged.map(([alias, canon]) => [factsOf(alias, canon).length, alias, canon]).filter((c) => c[0] <= 10);
  const [, alias, canon] = candidates.reduce((best, c) => (c[0] > best[0] || (c[0] === best[0] && c[1] > best[1]) ? c : best));
  const before = factsOf(alias, canon);
  const idsBefore = [...new Set([...before.flatMap((f) => [f[0], f[2]]), alias, canon])].sort();
  const node = (i) => [i, rawNames.get(i)[0], rawNames.get(i)[1]];
  show(`\n5. Entity resolution: '${rawNames.get(alias)[0]}' and '${rawNames.get(canon)[0]}' are two nodes before merging`,
    mermaidDiagram(idsBefore.map(node), before));
  const mergedMap = new Map();
  for (const [s, r, t] of before) { const f = [s === alias ? canon : s, r, t === alias ? canon : t]; mergedMap.set(f.join("\x01"), f); }
  const mergedFacts = [...mergedMap.values()].sort(cmpFact);
  const idsAfter = [...new Set([...mergedFacts.flatMap((f) => [f[0], f[2]]), canon])].sort();
  show("   ... and one node after merging (the facts of both are now together):", mermaidDiagram(idsAfter.map(node), mergedFacts));
}
