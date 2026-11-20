// Module 7 lesson: GraphRAG local search, compared honestly with plain RAG.
//
// Local search uses the graph in two ways: the RELATIONS around the entities of the question go into the prompt as compact
// facts, and the graph's entity-to-chunk links make sure that every entity named in the question brings its own best chunk.
// Part 1 follows one multi-hop question. Part 2 measures, on 13 questions that need evidence from several sections, whether
// the context covers ALL of the evidence (no LLM calls needed). Plain retrieval is shown at several context sizes, because
// more context is the obvious competitor.  Run:  node examples/js/m07_graphrag.mjs
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { Graph, formatFacts } from "./graph_store.mjs";
import { answerWithSources } from "./rag.mjs";
import { ROOT, isHit, loadRetriever } from "./retrieval.mjs";

const GOLDEN = join(ROOT, "examples", "graph_golden.json");
const QUESTION = "Which Module 2 component runs each worker of the Module 4 supervisor?"; // chosen because plain top-5 misses it

/** Does the context contain ALL the sections needed (and what share of them)? */
function evidence(chunks, expectAll) {
  const covered = expectAll.map((pair) => chunks.some((c) => isHit(c, [pair])));
  return [covered.every(Boolean), covered.filter(Boolean).length / covered.length];
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const retriever = await loadRetriever();
  const graph = Graph.open();
  const report = await graph.sync(retriever.chunks);
  if (report.extracted) {
    console.log(`(extracted ${report.extracted} chunks first, see m07_graph_build)`);
    graph.save();
  }
  const golden = JSON.parse(readFileSync(GOLDEN, "utf8"));
  const item = golden.find((g) => g.question === QUESTION);
  const indent = (text) => text.replaceAll("\n", "\n    ");

  console.log(`1. One multi-hop question\n   ${QUESTION}`);
  const plain = await retriever.search(QUESTION, 5);
  const context = await graph.localContext(QUESTION, retriever);
  console.log("   entities found in the question and in the top-5 chunks (the seeds):", context.seeds.slice(0, 8).join(", "));
  console.log("   the graph's facts around them (best 8 of", context.facts.length, "):");
  console.log(formatFacts(context.facts, 8).split("\n").map((line) => `     ${line}`).join("\n"));
  const top5 = new Set(plain.map(([, c]) => c.hash));
  console.log("   context chunks (top-5 by search, plus the ones the graph added):");
  for (const chunk of context.chunks) {
    console.log(`     ${top5.has(chunk.hash) ? "top-5" : "GRAPH"}  ${chunk.doc_id.slice(0, 2)} > ${chunk.section.split(" > ").pop()}`);
  }
  const plainOk = evidence(plain.map(([, c]) => c), item.expect_all)[0];
  const graphOk = evidence(context.chunks, item.expect_all)[0];
  console.log(`   needed: ${JSON.stringify(item.expect_all.map(([d, s]) => `${d.slice(0, 2)} > ${s}`)).replace(/"/g, "'").replace(/,/g, ", ")}`);
  console.log(`   all needed sections present: plain top-5 ${plainOk ? "yes" : "NO"}, graph local ${graphOk ? "yes" : "NO"}`);
  console.log("\n   Plain RAG answer:\n   ", indent(await answerWithSources(QUESTION, plain)));
  console.log("\n   GraphRAG answer (facts + chunks):\n   ",
    indent(await answerWithSources(QUESTION, context.chunks.map((c) => [0, c]), undefined, formatFacts(context.facts, 15))));

  console.log("\n2. Evidence coverage on the golden questions (every needed section must be in the context)");
  const methods = {
    "plain top-5": async (q) => (await retriever.search(q, 5)).map(([, c]) => c),
    "plain top-8": async (q) => (await retriever.search(q, 8)).map(([, c]) => c),
    "plain top-10": async (q) => (await retriever.search(q, 10)).map(([, c]) => c),
    "graph local (5 + up to 5)": async (q) => (await graph.localContext(q, retriever)).chunks,
  };
  console.log(`   ${"method".padEnd(27)}${"multi-hop: all evidence".padStart(25)}${"evidence recall".padStart(17)}${"avg context".padStart(13)}${"single-hop".padStart(12)}`);
  for (const [name, find] of Object.entries(methods)) {
    const row = {};
    for (const kind of ["multi-hop", "single"]) {
      row[kind] = [];
      for (const g of golden.filter((x) => x.kind === kind)) {
        const chunks = await find(g.question);
        const [ok, share] = evidence(chunks, g.expect_all);
        row[kind].push([ok, share, chunks.reduce((s, c) => s + c.text.length, 0)]);
      }
    }
    const multi = row["multi-hop"], single = row.single;
    const sum = (rows, i) => rows.reduce((s, r) => s + Number(r[i]), 0);
    console.log(`   ${name.padEnd(27)}${String(sum(multi, 0)).padStart(19)}/${String(multi.length).padEnd(5)}${(sum(multi, 1) / multi.length).toFixed(2).padStart(17)}` +
      `${String(Math.floor(sum(multi, 2) / multi.length)).padStart(9)} chars${String(sum(single, 0)).padStart(8)}/${single.length}`);
  }
  console.log("\n   Read it with care: 10 questions are few, and 'more context' (top-8, top-10) is the obvious competitor.");
}
