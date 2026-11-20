# LLM Agents: Handouts & Tutorials

Short, practical handouts on building agents with large language models (LLMs).
Written for developers who are new to agents.

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

From Module 5 on, an embedding model is also needed: `<PROVIDER>_EMBED_MODEL` (for Azure the name of an embedding deployment such as `text-embedding-3-small`, for LM Studio for example `text-embedding-nomic-embed-text-v1.5`). Without it, only keyword search works. How to create the Azure deployment: [Module 5](docs/05-rag.md#setup-an-embedding-model).

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
| 1 | [Foundations & history](docs/01-foundations.md) | Symbolic agents, expert systems, RL agents, ReAct, function calling, modern SDKs; agent vs. chatbot vs. workflow |
| 2 | [Core building blocks](docs/02-building-blocks.md) | LLM call, prompts, tool calling, structured output, memory and context, the agent loop |
| 3 | [Patterns](docs/03-patterns.md) | ReAct, plan-and-execute, reflection, routing, prompt chaining, parallelization, orchestrator-workers, evaluator-optimizer |
| 4 | [Multi-agent structures](docs/04-multi-agent.md) | Supervisor, hierarchical, swarm/handoff, debate and critic |
| 5 | [RAG](docs/05-rag.md) | Embeddings, chunking, hybrid search, reranking, evaluating recall, agentic RAG |
| 6 | [Knowledge bases](docs/06-knowledge-bases.md) | Incremental sync, versions, deletions, safe index releases, embedding-model changes, recall at scale, permissions |
| 7 | [GraphRAG](docs/07-graphrag.md) | Knowledge graph vs taxonomy vs ontology, entities and relations from text, entity resolution, local and global search, an honest comparison with plain RAG, updates, graph databases (Neo4j, FalkorDB, Memgraph, PostgreSQL) |
| 8 | [Graph databases](docs/08-graph-databases.md) | Where the graph lives in production: what a store must do, property graph vs RDF, Cypher/GQL, Neo4j vs FalkorDB vs Memgraph vs PostgreSQL, how to choose and migrate |
| 9 | [Memory](docs/09-memory.md) | Short-term (trim, summarize, persist), long-term (remember/recall/forget, reconcile on write, automatic extraction), facts with history, production issues (privacy, isolation, poisoning) |
| 10 | [Tools & MCP](docs/10-tools-mcp.md) | Designing tools, many tools (cost, shortlists, overlapping tools), the Model Context Protocol (a tiny server and client by hand), tool poisoning and defences |
| 10a | [MCP in practice](docs/10a-mcp-in-practice.md) | Adding, checking and reviewing MCP servers in Claude Desktop, the GitHub Copilot app and VS Code; useful servers (GitHub, Context7, Microsoft Learn, Playwright); using them safely |
| 11 | Frameworks landscape *(planned)* | LangGraph, OpenAI Agents SDK, AutoGen, CrewAI, Semantic Kernel; when to use none |
| 12 | Best practices *(planned)* | Simplicity, guardrails, evaluation, observability, cost/latency, security (prompt injection), human-in-the-loop |
| 13 | Capstone examples *(planned)* | Research assistant; coding/file helper |

### How Modules 5 to 7 fit together

Modules 5 to 7 all deal with giving an agent knowledge it was not trained on. They are separate modules because the three topics have different learning goals and different practical problems:

| | **5 RAG** | **6 Knowledge bases** | **7 GraphRAG** |
|---|---|---|---|
| **Main question** | How do I find the right text and answer from it? | How do I keep that working as documents change and grow? | What if the answer lives in the relations between documents? |
| **Learning objectives** | Explain the pipeline. Chunk, embed, and run dense, keyword and hybrid search. Measure recall@k and MRR. Choose naive or agentic RAG. | Design a sync with content hashes. Handle versions and deletion. Release through a validation gate. Plan model changes. Reason about scale and recall. | Explain what a graph adds (multi-hop and "global" questions) and how it relates to taxonomies and ontologies. Build one from LLM extraction. Run local and global search. Choose a storage. Judge when it is worth the cost. |
| **Practical issues** | Chunking pitfalls, similarity thresholds per model, a small golden set, injection through documents | Hash-based change detection, version policy, purging for compliance, rollback, rebuild cost, recall lost to approximate search, permissions | Extraction cost (one LLM call per chunk) and quality with small models, duplicate entities, provenance back to chunks, community summaries, updates, hard evaluation |
| **Production checklist focuses on** | Retrieval quality | Operations | Cost and complexity |

Read them in this order: Module 6 builds on the retriever and the golden set of Module 5, and GraphRAG's hardest part, keeping the graph up to date, reuses the sync and provenance ideas of Module 6. You can skip Module 7 without losing the thread. [Module 8](docs/08-graph-databases.md) is the production companion of Module 7 (where the graph is stored); read it when you take a GraphRAG system towards production.

## Layout

```
docs/                 handouts, one per module (01-foundations.md, ...)
diagrams/             Mermaid sources and shared diagrams (planned; diagrams currently live inside the handouts)
examples/python/      framework-agnostic Python; shared building blocks + mNN_* lessons
examples/js/          framework-agnostic JavaScript; same file names (.mjs)
                      shared building blocks (no prefix): llm_client (talk to the model, embeddings),
                      agent (the agent loop: Tool, run_agent / runAgent),
                      retrieval (chunking, vector store, BM25, hybrid search), rag (cited answers, reranking),
                      kb (a knowledge base that changes: sync, versions, deletions, safe releases),
                      graph_store (knowledge graph: LLM extraction with provenance, local and global search),
                      memory (short-term trim/summarize, long-term memory store, facts with history),
                      mcp_client (a minimal MCP client: start a server, list and call its tools as Tool objects)
                      lessons (mNN_ prefix): one runnable example per topic, run from the project root
examples/rag_golden.json   the golden question set of the retrieval evaluation (Module 5)
examples/graph_golden.json multi-hop questions for the GraphRAG comparison (Module 7)
examples/tools_catalog.json 36 office tools and 12 questions for the tool-selection experiment (Module 10)
examples/ontology.json     a small ontology for the handouts: classes, taxonomy, relations with domain and range (Module 7)
examples/langgraph/   LangGraph examples (planned, Module 11)
requirements.txt      Python dependencies (JavaScript needs none)
.env.example          backend settings template: copy to .env
```

## Status

- [x] Scope agreed
- [x] Folder scaffold
- [x] Shared `llm_client` and `agent` (Python, JS)
- [x] Module 1: [Foundations & history](docs/01-foundations.md)
- [x] Module 2: [Core building blocks](docs/02-building-blocks.md)
- [x] Module 3: [Patterns](docs/03-patterns.md)
- [x] Module 4: [Multi-agent structures](docs/04-multi-agent.md)
- [x] Module 5: [RAG](docs/05-rag.md)
- [x] Module 6: [Knowledge bases](docs/06-knowledge-bases.md)
- [x] Module 7: [GraphRAG](docs/07-graphrag.md)
- [x] Module 8: [Graph databases](docs/08-graph-databases.md)
- [x] Module 9: [Memory](docs/09-memory.md)
- [x] Module 10: [Tools & MCP](docs/10-tools-mcp.md)
- [x] Module 10a: [MCP in practice](docs/10a-mcp-in-practice.md)
- [ ] Modules 11-13 (next: Frameworks landscape)

## Further reading and link check

Each module ends with a *Further reading* list of papers, guides and documentation, all with links. Pages move, so if a link breaks, search by title. To re-check every external link (needs network and `curl`):

```bash
python tools/check_links.py
```

## License

[MIT](LICENSE) © 2026 István Szatmári
