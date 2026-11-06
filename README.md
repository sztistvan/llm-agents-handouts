# LLM Agents: Handouts & Tutorials

Short, practical handouts on building agents with large language models (LLMs).
Written in English for developers who are new to agents.

## Principles

- **Framework-agnostic first**: examples use plain Python/JavaScript and an OpenAI-compatible API. Popular frameworks are surveyed, with a few LangGraph examples.
- **Markdown + Mermaid diagrams + pseudocode** in every handout; each ends with exercises.
- **Two backends, one config**: local models via LM Studio, or Azure OpenAI. Switch with environment variables only.
- **Small local models are assumed**: handouts note where tool calling and structured output are unreliable and how to cope.

## Backend configuration (planned)

| Variable | LM Studio | Azure OpenAI |
|---|---|---|
| `LLM_PROVIDER` | `lmstudio` | `azure` |
| Base URL | `http://localhost:1234/v1` | `https://<resource>.openai.azure.com/openai/v1` |
| `LLM_API_KEY` | any string | your Azure key |
| `LLM_MODEL` | loaded model name | deployment name |

## Course outline

| # | Module | Topics |
|---|---|---|
| 1 | Foundations & history | Symbolic agents, expert systems, RL agents, ReAct, function calling, modern SDKs; agent vs. chatbot vs. workflow |
| 2 | Core building blocks | LLM call, prompts, tool calling, structured output, memory and context, the agent loop |
| 3 | Patterns | ReAct, plan-and-execute, reflection, routing, prompt chaining, parallelization, orchestrator-workers, evaluator-optimizer |
| 4 | Multi-agent structures | Supervisor, hierarchical, swarm/handoff, debate and critic |
| 5 | RAG, memory & tools | Retrieval, short/long-term memory, MCP |
| 6 | Frameworks landscape | LangGraph, OpenAI Agents SDK, AutoGen, CrewAI, Semantic Kernel; when to use none |
| 7 | Best practices | Simplicity, guardrails, evaluation, observability, cost/latency, security (prompt injection), human-in-the-loop |
| 8 | Capstone examples | Research assistant; coding/file helper |

## Layout

```
docs/                 handouts, one per module (01-foundations.md, ...)
diagrams/             Mermaid sources and shared diagrams
examples/python/      framework-agnostic Python + shared llm_client
examples/js/          framework-agnostic JavaScript + shared llm_client
examples/langgraph/   LangGraph examples
```

## Status

- [x] Scope agreed
- [x] Folder scaffold
- [x] Shared `llm_client` (Python, JS)
- [x] Module 1: [Foundations & history](docs/01-foundations.md)
- [x] Module 2: [Core building blocks](docs/02-building-blocks.md)
- [ ] Modules 3-8
