import { pathToFileURL } from "node:url";
import { chat } from "./llm_client.mjs";

// ReAct with plain text: works for models without native tool calling.
const tools = {
  get_weather: (city) => `14C and cloudy in ${city}`,
};

const SYSTEM = `Answer using this format, one step at a time:
Thought: <reasoning>
Action: tool_name("argument")
Then stop and wait for the Observation.
When done reply with: Final Answer: <answer>
Tools: get_weather(city)`;

export async function reactText(question, maxSteps = 5) {
  const messages = [{ role: "system", content: SYSTEM }, { role: "user", content: question }];
  for (let i = 0; i < maxSteps; i++) {
    // Not using the `stop` parameter: some models (e.g. Azure gpt-5 family) reject it.
    // Instead cut the reply at "Observation:" ourselves, in case the model invents one.
    const raw = (await chat(messages, { temperature: 0 })).content ?? "";
    const text = raw.split("Observation:")[0].trim();
    messages.push({ role: "assistant", content: text });
    const final = text.match(/Final Answer:\s*([\s\S]*)/);
    if (final) return final[1].trim();
    const action = text.match(/Action:\s*(\w+)\("?([^")]*)"?\)/);
    let observation;
    if (!action || !tools[action[1]]) observation = "Error: invalid or unknown action. Use the given format.";
    else observation = tools[action[1]](action[2]);
    messages.push({ role: "user", content: `Observation: ${observation}` });
  }
  return "Stopped: step limit reached.";
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(await reactText("What is the weather in Paris?"));
}
