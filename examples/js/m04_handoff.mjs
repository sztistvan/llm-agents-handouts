import { chat } from "./llm_client.mjs";

// Swarm-style handoff: agents are peers; a special tool transfers control.
const AGENTS = {
  triage: {
    system: "You are a triage agent. Hand off billing questions to billing and technical ones to support. Answer nothing yourself.",
    handoffs: ["billing", "support"],
  },
  billing: { system: "You are a billing agent. Answer billing questions in one or two sentences.", handoffs: [] },
  support: { system: "You are a technical support agent. Answer in one or two sentences.", handoffs: [] },
};

const handoffTools = (names) => names.map((n) => ({
  type: "function",
  function: {
    name: `transfer_to_${n}`,
    description: `Hand the conversation to the ${n} agent.`,
    parameters: { type: "object", properties: {}, required: [] },
  },
}));

export async function runSwarm(userText, start = "triage", maxHops = 4) {
  let active = start;
  const history = [{ role: "user", content: userText }];
  for (let hop = 0; hop <= maxHops; hop++) {
    const agent = AGENTS[active];
    const messages = [{ role: "system", content: agent.system }, ...history];
    const tools = handoffTools(agent.handoffs);
    const msg = await chat(messages, { temperature: 0.2, ...(tools.length ? { tools } : {}) });
    const target = msg.tool_calls?.[0]?.function.name.replace("transfer_to_", "");
    if (target && AGENTS[target]) {
      active = target;
      continue;
    }
    return `[${active}] ${msg.content}`;
  }
  return "Stopped: hop limit reached.";
}

console.log(await runSwarm("I was charged twice for my subscription."));
