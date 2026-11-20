// RAG generation helpers (Module 5): numbered sources, an answer that cites them, and an LLM reranker.
//
// Shared building block. Layers: llm_client.mjs -> retrieval.mjs (find chunks) -> rag.mjs (use them) -> m05_* lessons.
// `hits` are arrays of [score, chunk] pairs, as returned by Retriever.search.
import { chat } from "./llm_client.mjs";

export const ANSWER_SYSTEM =
  "Answer the question using ONLY the numbered sources. Cite the sources you used like [1] or [2][3]. " +
  "If the sources do not contain the answer, say that you do not know based on the handouts. Be concise.";

/** Number the retrieved chunks so the model can cite them: [1] file > section, then the text. */
export const formatSources = (hits, maxChars = 1200) =>
  hits.map(([, chunk], i) => `[${i + 1}] ${chunk.doc_id} > ${chunk.section}\n${chunk.text.slice(0, maxChars)}`).join("\n\n");

/** Augment and generate: put the sources in the prompt and answer from them only. */
export async function answerWithSources(question, hits, system = ANSWER_SYSTEM, facts = "") {
  if (!hits.length) return "I do not know based on the handouts (nothing relevant was found).";
  // `facts` (optional): extra lines from a knowledge graph (Module 7), shown before the question.
  const graph = facts ? `Graph facts (relations between the entities in the sources):\n${facts}\n\n` : "";
  const messages = [{ role: "system", content: system },
    { role: "user", content: `Sources:\n${formatSources(hits)}\n\n${graph}Question: ${question}` }];
  return ((await chat(messages, { temperature: 0.2 })).content ?? "").trim();
}

/**
 * Second stage: let the LLM read the candidates and score how well each answers the question (0-10).
 * Retrieval is cheap and wide (many candidates); reranking is slower and precise (a few are kept).
 * Returns the best k as [llm score, chunk]. If the model's reply cannot be parsed, the original order stays.
 */
export async function rerank(question, hits, k = 5) {
  if (hits.length <= 1) return hits.slice(0, k);
  const passages = hits.map(([, chunk], i) => `[${i + 1}] ${chunk.section}\n${chunk.text.slice(0, 500)}`).join("\n\n");
  const prompt = `Question: ${question}\n\nPassages:\n${passages}\n\n` +
    "Score each passage from 0 (irrelevant) to 10 (answers the question directly). " +
    `Reply with JSON only: {"scores": [one number per passage, in order, ${hits.length} numbers]}`;
  for (let attempt = 0; attempt < 2; attempt++) {
    const raw = ((await chat([{ role: "user", content: prompt }], { temperature: 0 })).content ?? "").trim();
    try {
      const scores = JSON.parse(raw.match(/\{[\s\S]*\}/)?.[0] ?? "null")?.scores;
      if (Array.isArray(scores) && scores.length === hits.length) {
        return hits.map(([, chunk], i) => [Number(scores[i]), chunk, i])
          .sort((a, b) => b[0] - a[0] || a[2] - b[2]).slice(0, k).map(([score, chunk]) => [score, chunk]);
      }
    } catch { /* unparsable reply: try again, then keep the original order */ }
  }
  return hits.slice(0, k);
}
