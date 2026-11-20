// Module 12 lesson: observability, cost and latency.
//
// Part 1 runs a few tasks through the guarded loop and prints its TRACE: one span per model call and per tool call, with token
// counts and timings, and writes the spans as JSON lines (examples/.traces/, git-ignored). Part 2 shows where the tokens of an
// agent run go: every step sends the whole history again. Part 3 measures PROMPT CACHING: the same long instruction block is
// sent six times, once with the stable text first (a cacheable prefix) and once with a changing timestamp in front of it
// (which defeats the cache). The prices of the cost estimate come from PRICE_INPUT_PER_M and PRICE_OUTPUT_PER_M in .env; without
// them illustrative rates are used and labelled as such. About 20 model calls. Run:  node examples/js/m12_observe_cost.mjs
import { mkdirSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { pathToFileURL } from "node:url";
import { prices, runGuarded } from "./guard.mjs";
import { chatFull } from "./llm_client.mjs";
import { READ_ONLY, SYSTEM, makeTools } from "./m12_eval.mjs";
import { ROOT } from "./retrieval.mjs";

const TRACE_DIR = join(ROOT, "examples", ".traces");
const ILLUSTRATIVE = [0.20, 1.25]; // dollars per million tokens: NOT a real price list, replace with your own in .env
const TASKS = ["What is 18% of 2450?", "Save two notes: buy milk, and call Anna.", "Save a note: dentist on Friday at 10:00, then list all my notes."];

const percentile = (values, q) => [...values].sort((a, b) => a - b)[Math.min(values.length - 1, Math.floor(q * values.length))];

function money(inputTokens, outputTokens) {
  let rate = prices();
  const real = Boolean(rate && rate.some((x) => x)); // prices of 0 mean "free" (a local model): use illustrative rates so that the lesson shows a number
  if (!real) rate = ILLUSTRATIVE;
  return `$${((inputTokens * rate[0] + outputTokens * rate[1]) / 1_000_000).toFixed(6)}` + (real ? "" : " (illustrative rates, not a real price list)");
}

const RULES = Array.from({ length: 60 }, (_, i) => `Rule ${i + 1}: when a request mentions item ${i + 1}, check the reference table ${i + 1} before answering, keep the wording neutral, ` +
  `and never reveal internal code ${1001 + i}.`).join(" ");
const QUESTIONS = ["Capital of France?", "Capital of Italy?", "Capital of Spain?", "Capital of Austria?", "Capital of Poland?", "Capital of Hungary?"];

async function ask(system, question) {
  const started = performance.now();
  const { usage } = await chatFull([{ role: "system", content: system }, { role: "user", content: `${question} Answer in one word.` }], { temperature: 0 });
  return [(performance.now() - started) / 1000, usage];
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log("1. The trace of three runs: one span per model call and per tool call");
  mkdirSync(TRACE_DIR, { recursive: true });
  const spans = [], runs = [];
  for (const prompt of TASKS) {
    const { tools } = makeTools([]);
    const result = await runGuarded(prompt, tools, { system: SYSTEM, policy: { readOnly: READ_ONLY, approve: () => true, maxSteps: 6 } });
    runs.push([prompt, result]);
    spans.push(...result.spans.map((s) => ({ run: prompt, ...s })));
  }
  const traceFile = join(TRACE_DIR, "m12_spans.jsonl");
  writeFileSync(traceFile, spans.map((s) => JSON.stringify(s)).join("\n"), "utf8");
  console.log(`   ${"run".padEnd(44)}${"span".padEnd(14)}${"seconds".padStart(8)}  details`);
  for (const s of spans) {
    const a = s.attributes;
    const detail = s.name === "chat"
      ? `in ${a["gen_ai.usage.input_tokens"]}, out ${a["gen_ai.usage.output_tokens"]}, cached ${a.cached_tokens}, tool calls requested ${a.tool_calls_requested}`
      : `${a.tool} -> ${a.outcome}`;
    console.log(`   ${s.run.slice(0, 42).padEnd(44)}${s.name.padEnd(14)}${s.duration_s.toFixed(2).padStart(8)}  ${detail}`);
  }
  const chats = spans.filter((s) => s.name === "chat").map((s) => s.duration_s);
  const totalIn = runs.reduce((sum, [, r]) => sum + r.inputTokens, 0);
  const totalOut = runs.reduce((sum, [, r]) => sum + r.outputTokens, 0);
  console.log(`\n   ${chats.length} model calls: median ${percentile(chats, 0.5).toFixed(2)} s, p95 ${percentile(chats, 0.95).toFixed(2)} s; ` +
    `${totalIn} input and ${totalOut} output tokens; estimated cost ${money(totalIn, totalOut)}`);
  console.log(`   spans written to ${relative(ROOT, traceFile)}`);

  console.log("\n2. Where the tokens go: every step sends the whole history again");
  const longest = runs.reduce((best, item) => (item[1].spans.filter((s) => s.name === "chat").length > best[1].spans.filter((s) => s.name === "chat").length ? item : best));
  console.log(`   run: '${longest[0]}'`);
  for (const [i, s] of longest[1].spans.filter((x) => x.name === "chat").entries()) {
    const a = s.attributes;
    console.log(`   model call ${i + 1}: ${String(a["gen_ai.usage.input_tokens"]).padStart(5)} tokens in, ${String(a["gen_ai.usage.output_tokens"]).padStart(4)} out`);
  }

  console.log(`\n3. Prompt caching: a stable instruction block of ${RULES.length} characters, six questions in a row`);
  for (const [label, build] of [["stable text first (cacheable prefix)", () => RULES],
    ["changing timestamp first (defeats the cache)", () => `Current time: ${process.hrtime.bigint()}\n${RULES}`]]) {
    const rows = [];
    for (const q of QUESTIONS) rows.push(await ask(build(), q));
    console.log(`   ${label}`);
    console.log(`     input tokens per call: [${rows.map(([, u]) => u.prompt_tokens).join(", ")}]`);
    console.log(`     cached tokens per call: [${rows.map(([, u]) => u.prompt_tokens_details?.cached_tokens ?? 0).join(", ")}]`);
    console.log(`     seconds per call: [${rows.map(([t]) => Number(t.toFixed(2))).join(", ")}]`);
  }
}
