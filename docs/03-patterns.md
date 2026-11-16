# Module 3: Agent Patterns

**Goal:** know the common building-block patterns, when each fits, and how to implement them without a framework.
**Time:** ~25 min. **Prerequisites:** [Module 2](02-building-blocks.md).

Patterns range from simple, predictable **workflows** (code controls the flow) to autonomous **agents** (the LLM controls the flow). Pick the simplest one that works.

```mermaid
flowchart LR
    A[Single LLM call] --> B[Prompt chaining]
    B --> C[Routing / Parallelization]
    C --> D[Orchestrator-workers]
    D --> E[Evaluator-optimizer]
    E --> F[Autonomous agent: ReAct, plan-and-execute]
    style A fill:#e8f5e9
    style F fill:#ffebee
```

| Pattern | Control flow | Use when | Main risk |
|---|---|---|---|
| Prompt chaining | Fixed sequence | Task splits into clear steps | Errors propagate |
| Routing | Classifier then branch | Distinct input categories | Misclassification |
| Parallelization | Fan-out / fan-in | Independent subtasks, or voting | Cost |
| Orchestrator-workers | LLM plans subtasks dynamically | Subtasks unknown upfront | Complexity |
| Evaluator-optimizer | Generate, critique, repeat | Clear quality criteria | Endless loops |
| ReAct | LLM loop with tools | Open-ended, tool-heavy tasks | Cost, drift |
| Plan-and-execute | Plan first, then run steps | Long tasks needing structure | Stale plans |
| Reflection | Agent critiques own output | Quality matters | Extra latency |

All examples below use `chat()` from `llm_client` (see [`examples/python/m03_patterns.py`](../examples/python/m03_patterns.py) for runnable versions of chaining, routing, voting, orchestrator-workers and evaluator-optimizer; text-based ReAct is in [`examples/js/m03_react_text.mjs`](../examples/js/m03_react_text.mjs)). Run from the project root, e.g. `python examples/python/m03_patterns.py` (about 15 model calls: slow on a local model) or `node examples/js/m03_react_text.mjs`. Plan-and-execute and reflection are pseudocode only; they are exercises.

## 1. Prompt chaining

Break a task into sequential LLM calls; add **gates** (code checks) between steps.

```mermaid
flowchart LR
    I[Input] --> S1[LLM: outline] --> G{Gate: valid?}
    G -->|yes| S2[LLM: write] --> S3[LLM: translate] --> O[Output]
    G -->|no| X[Stop / retry]
```

```text
outline = llm("Outline an article about " + topic)
if not looks_valid(outline): fail
draft = llm("Write the article from this outline:\n" + outline)
return llm("Translate to Hungarian:\n" + draft)
```

Good for small models: each call has a narrow job.

## 2. Routing

Classify the input, then send it to a specialised prompt or tool.

```mermaid
flowchart LR
    I[Input] --> R{Router LLM}
    R -->|billing| B[Billing prompt]
    R -->|technical| T[Tech prompt]
    R -->|other| G[General prompt]
```

```text
label = llm_choose(input, ["billing", "technical", "other"])   # constrained output
return HANDLERS[label if label in HANDLERS else "other"](input)
```

Always fall back to a default when the label is unknown.

## 3. Parallelization

Two variants: **sectioning** (different subtasks at once) and **voting** (same task several times, pick consensus).

```mermaid
flowchart LR
    I[Input] --> A[LLM A] & B[LLM B] & C[LLM C]
    A & B & C --> M[Merge / vote]
```

```text
results = run_in_parallel([llm(p) for p in prompts])
return majority(results)       # or: llm("Combine:\n" + results)
```

Local servers often process one request at a time, so parallel calls may not speed up LM Studio; they do on Azure.

## 4. Orchestrator-workers

A central LLM breaks the task into subtasks it only discovers at runtime, delegates them to workers, then synthesizes.

```mermaid
flowchart TB
    O[Orchestrator LLM] -->|subtask 1| W1[Worker]
    O -->|subtask 2| W2[Worker]
    O -->|subtask N| W3[Worker]
    W1 & W2 & W3 --> S[Synthesize]
```

```text
subtasks = llm_json("List the subtasks needed for: " + goal)
results = [worker_llm(t) for t in subtasks]
return llm("Combine into one answer:\n" + results)
```

## 5. Evaluator-optimizer (generate and critique)

One call produces, another judges against criteria; loop until accepted or the limit is hit.

