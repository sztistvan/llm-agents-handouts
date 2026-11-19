// Module 5 lesson: agentic RAG. Retrieval as a tool: the model decides WHEN to search and WITH WHAT query.
//
// Compare with m05_rag_basic, which always retrieves exactly once. Here the agent loop (agent.mjs) may search
// zero, one or several times. Run:  node examples/js/m05_rag_tool.mjs
import { pathToFileURL } from "node:url";
import { runAgent } from "./agent.mjs";
import { formatSources } from "./rag.mjs";
import { loadRetriever } from "./retrieval.mjs";

let retriever = null;

const searchDocs = {
  name: "search_docs",
  description: "Search the tutorial handouts about LLM agents (tool calling, patterns, multi-agent, RAG). " +
    "Use it for any question about their content. Use short, specific queries; search again with a different query if needed.",
  parameters: { type: "object", properties: { query: { type: "string", description: "What to look for" } }, required: ["query"] },
  // The 4 best chunks of the handouts for a query, numbered so the model can cite them.
  run: async ({ query }) => {
    retriever ??= await loadRetriever();
    const hits = await retriever.search(query, 4, { mode: "hybrid" });
    return hits.length ? formatSources(hits, 800) : "No results.";
  },
};

const SYSTEM = "You answer questions about the tutorial handouts. Use search_docs to find the facts and cite the sources " +
  "you used like [1]. If you search and the results do not contain the answer, say you do not know. " +
  "For questions that are not about the handouts, answer directly without searching.";

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  for (const question of [
    "How do I continue a conversation across several run_agent calls?", // one search
    "How does reflection differ from evaluator-optimizer, and which one has a loop?", // may search twice
    "What is 17 * 3?", // no search needed
  ]) {
    console.log(`\nQ: ${question}`);
    console.log("A:", await runAgent(question, [searchDocs], { system: SYSTEM, maxSteps: 6 }));
  }
}
