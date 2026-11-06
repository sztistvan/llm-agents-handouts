// Thin LLM client for any OpenAI-compatible backend (LM Studio or Azure OpenAI).
// Uses only built-in fetch (Node 18+). See README for environment variables.

function required(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Environment variable ${name} is required for this provider`);
  return value;
}

export function getConfig() {
  const provider = (process.env.LLM_PROVIDER ?? "lmstudio").toLowerCase();
  if (provider === "lmstudio") {
    return {
      baseUrl: process.env.LLM_BASE_URL ?? "http://localhost:1234/v1",
      apiKey: process.env.LLM_API_KEY ?? "lm-studio",
      model: process.env.LLM_MODEL ?? "local-model",
    };
  }
  if (provider === "azure") {
    return {
      baseUrl: required("LLM_BASE_URL"),
      apiKey: required("LLM_API_KEY"),
      model: required("LLM_MODEL"),
    };
  }
  throw new Error(`Unknown LLM_PROVIDER: ${provider}`);
}

/** Send a chat completion request and return the first choice's message. */
export async function chat(messages, extra = {}) {
  const { baseUrl, apiKey, model } = getConfig();
  const res = await fetch(`${baseUrl.replace(/\/$/, "")}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({ model, messages, ...extra }),
  });
  if (!res.ok) throw new Error(`LLM request failed: ${res.status} ${await res.text()}`);
  const data = await res.json();
  return data.choices[0].message;
}

if (import.meta.url === `file://${process.argv[1].replace(/\\/g, "/")}` ||
    process.argv[1]?.endsWith("llm_client.mjs")) {
  const reply = await chat([{ role: "user", content: "Say hello in five words." }]);
  console.log(reply.content);
}
