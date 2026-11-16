# LLM Agents: Handouts & Tutorials

Short, practical handouts on building agents with large language models (LLMs).
Written in English for developers who are new to agents.

## Principles

- **Framework-agnostic first**: examples use plain Python/JavaScript and an OpenAI-compatible API. Popular frameworks are surveyed, with a few LangGraph examples.
- **Markdown + Mermaid diagrams + pseudocode** in every handout; each ends with exercises.
- **Several backends, one config**: Azure OpenAI, OpenRouter, or local models via LM Studio. Switch with environment variables only.
- **Small local models are assumed**: handouts note where tool calling and structured output are unreliable and how to cope.

## Quick start

```powershell
# Python examples (from the project root)
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env        # then fill in the settings of your provider (see below)
python examples/python/m01_minimal_agent.py

# JavaScript examples: Node.js 20.12+ only, no install step
node examples/js/m01_minimal_agent.mjs
```

On macOS/Linux activate with `source .venv/bin/activate` and copy with `cp`. Each handout lists the example files it uses.

## Backend configuration

Copy `.env.example` to `.env` and fill in the provider(s) you use. `LLM_PROVIDER` (default `azure`) selects
a block of three settings named after it: `<PROVIDER>_BASE_URL`, `<PROVIDER>_API_KEY`, `<PROVIDER>_MODEL`.

| `LLM_PROVIDER` | Base URL | API key | Model |
|---|---|---|---|
| `azure` | `https://<resource>.openai.azure.com/openai/v1` | your Azure key | deployment name |
| `openrouter` | `https://openrouter.ai/api/v1` | your OpenRouter key | model slug |
| `lmstudio` | `http://localhost:1234/v1` | any non-empty string | name shown at `http://localhost:1234/v1/models` |

Any other OpenAI-compatible endpoint works the same way (e.g. `LLM_PROVIDER=ollama` with `OLLAMA_*` variables).
Switch provider for one run without editing `.env` (real environment variables override `.env`):

```powershell
# PowerShell (Windows): the variable stays set in this window until you remove it
$env:LLM_PROVIDER = "lmstudio"
python examples/python/m01_minimal_agent.py
Remove-Item Env:LLM_PROVIDER      # back to the provider from .env
```

```bash
# bash / zsh / Git Bash
LLM_PROVIDER=lmstudio python examples/python/m01_minimal_agent.py
```

Or simply change the `LLM_PROVIDER=` line in `.env`.

### Running the JavaScript examples

The `.mjs` files run with plain Node.js (20.12 or newer, no `npm install` needed; the client uses built-in `fetch` and reads `.env` itself). Run them from the project root, like the Python ones:

```powershell
node examples/js/m01_minimal_agent.mjs
```

The shared client (`llm_client.mjs` / `llm_client.py`) is imported by every example automatically; you never run it first.
The provider switch works the same way (`$env:LLM_PROVIDER = "lmstudio"` in PowerShell, `LLM_PROVIDER=lmstudio node ...` in bash).

## Course outline

| # | Module | Topics |
|---|---|---|
| 1 | Foundations & history | Symbolic agents, expert systems, RL agents, ReAct, function calling, modern SDKs; agent vs. chatbot vs. workflow |
| 2 | Core building blocks | LLM call, prompts, tool calling, structured output, memory and context, the agent loop |
| 3 | Patterns | ReAct, plan-and-execute, reflection, routing, prompt chaining, parallelization, orchestrator-workers, evaluator-optimizer |
| 4 | Multi-agent structures | Supervisor, hierarchical, swarm/handoff, debate and critic |
| 5 | RAG, memory & tools *(planned)* | Retrieval, short/long-term memory, MCP |
| 6 | Frameworks landscape *(planned)* | LangGraph, OpenAI Agents SDK, AutoGen, CrewAI, Semantic Kernel; when to use none |
| 7 | Best practices *(planned)* | Simplicity, guardrails, evaluation, observability, cost/latency, security (prompt injection), human-in-the-loop |
| 8 | Capstone examples *(planned)* | Research assistant; coding/file helper |

## Layout

```
docs/                 handouts, one per module (01-foundations.md, ...)
diagrams/             Mermaid sources and shared diagrams (planned; diagrams currently live inside the handouts)
examples/python/      framework-agnostic Python + shared llm_client
examples/js/          framework-agnostic JavaScript + shared llm_client
examples/langgraph/   LangGraph examples (planned, Module 6)
requirements.txt      Python dependencies (JavaScript needs none)
.env.example          backend settings template: copy to .env
```

## Status

- [x] Scope agreed
- [x] Folder scaffold
- [x] Shared `llm_client` (Python, JS)
- [x] Module 1: [Foundations & history](docs/01-foundations.md)
- [x] Module 2: [Core building blocks](docs/02-building-blocks.md)
- [x] Module 3: [Patterns](docs/03-patterns.md)
- [x] Module 4: [Multi-agent structures](docs/04-multi-agent.md)
- [ ] Modules 5-8
