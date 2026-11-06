import { chat } from "./llm_client.mjs";

const ask = async (prompt, system = "You are a concise assistant.", temperature = 0.2) =>
  ((await chat([{ role: "system", content: system }, { role: "user", content: prompt }], { temperature })).content ?? "").trim();

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
    const text = ((await chat(messages, { temperature: 0, stop: ["Observation:"] })).content ?? "").trim();
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

console.log(await reactText("What is the weather in Paris?"));
