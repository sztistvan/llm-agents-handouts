// A small production-style agent loop (Module 12): budgets, a permission gate, an audit trail and a trace.
//
// Shared building block. Layers: llm_client -> guard -> m12_* lessons. `runGuarded` is the loop of Module 2
// with the things a real deployment adds around it, which makes it a harness in miniature (see docs/glossary.md):
//
//   BUDGETS      a maximum of model calls (steps), tool calls, tokens and (optionally) money per run; when one is used up the
//                run stops with a reason instead of looping or spending without limit
//   PERMISSIONS  tools on the read-only list run; every other tool needs `policy.approve(name, args)` to say yes, and a
//                "no" is returned to the model as the tool's result. The decision is made in code, never by the model
//   AUDIT TRAIL  every tool call with its outcome (ran, denied, error), in `result.audit`
//   TRACE        one span per model call and per tool call with timings and token counts, in `result.spans`. The attribute
//                names follow the OpenTelemetry GenAI conventions (status: Development), so the spans can be exported later
//
// Prices for the cost estimate come from PRICE_INPUT_PER_M and PRICE_OUTPUT_PER_M (dollars per million tokens), optionally
// prefixed by the provider (AZURE_PRICE_INPUT_PER_M); without them the cost is null.
// A tool is a plain object: { name, description, parameters (JSON Schema), run(args) }.
import { chatFull, getConfig } from "./llm_client.mjs";

const MAX_TOOL_OUTPUT = 2000;

/** [input, output] dollars per million tokens from the environment, or null when not set. */
export function prices() {
  const read = (name) => process.env[`${getConfig().provider.toUpperCase()}_${name}`] || process.env[name];
  const low = read("PRICE_INPUT_PER_M"), high = read("PRICE_OUTPUT_PER_M");
  return low && high ? [Number(low), Number(high)] : null;
}

export function estimateCost(inputTokens, outputTokens) {
  const rate = prices();
  return rate === null ? null : (inputTokens * rate[0] + outputTokens * rate[1]) / 1_000_000;
}

export const defaultPolicy = () => ({
  readOnly: new Set(),             // tools that run without asking
  approve: () => false,            // asked for every other tool: (name, args) => boolean
  maxSteps: 8,                     // model calls
  maxToolCalls: 12,
  maxTokens: 30_000,               // input + output tokens of the whole run
  maxCost: null,                   // dollars, needs prices()
});

/** Run a goal; returns { answer, stopReason, spans, audit, inputTokens, outputTokens, cachedTokens, cost }. */
export async function runGuarded(goal, tools, { system = "You are a helpful assistant.", policy = {}, messages = [] } = {}) {
  const rules = { ...defaultPolicy(), ...policy };
  const schemas = tools.map(({ name, description, parameters }) => ({ type: "function", function: { name, description, parameters } }));
  const registry = Object.fromEntries(tools.map((t) => [t.name, t]));
  const { model } = getConfig();
  if (messages.length === 0) messages.push({ role: "system", content: system });
  messages.push({ role: "user", content: goal });
  const result = { answer: "", stopReason: "final", spans: [], audit: [], inputTokens: 0, outputTokens: 0, cachedTokens: 0,
    get cost() { return estimateCost(this.inputTokens, this.outputTokens); },
    get toolCalls() { return this.audit.filter((a) => a.outcome !== "unknown_tool"); } };

  const overBudget = (step, calls) => {
    if (step >= rules.maxSteps) return "max_steps";
    if (calls >= rules.maxToolCalls) return "max_tool_calls";
    if (result.inputTokens + result.outputTokens >= rules.maxTokens) return "max_tokens";
    if (rules.maxCost !== null && (result.cost ?? 0) >= rules.maxCost) return "max_cost";
    return null;
  };

  let calls = 0;
  for (let step = 0; step <= rules.maxSteps; step++) {
    const reason = overBudget(step, calls);
    if (reason) { result.stopReason = reason; result.answer = `Stopped: ${reason.replaceAll("_", " ")} reached.`; return result; }
    let started = Date.now();
    const { message, usage } = await chatFull(messages, { tools: schemas, temperature: 0.2 });
    const cached = usage.prompt_tokens_details?.cached_tokens ?? 0;
    result.inputTokens += usage.prompt_tokens ?? 0;
    result.outputTokens += usage.completion_tokens ?? 0;
    result.cachedTokens += cached;
    result.spans.push({ name: "chat", duration_s: (Date.now() - started) / 1000, attributes: {
      "gen_ai.operation.name": "chat", "gen_ai.request.model": model,
      "gen_ai.usage.input_tokens": usage.prompt_tokens ?? 0, "gen_ai.usage.output_tokens": usage.completion_tokens ?? 0,
      cached_tokens: cached, tool_calls_requested: message.tool_calls?.length ?? 0 } });
    messages.push(message);
    if (!message.tool_calls?.length) { result.answer = message.content ?? ""; return result; }
    for (const call of message.tool_calls) {
      const name = call.function.name;
      let args = {};
      try { args = JSON.parse(call.function.arguments || "{}"); } catch { /* bad JSON: treated as no arguments */ }
      started = Date.now();
      let outcome, text;
      if (!(name in registry)) {
        [outcome, text] = ["unknown_tool", `Error: unknown tool '${name}'`];
      } else if (!rules.readOnly.has(name) && !(await rules.approve(name, args))) {
        [outcome, text] = ["denied", "Error: this action needs the user's approval and was not approved."];
      } else {
        calls += 1;
        try { [outcome, text] = ["ran", String(await registry[name].run(args))]; } catch (err) { [outcome, text] = ["error", `Error: ${err.message}`]; }
      }
      result.audit.push({ tool: name, arguments: args, outcome });
      result.spans.push({ name: "execute_tool", duration_s: (Date.now() - started) / 1000, attributes: {
        "gen_ai.operation.name": "execute_tool", tool: name, outcome, result_chars: text.length } });
      messages.push({ role: "tool", tool_call_id: call.id, content: text.slice(0, MAX_TOOL_OUTPUT) });
    }
  }
  result.stopReason = "max_steps";
  result.answer = "Stopped: max steps reached.";
  return result;
}
