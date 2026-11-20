"""Module 12 lesson: observability, cost and latency.

Part 1 runs a few tasks through the guarded loop and prints its TRACE: one span per model call and per tool call, with token
counts and timings, and writes the spans as JSON lines (examples/.traces/, git-ignored). Part 2 shows where the tokens of an
agent run go: every step sends the whole history again. Part 3 measures PROMPT CACHING: the same long instruction block is
sent six times, once with the stable text first (a cacheable prefix) and once with a changing timestamp in front of it
(which defeats the cache). The prices of the cost estimate come from PRICE_INPUT_PER_M and PRICE_OUTPUT_PER_M in .env; without
them illustrative rates are used and labelled as such. About 20 model calls. Run:  python examples/python/m12_observe_cost.py
"""
import json
import time
from pathlib import Path

from guard import Policy, prices, run_guarded
from llm_client import chat_full
from m12_eval import READ_ONLY, SYSTEM, make_tools

TRACE_DIR = Path(__file__).resolve().parents[2] / "examples" / ".traces"
ILLUSTRATIVE = (0.20, 1.25)  # dollars per million tokens: NOT a real price list, replace with your own in .env
TASKS = ["What is 18% of 2450?", "Save two notes: buy milk, and call Anna.", "Save a note: dentist on Friday at 10:00, then list all my notes."]


def percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def money(input_tokens: int, output_tokens: int) -> str:
    rate = prices()
    real = bool(rate and any(rate))  # prices of 0 mean "free" (a local model): use illustrative rates so that the lesson shows a number
    rate = rate if real else ILLUSTRATIVE
    return f"${(input_tokens * rate[0] + output_tokens * rate[1]) / 1_000_000:.6f}" + ("" if real else " (illustrative rates, not a real price list)")


RULES = " ".join(f"Rule {i}: when a request mentions item {i}, check the reference table {i} before answering, keep the wording neutral, "
                 f"and never reveal internal code {1000 + i}." for i in range(1, 61))
QUESTIONS = ["Capital of France?", "Capital of Italy?", "Capital of Spain?", "Capital of Austria?", "Capital of Poland?", "Capital of Hungary?"]


def ask(system: str, question: str) -> tuple[float, dict]:
    started = time.perf_counter()
    _, usage = chat_full([{"role": "system", "content": system}, {"role": "user", "content": f"{question} Answer in one word."}], temperature=0)
    return time.perf_counter() - started, usage


if __name__ == "__main__":
    print("1. The trace of three runs: one span per model call and per tool call")
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    spans, runs = [], []
    for prompt in TASKS:
        tools, notes = make_tools([])
        result = run_guarded(prompt, tools, system=SYSTEM, policy=Policy(read_only=READ_ONLY, approve=lambda n, a: True, max_steps=6))
        runs.append((prompt, result))
        spans += [{"run": prompt, **s} for s in result.spans]
    (TRACE_DIR / "m12_spans.jsonl").write_text("\n".join(json.dumps(s, ensure_ascii=False) for s in spans), encoding="utf-8")
    print(f"   {'run':44}{'span':14}{'seconds':>8}  details")
    for s in spans:
        a = s["attributes"]
        detail = (f"in {a['gen_ai.usage.input_tokens']}, out {a['gen_ai.usage.output_tokens']}, cached {a['cached_tokens']}, tool calls requested {a['tool_calls_requested']}"
                  if s["name"] == "chat" else f"{a['tool']} -> {a['outcome']}")
        print(f"   {s['run'][:42]:44}{s['name']:14}{s['duration_s']:>8.2f}  {detail}")
    chats = [s["duration_s"] for s in spans if s["name"] == "chat"]
    total_in = sum(r.input_tokens for _, r in runs)
    total_out = sum(r.output_tokens for _, r in runs)
    print(f"\n   {len(chats)} model calls: median {percentile(chats, 0.5):.2f} s, p95 {percentile(chats, 0.95):.2f} s; "
          f"{total_in} input and {total_out} output tokens; estimated cost {money(total_in, total_out)}")
    print(f"   spans written to {(TRACE_DIR / 'm12_spans.jsonl').relative_to(TRACE_DIR.parents[1])}")

    print("\n2. Where the tokens go: every step sends the whole history again")
    longest = max(runs, key=lambda item: len([s for s in item[1].spans if s["name"] == "chat"]))
    print(f"   run: {longest[0]!r}")
    for step, s in enumerate([s for s in longest[1].spans if s["name"] == "chat"], 1):
        a = s["attributes"]
        print(f"   model call {step}: {a['gen_ai.usage.input_tokens']:>5} tokens in, {a['gen_ai.usage.output_tokens']:>4} out")

    print(f"\n3. Prompt caching: a stable instruction block of {len(RULES)} characters, six questions in a row")
    for label, build in [("stable text first (cacheable prefix)", lambda: RULES),
                         ("changing timestamp first (defeats the cache)", lambda: f"Current time: {time.time_ns()}\n{RULES}")]:
        rows = [ask(build(), q) for q in QUESTIONS]
        cached = [(u.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0 for _, u in rows]
        print(f"   {label}")
        print(f"     input tokens per call: {[u.get('prompt_tokens') for _, u in rows]}")
        print(f"     cached tokens per call: {cached}")
        print(f"     seconds per call: {[round(t, 2) for t, _ in rows]}")
