import { chat, show, traceMode } from "./llm_client.mjs";

const getTime = ({ city }) => `It is 12:00 in ${city}.`; // stub

const tools = [{
  type: "function",
  function: {
    name: "get_time",
    description: "Get the current time in a city.",
    parameters: { type: "object", properties: { city: { type: "string" } }, required: ["city"] },
  },
}];
const registry = { get_time: getTime }; // mapping of tool names to their corresponding functions

async function runAgent(goal, maxSteps = 5) {
  const mode = traceMode("compact"); // LLM_TRACE=raw: full JSON; LLM_TRACE=off: silent
  const messages = [
    { role: "system", content: "You are a helpful assistant. Use tools when needed." },
    { role: "user", content: goal },
  ];
  for (let step = 1; step <= maxSteps; step++) {
    const msg = await chat(messages, { tools });
    messages.push(msg);
    show(msg, step, mode);
    if (!msg.tool_calls?.length) return msg.content; // no tool call = the model has given its final answer
    for (const call of msg.tool_calls) {
      let result;
      try {
        result = registry[call.function.name](JSON.parse(call.function.arguments)); // call the registered tool function with the provided arguments
      } catch (err) {
        result = `Error: ${err.message}`; // feed errors back so the model can retry
      }
      const toolMsg = { role: "tool", tool_call_id: call.id, content: result };
      messages.push(toolMsg);
      show(toolMsg, step, mode);
    }
  }
  throw new Error("Step limit reached");
}

console.log(await runAgent("What time is it in Budapest?"));
