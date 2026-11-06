import { chat } from "./llm_client.mjs";

const getTime = ({ city }) => `It is 12:00 in ${city}.`; // stub

const tools = [{
  type: "function",
  function: {
    name: "get_time",
    description: "Get the current time in a city.",
    parameters: { type: "object", properties: { city: { type: "string" } }, required: ["city"] },
  },
}];
const registry = { get_time: getTime };

async function runAgent(goal, maxSteps = 5) {
  const messages = [
    { role: "system", content: "You are a helpful assistant. Use tools when needed." },
    { role: "user", content: goal },
  ];
  for (let i = 0; i < maxSteps; i++) {
    const msg = await chat(messages, { tools });
    messages.push(msg);
    if (!msg.tool_calls?.length) return msg.content;
    for (const call of msg.tool_calls) {
      let result;
      try {
        result = registry[call.function.name](JSON.parse(call.function.arguments));
      } catch (err) {
        result = `Error: ${err.message}`; // feed errors back so the model can retry
      }
      messages.push({ role: "tool", tool_call_id: call.id, content: result });
    }
  }
  throw new Error("Step limit reached");
}

console.log(await runAgent("What time is it in Budapest?"));
