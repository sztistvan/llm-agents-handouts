// Reusable agent loop (Module 2): `runAgent`.
//
// Shared building block: the later modules import it (the supervisor in Module 4 uses it for its workers).
// Layers: llm_client.mjs (talk to the model) -> agent.mjs (the loop) -> the mNN_*.mjs lessons.
// The lessons show how it is built; see docs/02-building-blocks.md, section 6.
//
// A tool is a plain object: { name, description, parameters (JSON Schema), run(args) }.
import { chat, show, traceMode } from "./llm_client.mjs";

const MAX_TOOL_OUTPUT = 2000;

/**
 * Run the agent loop and return the final answer (a string).
 * `messages`: optional conversation so far. The array is extended in place (the system message is
 * added only if the array is empty), so pass the same array again to continue the conversation.
 */
export async function runAgent(goal, tools, { system = "You are a helpful assistant.", maxSteps = 8, messages = [] } = {}) {
  const schemas = tools.map(({ name, description, parameters }) => ({
    type: "function", function: { name, description, parameters } }));
  const registry = Object.fromEntries(tools.map((t) => [t.name, t])); // mapping of tool names to their tool objects
  const mode = traceMode(); // off by default; LLM_TRACE=1 one line per message, LLM_TRACE=raw full JSON
  if (messages.length === 0) messages.push({ role: "system", content: system });
  messages.push({ role: "user", content: goal });
  for (let step = 1; step <= maxSteps; step++) {
    const msg = await chat(messages, { tools: schemas, temperature: 0.2 });
    messages.push(msg);
    show(msg, step, mode);
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
      const toolMsg = { role: "tool", tool_call_id: call.id, content: result.slice(0, MAX_TOOL_OUTPUT) };
      messages.push(toolMsg);
      show(toolMsg, step, mode);
    }
  }
  return "Stopped: step limit reached.";
}
