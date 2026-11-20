// Module 10 lesson: what happens when an agent has MANY tools, and how to give it fewer.
//
// examples/tools_catalog.json describes 36 office tools (calendar, e-mail, files, tasks, CRM, ...) and 12 questions with the
// tool that should be called first. Every question is sent to the model once with the tool definitions and we look at the
// FIRST tool call (nothing is executed). Strategy A sends all 36 definitions; strategy B embeds the descriptions (Module 5),
// retrieves the 5 closest tools for the question and sends only those. Part 3 measures how often the right tool is among the
// k closest, without any LLM call; part 4 triples the catalog (the same tools from three "servers"). Needs an embedding model.
// 36 chat calls. Run:  node examples/js/m10_many_tools.mjs
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { chat, embed } from "./llm_client.mjs";
import { ROOT } from "./retrieval.mjs";

const SYSTEM = "You are an office assistant. Use the tools to help the user. Call the single most appropriate tool first.";
const K = 5;

const schemas = (tools) => tools.map((t) => ({ type: "function", function: t }));
const size = (tools) => Math.floor(JSON.stringify(schemas(tools)).length / 4);

/** The name of the first tool the model calls (null if it answers without a tool), and the seconds it took. */
async function firstTool(question, tools) {
  const started = Date.now();
  const msg = await chat([{ role: "system", content: SYSTEM }, { role: "user", content: question }], { tools: schemas(tools), temperature: 0 });
  return [msg.tool_calls?.[0]?.function.name ?? null, (Date.now() - started) / 1000];
}

const cosine = (a, b) => {
  let dot = 0, na = 0, nb = 0;
  for (let i = 0; i < a.length; i++) { dot += a[i] * b[i]; na += a[i] * a[i]; nb += b[i] * b[i]; }
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
};

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { tools, questions } = JSON.parse(readFileSync(join(ROOT, "examples", "tools_catalog.json"), "utf8"));
  const byName = Object.fromEntries(tools.map((t) => [t.name, t]));
  const n = questions.length;

  console.log(`1. ${tools.length} tools; their definitions alone are about ${size(tools)} tokens, sent with EVERY request`);
  console.log(`   ${K} tools would be about ${size(tools.slice(0, K))} tokens`);

  const vectors = await embed(tools.map((t) => `${t.name.replaceAll("_", " ")}: ${t.description}`));
  const queryVectors = await embed(questions.map((q) => q.question), "query");
  const closest = (i, k) => tools.map((t, j) => [t.name, cosine(queryVectors[i], vectors[j])]).sort((a, b) => b[1] - a[1]).slice(0, k).map(([name]) => name);

  console.log(`\n2. The first tool call: all ${tools.length} tools (A) against the ${K} closest by embedding (B)`);
  console.log(`   ${"question".padEnd(58)}${"expected".padEnd(20)}${"A: all".padEnd(22)}B: top-${K}`);
  const score = { A: 0, B: 0 };
  const seconds = { A: 0, B: 0 };
  for (const [i, item] of questions.entries()) {
    const [a, aTime] = await firstTool(item.question, tools);
    const [b, bTime] = await firstTool(item.question, closest(i, K).map((name) => byName[name]));
    score.A += a === item.expected; score.B += b === item.expected;
    seconds.A += aTime; seconds.B += bTime;
    const mark = (got) => String(got) + (got === item.expected ? "" : "  <-- wrong");
    console.log(`   ${item.question.slice(0, 56).padEnd(58)}${item.expected.padEnd(20)}${mark(a).padEnd(22)}${mark(b)}`);
  }
  console.log(`\n   correct first tool: A ${score.A}/${n}, B ${score.B}/${n};  mean seconds per call: A ${(seconds.A / n).toFixed(2)}, B ${(seconds.B / n).toFixed(2)}`);
  console.log(`   tool tokens per request: A ${size(tools)}, B about ${size(closest(0, K).map((name) => byName[name]))}`);

  console.log("\n3. Retrieval alone: how often is the right tool among the k closest? (no LLM call)");
  for (const k of [1, 3, 5, 8]) console.log(`   top-${k}: ${questions.filter((item, i) => closest(i, k).includes(item.expected)).length}/${n}`);
  for (const [i, item] of questions.entries()) {
    if (!closest(i, K).includes(item.expected)) console.log(`   missed at top-${K}: '${item.question}' -> ${JSON.stringify(closest(i, K))}`);
  }

  // Several servers often expose the same kind of tool: copy the whole catalog for two accounts (108 tools)
  const many = [...tools, ...["work", "personal"].flatMap((account) => tools.map((t) => ({ ...t, name: `${account}_${t.name}`, description: `${t.description} (${account} account)` })))];
  console.log(`\n4. Three copies of the catalog, as if three servers (own, work account, personal account) exposed the same tools: ${many.length} tools, about ${size(many)} tokens`);
  const strip = (name) => (name && ["work", "personal"].includes(name.split("_")[0]) ? name.split("_").slice(1).join("_") : name);
  let right = 0, prefixed = 0, secondsMany = 0;
  for (const item of questions) {
    const [got, took] = await firstTool(item.question, many);
    right += strip(got) === item.expected;
    prefixed += Boolean(got) && got !== strip(got);
    secondsMany += took;
  }
  console.log(`   right tool (ignoring the account): ${right}/${n}; one of the account copies chosen: ${prefixed}/${n} (nothing told the model which account to use); mean seconds per call ${(secondsMany / n).toFixed(2)}`);
}
