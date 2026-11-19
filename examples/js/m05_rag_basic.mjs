// Module 5 lesson: naive RAG, end to end.
//
// Index the handouts (chunk, embed), retrieve the chunks closest to the question, put them in the prompt,
// answer with citations. Run:  node examples/js/m05_rag_basic.mjs ["your question"]
import { pathToFileURL } from "node:url";
import { answerWithSources } from "./rag.mjs";
import { loadRetriever } from "./retrieval.mjs";

// Cosine scores are only comparable within ONE embedding model: unrelated text scores about 0.1 with
// Azure text-embedding-3-small but about 0.4 with nomic. Calibrate the threshold for your model.
const MIN_SCORE = Number(process.env.RAG_MIN_SCORE ?? 0.25);

export async function ask(retriever, question, k = 4) {
  const dense = retriever.store !== null;
  let hits = await retriever.search(question, k, { mode: dense ? "dense" : "bm25" });
  if (dense) hits = hits.filter(([score]) => score >= MIN_SCORE); // too weak a match = not found
  console.log(`\nQ: ${question}`);
  hits.forEach(([score, chunk], i) => console.log(`  [${i + 1}] ${score.toFixed(2)}  ${chunk.doc_id} > ${chunk.section}`));
  if (!hits.length) console.log("  (nothing above the score threshold)");
  const answer = await answerWithSources(question, hits);
  console.log(`A: ${answer}`);
  return answer;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const retriever = await loadRetriever();
  const questions = process.argv.slice(2).length ? process.argv.slice(2) : [
    "What is the difference between reflection and evaluator-optimizer?",
    "How can I continue a conversation across several run_agent calls?",
    "What is the capital of Australia?", // not in the handouts: the right answer is "I do not know"
  ];
  for (const question of questions) await ask(retriever, question);
}