```mermaid
flowchart LR
    G[Generator] --> E{Evaluator}
    E -->|reject + feedback| G
    E -->|accept| O[Output]
```

```text
draft = llm(task)
for i in 1..MAX_ROUNDS:
    verdict = llm_json("Review against criteria. {ok: bool, feedback: str}\n" + draft)
    if verdict.ok: return draft
    draft = llm(task + "\nImprove using feedback: " + verdict.feedback + "\n" + draft)
return draft
```

## 6. ReAct (reason + act)

The classic agent loop: **Thought -> Action -> Observation**, repeated. With function-calling APIs this is the loop from Modules 1-2; the "thought" is the model's reasoning before a tool call.

```mermaid
stateDiagram-v2
    [*] --> Think
    Think --> Act: needs info/action
    Act --> Observe: tool result
    Observe --> Think
    Think --> [*]: final answer
```

Text-based ReAct (for models without native tool calling):

```text
Thought: I need the weather in Paris.
Action: get_weather("Paris")
Observation: 14C, cloudy
Thought: I can answer now.
Final Answer: It is 14C and cloudy.
```

Implement by cutting the reply at `Observation:` (the model must not invent observations), parsing the `Action:` line, running the tool, and appending the real observation. Runnable: [`examples/js/m03_react_text.mjs`](../examples/js/m03_react_text.mjs). You can also pass `stop=["Observation:"]` to the API, but some models (e.g. Azure gpt-5 family) reject that parameter, so cutting in code is the portable way. This works with weak local models, but parse defensively.

## 7. Plan-and-execute

Plan once, execute each step (often with a cheaper/smaller model or a ReAct sub-loop), re-plan when a step fails.

```mermaid
flowchart TB
    P[Planner LLM] --> L[Step list]
    L --> E[Executor: run next step]
    E --> C{Done / failed?}
    C -->|next step| E
    C -->|failed| R[Re-plan]
    R --> L
    C -->|all done| F[Final answer]
```

```text
plan = llm_json("Make a numbered plan for: " + goal)
for step in plan:
    result = executor(step, context)
    context.append(result)
    if failed(result): plan = replan(goal, context); restart
return llm("Answer using:\n" + context)
```

Benefits: fewer expensive reasoning calls, easier to inspect and show progress. Drawback: plans go stale if the environment surprises you, so allow re-planning.

## 8. Reflection

The agent reviews its own result (or a tool error) and revises. It is evaluator-optimizer where generator and critic are the same agent, possibly with a different prompt.

```text
answer = agent(task)
critique = llm("What is wrong or missing in this answer?\n" + answer)
return agent(task + "\nFix these issues:\n" + critique)
```

Small models are weak self-critics; use concrete checks (run the tests, validate the JSON, check the sources) wherever possible rather than "does this look good?".

## 9. Choosing a pattern

```mermaid
flowchart TD
    Q1{One call enough?} -->|yes| A[Single call]
    Q1 -->|no| Q2{Steps known upfront?}
    Q2 -->|yes| Q3{Independent?}
    Q3 -->|yes| P[Parallelization]
    Q3 -->|no| C[Prompt chaining / Routing]
    Q2 -->|no| Q4{Need tools & open-ended?}
    Q4 -->|yes| R[ReAct / Plan-and-execute]
    Q4 -->|no| O[Orchestrator-workers]
    A -.quality issues.-> E[Add evaluator-optimizer]
```

## Small local model notes

- Prefer chaining and routing over free-form agents: narrow prompts succeed more often.
- Use constrained or validated output for routers and evaluators.
- Cap rounds in every loop (reflection, re-planning, ReAct).
- Use the larger model (Azure) for planning and a small local one for simple steps.

## Key takeaways

- Most real systems are workflows plus a few agentic pieces.
- Add complexity only when measured results justify it.
- Gates, step limits, and concrete checks keep patterns reliable.

## Exercises

1. Build a chain: summarize a text, extract 3 action items, then draft an email.
2. Build a router with three categories and a safe default; test with ambiguous input.
3. Implement evaluator-optimizer for "write a haiku with exactly 17 syllables" using a code check instead of an LLM judge.
4. Extend the text-based ReAct example with a second tool and run it on a local model.
5. Compare plan-and-execute vs. ReAct on a multi-step task: count LLM calls and tokens.

**Next:** [Module 4: Multi-agent structures](04-multi-agent.md)
