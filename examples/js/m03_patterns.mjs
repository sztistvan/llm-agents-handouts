// Runnable versions of the Module 3 workflow patterns (no framework).
import { pathToFileURL } from "node:url";
import { chat } from "./llm_client.mjs";

export async function ask(prompt, { system = "You are a concise assistant.", temperature = 0.2 } = {}) {
  const messages = [{ role: "system", content: system }, { role: "user", content: prompt }];
  return ((await chat(messages, { temperature })).content ?? "").trim();
}

export async function askJson(prompt, retries = 3) {
  const messages = [{ role: "system", content: "Reply with valid JSON only." }, { role: "user", content: prompt }];
  for (let i = 0; i < retries; i++) {
    let raw = ((await chat(messages, { temperature: 0 })).content ?? "").trim();
    raw = raw.replace(/^```(?:json)?\s*/, "").replace(/```$/, "").trim();
    try {
      return JSON.parse(raw);
    } catch (err) {
      messages.push({ role: "assistant", content: raw },
                    { role: "user", content: `Invalid JSON (${err.message}). Reply with valid JSON only.` });
    }
  }
  throw new Error("No valid JSON");
}

// 1. Prompt chaining: fixed sequence with a gate (a code check) in between.
export async function chain(topic) {
  const outline = await ask(`Write a 3-bullet outline for a short article about ${topic}.`);
  if (outline.split("\n").filter((line) => line.trim()).length < 3) { // gate: expect 3 non-empty lines
    throw new Error("Outline too short");
  }
  return ask(`Write a 100-word article from this outline:\n${outline}`);
}

// 2. Routing: classify, then branch to a specialised prompt.
export async function route(text) {
  const handlers = {
    billing: "You are a billing support agent.",
    technical: "You are a technical support agent.",
    other: "You are a general support agent.",
  };
  const label = (await ask(`Classify as billing, technical or other. One word only.\n${text}`, { temperature: 0 })).toLowerCase();
  const key = Object.keys(handlers).find((k) => label.includes(k)) ?? "other"; // safe default
  return ask(text, { system: handlers[key] });
}

// 3. Parallelization (voting): same question several times at once, pick the majority.
export async function vote(question, n = 3) {
  const answers = await Promise.all(
    Array.from({ length: n }, () => ask(`${question} Answer in one word.`, { temperature: 0.8 })));
  const normalized = answers.map((a) => a.toLowerCase().replace(/^[\s.!]+|[\s.!]+$/g, "")); // "Canberra." == "canberra"
  const counts = new Map();
  for (const a of normalized) counts.set(a, (counts.get(a) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
}

// 4. Orchestrator-workers: the LLM decides the subtasks, workers do them, one call combines.
export async function orchestrate(goal) {
  const { subtasks } = await askJson(`List 2-4 subtasks for: ${goal}. Format: {"subtasks": ["..."]}`);
  const results = [];
  for (const task of subtasks) results.push(await ask(`Complete this subtask briefly: ${task}`));
  return ask(`Combine into one answer:\n${results.join("\n")}`);
}

// 5. Evaluator-optimizer: generate, critique, improve; capped number of rounds.
export async function evaluateOptimize(task, maxRounds = 3) {
  let draft = await ask(task);
  for (let i = 0; i < maxRounds; i++) {
    const verdict = await askJson(
      `Task: ${task}\nDraft: ${draft}\nIs the draft correct and complete? ` +
      'Format: {"ok": true|false, "feedback": "..."}');
    if (verdict.ok) break;
    draft = await ask(`${task}\nImprove using this feedback: ${verdict.feedback}\nPrevious draft: ${draft}`);
  }
  return draft;
}

// 6. Reflection: the SAME agent answers, critiques its own answer once, then revises.
// Compared with evaluateOptimize: no separate judge, no ok/not-ok verdict, no loop.
export async function reflect(task) {
  const answer = await ask(task);
  const critique = await ask(`Task: ${task}\nAnswer: ${answer}\nWhat is wrong or missing in this answer? Be specific and brief.`);
  return ask(`${task}\nPrevious answer: ${answer}\nFix these issues:\n${critique}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(await chain("local LLMs"));
  console.log(await route("My invoice shows the wrong amount."));
  console.log(await vote("What is the capital of Australia?"));
  console.log(await orchestrate("Plan a one-day team workshop on LLM agents"));
  console.log(await evaluateOptimize("Write one sentence explaining what an LLM agent is."));
  console.log(await reflect("Explain in two sentences why the sky is blue."));
}
