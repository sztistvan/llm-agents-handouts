import { pathToFileURL } from "node:url";
import { chat } from "./llm_client.mjs";

const MAX_TOOL_OUTPUT = 2000;

export async function runAgent(goal, tools, { system = "You are a helpful assistant.", maxSteps = 8 } = {}) {
  const schemas = tools.map(({ name, description, parameters }) => ({
    type: "function", function: { name, description, parameters } }));
  const registry = Object.fromEntries(tools.map((t) => [t.name, t]));
  const messages = [{ role: "system", content: system }, { role: "user", content: goal }];
  for (let i = 0; i < maxSteps; i++) {
    const msg = await chat(messages, { tools: schemas, temperature: 0.2 });
    messages.push(msg);
    if (!msg.tool_calls?.length) return msg.content;
    for (const call of msg.tool_calls) {
      let result;
      try {
        const tool = registry[call.function.name];
        if (!tool) throw new Error(`unknown tool '${call.function.name}'`);
        result = String(await tool.run(JSON.parse(call.function.arguments)));
      } catch (err) {
        result = `Error: ${err.message}`;
      }
      messages.push({ role: "tool", tool_call_id: call.id, content: result.slice(0, MAX_TOOL_OUTPUT) });
    }
  }
  return "Stopped: step limit reached.";
}

const tools = [
  { name: "add", description: "Add two numbers.", run: ({ a, b }) => a + b,
    parameters: { type: "object", properties: { a: { type: "number" }, b: { type: "number" } }, required: ["a", "b"] } },
  { name: "word_count", description: "Count words in a text.", run: ({ text }) => text.split(/\s+/).filter(Boolean).length,
    parameters: { type: "object", properties: { text: { type: "string" } }, required: ["text"] } },
];

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(await runAgent("How many words are in 'the quick brown fox'? Then add 10 to that count.", tools));
}
