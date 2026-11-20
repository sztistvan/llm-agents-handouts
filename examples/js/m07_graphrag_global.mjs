// Module 7 lesson: GraphRAG global search. Questions about the WHOLE document set.
//
// "What are the main themes?" has no answer in any single chunk, and top-k retrieval returns only a few chunks. GraphRAG
// groups the graph into communities (label propagation here, Leiden in production systems), has an LLM summarize each, and
// answers broad questions from the summaries. A real system maps the question over each summary and combines the partial
// answers; here all summaries fit one prompt. Summaries are cached by the content of their community.
// Run:  node examples/js/m07_graphrag_global.mjs
import { pathToFileURL } from "node:url";
import { Graph } from "./graph_store.mjs";
import { chat } from "./llm_client.mjs";
import { answerWithSources } from "./rag.mjs";
import { loadRetriever } from "./retrieval.mjs";

const QUESTION = "What are the main themes of the handouts as a whole?";
const TOP = 8; // how many of the largest communities to summarize

async function answerGlobal(question, summaries) {
  const context = summaries.map((s, i) => `[${i + 1}] ${s.title}: ${s.summary}`).join("\n\n");
  const messages = [{ role: "system", content: "Answer the question using ONLY the community summaries below, which together " +
      "cover the whole document set. Name the themes you use by their title. Be concise." },
    { role: "user", content: `Community summaries:\n${context}\n\nQuestion: ${question}` }];
  return ((await chat(messages, { temperature: 0.2 })).content ?? "").trim();
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const retriever = await loadRetriever();
  const graph = Graph.open();
  const report = await graph.sync(retriever.chunks);
  if (report.extracted) console.log(`(extracted ${report.extracted} chunks first, see m07_graph_build)`);
  const indent = (text) => text.replaceAll("\n", "\n    ");

  const groups = graph.communities();
  console.log(`1. Communities: ${groups.length} groups of at least 3 entities; sizes of the largest: [${groups.slice(0, 10).map((g) => g.length).join(", ")}]`);
  groups.slice(0, TOP).forEach((members, i) => console.log(`   ${i + 1}. ${String(members.length).padStart(2)} entities, e.g. ${graph.memberNames(members).join(", ")}`));

  console.log(`\n2. One LLM call per community writes a title and a summary (cached; ${TOP} communities)`);
  const summaries = [];
  for (const members of groups.slice(0, TOP)) {
    const summary = await graph.summarize(members);
    if (summary) summaries.push(summary);
  }
  graph.save();
  for (const summary of summaries.slice(0, 4)) console.log(`   - ${summary.title}: ${summary.summary}`);

  console.log(`\n3. A global question: ${QUESTION}`);
  console.log("\n   Plain RAG (top-5 chunks):\n   ", indent(await answerWithSources(QUESTION, await retriever.search(QUESTION, 5))));
  console.log("\n   GraphRAG global (community summaries):\n   ", indent(await answerGlobal(QUESTION, summaries)));
}
