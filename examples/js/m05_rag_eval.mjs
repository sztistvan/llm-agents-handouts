// Module 5 lesson: measure retrieval instead of guessing. Recall@k and MRR on a golden question set.
//
// examples/rag_golden.json lists questions and the sections that answer them. A retrieval "hit" means one of the
// expected sections is among the top k chunks. Run:  node examples/js/m05_rag_eval.mjs [--rerank]
// (--rerank adds the LLM reranker: one extra model call per question.)
import { pathToFileURL } from "node:url";
import { rerank } from "./rag.mjs";
import { firstHitRank, loadGolden, loadRetriever } from "./retrieval.mjs";

const KS = [1, 3, 5];

async function evaluate(retriever, golden, method) {
  const ranks = [];
  for (const item of golden) {
    const hits = method === "hybrid+rerank"
      ? await rerank(item.question, await retriever.search(item.question, 20, { mode: "hybrid" }), 5)
      : await retriever.search(item.question, 5, { mode: method });
    ranks.push([item.question, firstHitRank(hits, item.expect), hits]);
  }
  const n = ranks.length;
  const scores = Object.fromEntries(KS.map((k) => [`recall@${k}`, ranks.filter(([, r]) => r && r <= k).length / n]));
  scores.MRR = ranks.reduce((s, [, r]) => s + (r ? 1 / r : 0), 0) / n;
  return [scores, ranks];
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const retriever = await loadRetriever();
  const golden = loadGolden();
  const methods = ["bm25", ...(retriever.store ? ["dense", "hybrid"] : [])];
  if (process.argv.includes("--rerank") && retriever.store) methods.push("hybrid+rerank");
  console.log(`${golden.length} golden questions, ${retriever.chunks.length} chunks\n`);
  console.log("method".padEnd(14) + KS.map((k) => `recall@${k}`.padStart(10)).join("") + "MRR".padStart(8));
  const results = {};
  for (const method of methods) {
    const [scores, ranks] = await evaluate(retriever, golden, method);
    results[method] = ranks;
    console.log(method.padEnd(14) + KS.map((k) => scores[`recall@${k}`].toFixed(2).padStart(10)).join("") + scores.MRR.toFixed(2).padStart(8));
  }

  const best = methods[methods.length - 1];
  const misses = results[best].filter(([, rank]) => rank === null);
  console.log(`\nQuestions where '${best}' misses the expected section in the top 5 (${misses.length
    ? "read these: they show what to fix" : "none: the golden set no longer discriminates, add harder questions"}):`);
  for (const [question, , hits] of misses) {
    console.log(`- ${question}`);
    for (const [, chunk] of hits.slice(0, 3)) console.log(`    got: ${chunk.doc_id} > ${chunk.section.split(" > ").pop()}`);
  }
}
