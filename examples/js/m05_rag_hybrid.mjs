// Module 5 lesson: better retrieval. Dense vs keyword (BM25) vs hybrid, a metadata filter, and reranking.
//
// Run:  node examples/js/m05_rag_hybrid.mjs
import { pathToFileURL } from "node:url";
import { answerWithSources, rerank } from "./rag.mjs";
import { loadRetriever } from "./retrieval.mjs";

const QUERIES = [
  ["meaning, few shared words", "how does the model remember earlier turns of a conversation?"],
  ["an exact identifier", "model_dump"],
];

const show = (label, hits) => console.log(`  ${label.padEnd(6)}`, hits.map(([score, chunk]) =>
  `${score.toFixed(2)} ${chunk.doc_id.slice(0, 2)}:${chunk.section.split(" > ").pop().slice(0, 32)}`).join(" | "));

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const retriever = await loadRetriever();

  const modes = retriever.store ? ["dense", "bm25", "hybrid"] : ["bm25"]; // without embeddings only keywords exist
  console.log("1. Three ways to search (top 3 per method; score scales differ: cosine, BM25, RRF)");
  if (modes.length === 1) console.log("   (no embedding model configured: only the keyword row is real here)");
  for (const [kind, query] of QUERIES) {
    console.log(`\nQ (${kind}): ${query}`);
    for (const mode of modes) show(mode, await retriever.search(query, 3, { mode }));
  }

  console.log("\n2. A metadata filter: only chunks of the patterns handout (03-patterns.md)");
  const onlyPatterns = (chunk) => chunk.doc_id === "03-patterns.md";
  show("hybrid", await retriever.search("when should a second call check the first answer?", 3, { where: onlyPatterns }));

  console.log("\n3. Two stages: retrieve wide (20 candidates), let the LLM rerank, keep the best 4, answer");
  const question = "What is the difference between reflection and evaluator-optimizer?";
  const candidates = await retriever.search(question, 20, { mode: "hybrid" });
  const best = await rerank(question, candidates, 4);
  show("before", candidates.slice(0, 4));
  show("after", best);
  console.log("A:", await answerWithSources(question, best));
}
