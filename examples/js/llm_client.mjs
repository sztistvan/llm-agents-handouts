// Thin LLM client for any OpenAI-compatible backend (LM Studio or Azure OpenAI).
// Uses only built-in fetch (Node 20.12+). See README for environment variables.
// Also reads a .env file in the project root (real environment variables win).
//   LLM_TIMEOUT  request timeout in seconds (default 300; local models can be slow)
// Use a non-reasoning, tool-capable model: reasoning models may spend the whole
// token budget thinking and return an empty answer (chat() throws a clear error).
import { fileURLToPath, pathToFileURL } from "node:url";
import { existsSync } from "node:fs";

const envFile = fileURLToPath(new URL("../../.env", import.meta.url));
if (existsSync(envFile)) {
  try { process.loadEnvFile(envFile); } catch { /* Node < 20.12: export variables manually */ }
}

// Provider selection: LLM_PROVIDER (default "azure") picks a block of three settings,
// <PROVIDER>_BASE_URL, <PROVIDER>_API_KEY, <PROVIDER>_MODEL (see .env.example).
// One-off switch: PowerShell:  $env:LLM_PROVIDER = "lmstudio"; node m01_minimal_agent.mjs
//                              (then Remove-Item Env:LLM_PROVIDER to go back to the .env provider)
//                 bash/zsh:    LLM_PROVIDER=lmstudio node m01_minimal_agent.mjs
function setting(provider, name) {
  const key = `${provider.toUpperCase()}_${name}`;
  const value = process.env[key];
  if (!value) throw new Error(`Missing ${key} (LLM_PROVIDER=${provider}). Add it to .env, see .env.example.`);
  return value;
}

export function getConfig() {
  const provider = (process.env.LLM_PROVIDER ?? "azure").trim().toLowerCase();
  return {
    provider,
    baseUrl: setting(provider, "BASE_URL"),
    apiKey: setting(provider, "API_KEY"),
    model: setting(provider, "MODEL"),
  };
}

/** Send a chat completion request and return the first choice's message. */
export async function chat(messages, extra = {}) {
  const { baseUrl, apiKey, model } = getConfig();
  const timeoutMs = Number(process.env.LLM_TIMEOUT ?? 300) * 1000;
  const res = await fetch(`${baseUrl.replace(/\/$/, "")}/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({ model, messages, ...extra }),
    signal: AbortSignal.timeout(timeoutMs),
    // Node's built-in fetch also has a fixed 5-minute headers timeout (undici default);
    // slower generations fail with "fetch failed" regardless of LLM_TIMEOUT.
  });
  if (!res.ok) throw new Error(`LLM request failed: ${res.status} ${await res.text()}`);
  const data = await res.json();
  const choice = data.choices[0];
  if (choice.finish_reason === "length" && !choice.message.content && !choice.message.tool_calls?.length) {
    throw new Error(
      "Empty reply: the token limit was hit before any answer. " +
      "Reasoning models do this; load a non-reasoning model or raise max_tokens.");
  }
  return choice.message;
}

/** Read LLM_TRACE: 'compact' (also 1/true/on), 'raw' (full JSON) or 'off'. `defaultMode` applies when unset. */
export function traceMode(defaultMode = "off") {
  const value = (process.env.LLM_TRACE ?? defaultMode).trim().toLowerCase();
  if (value === "raw") return "raw";
  return ["1", "true", "on", "yes", "compact"].includes(value) ? "compact" : "off";
}

const short = (text, limit = 100) => {
  const s = String(text).split(/\s+/).filter(Boolean).join(" ");
  return s.length <= limit ? s : `${s.slice(0, limit - 1)}…`;
};

/**
 * Print one message of the agent loop, to see tool calls and the final answer.
 * mode 'compact': one line per message; 'raw': the message as JSON; 'off': nothing.
 */
export function show(msg, step, mode) {
  if (mode === "off") return;
  const empty = (v) => v == null || v === "" || (Array.isArray(v) && !v.length) ||
    (typeof v === "object" && !Array.isArray(v) && !Object.keys(v).length);
  const data = Object.fromEntries(Object.entries(msg).filter(([, v]) => !empty(v))); // drop empty noise
  if (mode === "raw") {
    console.log(`--- step ${step}: ${data.role} message`);
    console.log(JSON.stringify(data, null, 2));
    return;
  }
  if (data.role === "assistant" && data.tool_calls) {
    for (const call of data.tool_calls) {
      console.log(`[step ${step}] assistant -> TOOL CALL ${call.function.name}(${call.function.arguments})  id=${call.id}`);
    }
  } else if (data.role === "assistant") {
    console.log(`[step ${step}] assistant -> FINAL ANSWER (no tool_calls): ${short(data.content ?? "")}`);
  } else if (data.role === "tool") {
    console.log(`[step ${step}] tool      <- ${short(data.content ?? "")}  (tool_call_id=${data.tool_call_id})`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const reply = await chat([{ role: "user", content: "Say hello in five words." }]);
  console.log(reply.content);
}
