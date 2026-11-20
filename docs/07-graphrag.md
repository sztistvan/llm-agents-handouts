# Module 7: GraphRAG

**Goal:** understand what a knowledge graph adds to retrieval, build one from text with an LLM, use it for local and global questions, and judge honestly whether it is worth its cost.
**Time:** ~35 min. **Prerequisites:** [Module 5](05-rag.md) (the retriever and the golden-set method; Module 6, [knowledge bases](06-knowledge-bases.md), helps for the section on updates).

How this module relates to RAG (Module 5) and knowledge bases (Module 6): see the [overview in the README](../README.md#how-modules-5-to-7-fit-together).

## Setup

No new settings: GraphRAG uses the chat model and the embedding model you already configured ([setup](05-rag.md#setup-an-embedding-model)), and the handouts of Modules 1-4 as its documents. Run from the project root:

| Lesson | Python | JavaScript |
|---|---|---|
| Build the graph from the handouts | `python examples/python/m07_graph_build.py` | `node examples/js/m07_graph_build.mjs` |
| Local search, compared with plain RAG | `python examples/python/m07_graphrag.py` | `node examples/js/m07_graphrag.mjs` |
| Global search over communities | `python examples/python/m07_graphrag_global.py` | `node examples/js/m07_graphrag_global.mjs` |

The first run **makes one LLM call per chunk** (66 calls, about a minute on Azure with four in parallel). The graph is saved in `examples/.rag_index/graph-<chat model>.json` (git-ignored) and shared by Python and JavaScript; a different chat model or a changed extraction prompt makes a new graph. Summaries of communities are cached in the same file.

## 1. Why a graph?

Retrieval of chunks (Module 5) finds the passages *closest to the question*. Three kinds of questions escape it:

| Kind of question | Why plain retrieval struggles | What a graph adds |
|---|---|---|
| **Multi-hop**: "Which Module 2 component runs each worker of the Module 4 supervisor?" | The answer is spread over sections that do not share words with the question and with each other | Entities link the sections: *supervisor* is connected to *worker*, to *run_agent*, to the chunk that explains it |
| **Global**: "What are the main themes of the handouts?" | No chunk contains the answer, and top-k returns only a few chunks | Communities and their summaries describe the whole set |
| **Relations**: "What contrasts with what? What builds on what?" | Relations are implicit in prose | They are extracted once and stored as edges |

GraphRAG is therefore an *indexing* idea: spend LLM calls up front to turn text into entities and relations. Whether that pays off is an empirical question, and sections 6 and 9 give a sober answer.

## 2. What a knowledge graph is, and how this one is built

A knowledge graph is a set of **entities** (nodes) connected by **relations** (edges): `supervisor --manages--> worker`. Here an LLM reads every chunk and lists both.

```mermaid
flowchart LR
    C[Chunks] --> X["LLM extraction: entities and relations per chunk"] --> R[Entity resolution] --> G[("Graph, with the chunk of every fact")]
    G --> L["Local search: facts and chunks around the entities of the question"]
    G --> K[Communities] --> S[LLM summary per community] --> B["Global search: answer from the summaries"]
```

One design decision matters more than any other: the **source of truth is one extraction record per chunk** (the entities and relations the LLM found in it). The graph itself (nodes, edges, neighbours) is *derived* from the records. So every node and edge knows which chunks it came from (**provenance**), every fact can be cited, and updating the graph is the same operation as the sync of Module 6: extract new chunks, drop the records of removed chunks, rebuild. The building block is [`graph_store.py`](../examples/python/graph_store.py) / [`graph_store.mjs`](../examples/js/graph_store.mjs).

## 3. Extraction: `m07_graph_build`

`extract_chunk` makes one LLM call per chunk. The prompt asks for JSON only: at most 8 entities (short, singular, canonical names, with a type from a fixed list) and at most 8 relations (a short verb phrase connecting two of the entities). The reply goes through the parse-validate-retry pattern of Module 2: bad JSON is sent back with a request to fix it, names are normalized, relations whose endpoints were not listed get them added, and a chunk that never yields usable JSON is *not stored*, so the next sync retries it.

What came out for the 66 chunks of Modules 1-4 (the first run, with an Azure `gpt-5.4-nano` deployment and 4 calls in parallel; later runs report "0 extracted, 66 reused from the cache"):

```text
1. Extraction: one LLM call per chunk (66 chunks)
   66 chunks extracted, 0 reused from the cache, 0 failed, 54.1 s
2. What came out
   339 entities and 403 relations from 66 chunks (5.1 entities and 6.1 relations per chunk)
   entity types: concept 117, component 60, pattern 59, parameter 37, file 23, tool 23, other 10, provider 10
   best connected entities (name: relations, chunks):
     agent loop              34 relations, in 10 chunks
     tool_calls              17 relations, in 12 chunks
     run_agent               15 relations, in 4 chunks
   one chunk's extraction (Reflection vs. evaluator-optimizer):
     entities:  evaluator-optimizer (pattern), reflection (pattern), generate-critique-improve (concept), max-rounds (parameter), ...
     relations: evaluator optimizer --implements--> generate critique improve; reflection --implements--> generate critique improve; ...
```

Things to notice:

- **Cost scales with the corpus, not with the questions.** One call per chunk: 66 here, a million chunks means a million LLM calls (plus time under rate limits). Embeddings for plain RAG cost far less. The saved records make this a one-time cost per chunk and per extraction prompt.
- **Quality depends on the model.** A small local model may fail on JSON or invent relations; here all 66 chunks succeeded. Always count failures and read samples.
- **The output is messy even when it works:** relation labels came back as `uses-parameter` and `implemented-in`, some entities are `other`, and the same idea appears under several names (next section).

## 4. Entity resolution: the main quality problem

If `tool` and `tools`, or `handoff` and `handoffs`, become different nodes, the graph is fragmented and every search that follows it loses links. **Entity resolution** decides which names are one entity. The lesson applies one simple, safe rule on the *derived* graph (the records stay untouched): names that differ only by plural forms are merged into the variant that occurs in most chunks. That merged 6 variants (`gates` into `gate`, `handoffs` into `handoff`, `local models` into `local model`, ...). What remains is a list of judgement calls:

```text
   still suspicious (a person, a rule or an LLM has to decide whether these are one entity):
     0.75  'chain of thought'  ~  'chain of thought prompting'
     0.75  'multi agent research system'  ~  'multi agent system'
     0.67  'agent loop'  ~  'supervisor agent loop'
     0.67  'agent loop'  ~  'worker agent loop'
```

The last two show why this is hard: *a worker's agent loop is an agent loop*, but merging them would erase a distinction the handouts make. A **false merge** corrupts the graph silently, a **missed merge** only fragments it, so be conservative.

| Technique | Good for | Risk |
|---|---|---|
| Normalization (case, punctuation, plurals) | Spelling variants | Almost none |
| Alias tables (a reviewed list: `run_agent` = `run agent`) | Known synonyms and abbreviations | Maintenance |
| Embedding similarity of names or descriptions, with a threshold | Synonyms ("LLM" and "language model") | False merges: tune and review |
| An LLM judging candidate pairs | Hard, context-dependent cases | Cost, and the LLM's own mistakes |
| Human review of the top candidates | The few entities everything hangs on | Time |

The same goes for the **schema**. An open schema (the LLM chooses entity types and relation labels) is flexible but noisy, as above; a closed one (a fixed list of types and relations) is cleaner but misses what you did not anticipate.

## 5. Local search: `m07_graphrag`

For a question, local search uses the graph in two ways ([`Graph.local_context`](../examples/python/graph_store.py)):

1. **Facts for the prompt.** Seeds are the entities *named in the question* plus the entities of the top-5 retrieved chunks. The search walks two hops over the graph and keeps the best relations: first those that touch an entity named in the question, then the nearest, then the best supported. They go into the prompt as compact lines, each with the chunk it came from.
2. **Chunks the plain search missed.** Every entity is linked to the chunks that mention it, so each entity *named in the question* gets its own best chunk (a retrieval filtered by that entity). This is what brings in the second and third part of a multi-part question. Remaining room (at most 5 extra chunks in all) is filled with the chunks the kept facts came from.

A real run for the question above (shortened):

```text
   the graph's facts around them (best 8 of 30):
     - supervisor --manages--> worker  [04-multi-agent.md#4]
     - supervisor --calls as tools--> tools  [04-multi-agent.md#9]
     - m04_supervisor --builds--> supervisor  [04-multi-agent.md#9]
   context chunks (top-5 by search, plus the ones the graph added):
     top-5  04 > 3. Supervisor (orchestrator) pattern
     top-5  04 > 9. Example: supervisor with workers as tools
     ...
     GRAPH  03 > 4. Orchestrator-workers
     GRAPH  02 > 6. The agent loop, made reusable
   needed: ['04 > 9. Example: supervisor with workers as tools', '02 > 6. The agent loop, made reusable']
   all needed sections present: plain top-5 NO, graph local yes
```

The plain top-5 never reached the Module 2 section that explains `run_agent`; the graph brought it in. (This question was *chosen* for the lesson because it shows the mechanism. The next section is the fair test.) Note also that both the plain and the graph answer were correct here: the Module 4 chunk already says that workers call `run_agent`. Evidence coverage and answer correctness are different measures.

## 6. Does it help? An honest comparison

`examples/graph_golden.json` holds 13 questions: 10 multi-hop ones that each need evidence from 2 or 3 sections, and 3 single-hop controls. For each method the lesson checks whether the context contains **all** the needed sections (no LLM calls, so it is cheap and repeatable). Plain retrieval is shown at several context sizes, because "just retrieve more" is the obvious competitor:

| Method | Multi-hop: all evidence | Share of evidence found | Average context | Single-hop |
|---|---|---|---|---|
| Plain top-5 | 6 / 10 | 0.73 | 3,620 chars | 3 / 3 |
| Plain top-8 | 7 / 10 | 0.88 | 6,169 chars | 3 / 3 |
| Plain top-10 | 8 / 10 | 0.92 | 7,450 chars | 3 / 3 |
| GraphRAG local (5 + up to 5) | 8 / 10 | 0.88 | 6,101 chars | 3 / 3 |

How to read it:

- **On this corpus GraphRAG is not a breakthrough.** It matches plain top-10 (8 of 10) with about 18% less context, and beats top-8 by one question at a similar size. That is an efficiency gain, not a recall gain. Ten questions are few, and one question is 10 points.
- **Two questions fail for every method.** They ask for something spread over many places ("the limits that stop loops, in three handouts", "how too many tools connect small models and multi-agent design"), which no chunk-level or entity-level link captures well.
- **Why the gain is small here:** the corpus is small (66 chunks) and carefully structured, so hybrid search already puts most of the evidence in the top 10. The graph pays off where that is *not* true: large corpora, entity-heavy text (people, contracts, products, incidents) and questions that join facts from distant documents.
- **The costs are real:**

| | Plain RAG (Module 5) | GraphRAG local | GraphRAG global |
|---|---|---|---|
| Indexing | embeddings: cheap | one LLM call per chunk, plus resolution and review | the same, plus one call per community |
| Query | 1 retrieval, 1 call | 1 to 6 retrievals, a graph walk, 1 call | 1 call over all summaries |
| Explainability | the chunks | the chunks and the facts that led to them | the summaries |
| Typical failure | the right chunk is not retrieved | wrong or missing extractions, false merges | summaries that mix unrelated things |

## 7. Global search: `m07_graphrag_global`

"What are the main themes of the handouts as a whole?" has no answer in any chunk. GraphRAG groups the graph into **communities** (clusters of densely connected entities), has an LLM write a **title and summary** for each, and answers from the summaries. The lesson groups the graph with **label propagation**: every entity repeatedly takes the most common label among its neighbours, in a fixed order, so the result is the same every run. Production systems use the more refined **Leiden** algorithm, often with several levels of communities.

```text
1. Communities: 39 groups of at least 3 entities; sizes of the largest: [32, 25, 19, 18, 13, 12, 11, 8, 8, 8]
   1. 32 entities, e.g. reflection, evaluator-optimizer, react, agent patterns, llm_client chat
   2. 25 entities, e.g. agent loop, tool_calls, messages, conversation history, msg
   3. 19 entities, e.g. handoff, llm_choose, billing, constrained output, openai agents sdk
   ...
3. A global question: What are the main themes of the handouts as a whole?

   Plain RAG (top-5 chunks):
     I don't know based on the handouts ... The excerpts don't cover the handouts as a whole ...

   GraphRAG global (community summaries):
     Main themes across the handouts:
     - LLM Agent Orchestration via Evaluation-Optimization and Prompt Chaining
     - LLM Agent Orchestration with Tool-Calling and Traceability
     - LLM Agent Orchestration with Handoffs and Routing
     ...
```

This is where GraphRAG earns its keep: plain RAG correctly says it cannot answer, and the community summaries give a usable overview. It also shows the weak spots. The titles are repetitive, a community such as `m01, lm studio, run_in_parallel, azure, extract_task` mixes unrelated things, and the quality of the themes depends on the quality of the graph. A summary is cached by the content of its community, so only changed communities are summarized again. With hundreds of communities the summaries no longer fit one prompt: the real method *maps* the question over each summary and then *reduces* the partial answers.

## 8. Keeping the graph up to date

Because every record knows its chunk, the sync of Module 6 applies directly: chunks are compared by hash, only new chunks are extracted, the records of removed chunks are dropped, and the derived graph is rebuilt (cheap). The lesson changes one sentence in one chunk, on a copy of the graph:

```text
   re-extracted 1, kept 65, removed the record of 1 (the old text)
   entities 339 -> 340; new: ['evaluate-optimize', 'tree of thought']; no longer in the graph: ['evaluate_optimize']
   (re-extracting the chunk can change more than the sentence you added: an LLM does not give the same answer twice)
```

What to plan for:

- **Re-extraction is not reproducible.** The new record differs from the old one in more than the added sentence (`evaluate_optimize` became `evaluate-optimize`), which resolution has to absorb.
- **Merges and communities are derived, so they follow.** An update can change which entities merge, and therefore the communities, and the summaries whose signature changed are regenerated.
- **Deletion must reach the derived data:** the records, the entities and relations that only came from the deleted text, the community summaries built from them, and the cache. Verify by searching the graph.
- **A new extraction prompt or schema invalidates everything** (`PROMPT_VERSION` in the code), like a new embedding model in Module 6: plan it as a release, with a validation gate.

## 9. When (not) to use GraphRAG

Try the cheaper steps first; each one fixes a different problem:

| Step | Try it when | Cost |
|---|---|---|
| Hybrid search and a good chunking (Module 5) | Always | Low |
| More candidates and a reranker | The right chunk is found but ranked low | A call per question |
| Query decomposition or multi-query, agentic RAG (Module 5) | Multi-part questions | More calls per question |
| **GraphRAG** | Many entities that recur across many documents, questions that join facts from far apart, or **global questions** about the whole set | LLM extraction of the whole corpus, resolution, maintenance |

| Use GraphRAG when | Skip it when |
|---|---|
| You need overviews and themes ("what are the main risks across these reports?") | Most questions are answered by one passage |
| The text is full of recurring entities and relations (cases, contracts, products, people) | The corpus is small or well structured, and hybrid search already works |
| You can afford the extraction and review of entities | You cannot evaluate it: without a multi-hop golden set you will not know whether it helped |

## From tutorial to production

The lessons run on 66 chunks. What changes with a real corpus, and what to look for:

| Area | In this tutorial | What to look for in production |
|---|---|---|
| Extraction cost and model | 66 calls, a small model, 4 in parallel | Calls grow with the corpus: budget them, use a cheaper model for extraction, batch and rate-limit, keep records so that nothing is extracted twice |
| Extraction quality | Counts and a few samples | Failure rate, valid-JSON rate, sampled review, the effect of a model or prompt change on the graph, a versioned prompt |
| Schema | Open: the LLM chooses types and labels | A governed list of entity types and relations when the domain is stable; a mapping for the rest |
| Entity resolution | Plural forms plus a list of suspects | Alias tables, embedding clustering with review, an LLM judge for hard pairs, and a record of every merge so it can be undone |
| Storage | A JSON file and in-memory dictionaries | A graph database (for example Neo4j) or a store built for it, indexes on entity names and chunk links, backups |
| Communities | Label propagation, one level | Leiden, several levels, summaries per level, a plan for recomputing and re-summarizing after changes |
| Updates | Hash-based re-extraction | Change feeds, idempotent jobs, validation gates before a new graph goes live ([Module 6](06-knowledge-bases.md)), deletion that reaches records, caches and summaries |
| Evaluation | 13 coverage questions, no answer scoring | A multi-hop and a global question set from real users, answer-level checks (LLM judges are noisy: repeat them), cost and latency next to quality |
| Security | None | Permissions apply to **facts** too: an edge extracted from a restricted chunk must not leak through a neighbour. Keep the chunk of every edge and filter by it |
| Libraries | Plain code | Microsoft's GraphRAG and LightRAG implement indexing, communities and query modes; Neo4j offers a GraphRAG package. Use one when you need scale, and keep this module's questions to evaluate it |

## Key takeaways

- GraphRAG is an *indexing* investment: an LLM turns text into entities and relations once, and searches then follow the links.
- Keep an extraction record per chunk and derive the graph from it: you get provenance, citations and incremental updates for free.
- Entity resolution is the main quality problem. Merge conservatively: a false merge is worse than a missed one.
- Local search brings facts and the chunks that plain retrieval missed; global search answers about the whole set from community summaries.
- Measure against the obvious competitor (just retrieve more). Here GraphRAG matched top-10 with less context, and its clearest win was the global question.
- Try hybrid search, reranking and multi-query retrieval first; use GraphRAG for recurring entities, joined facts and global questions.

## Exercises

1. Change the extraction prompt (for example, limit the relations to a fixed list), raise `PROMPT_VERSION` and rebuild. How do the statistics change, and what happens to local-search coverage?
2. Add an alias table to the resolution (`run_agent` = `run agent`, `m02 agent loop` = `agent loop`). Does coverage change? Which merge is risky?
3. Vary `hops` (1, 2, 3) and `extra_chunks` (0, 3, 5, 8) in `local_context`. Plot coverage against average context size, together with plain top-k.
4. Add five multi-hop questions to `graph_golden.json` where you expect the graph to help. Does it?
5. Implement multi-query retrieval (Module 5, exercise 4) and compare it with graph local search on the golden set.
6. Change `min_size` and `rounds` in `communities`. Which communities are meaningful and which are noise?
7. Delete a section from the handouts and re-sync: which entities, facts and summaries disappear or become stale?

## Further reading

- Edge et al., [*From Local to Global: A Graph RAG Approach to Query-Focused Summarization*](https://arxiv.org/abs/2404.16130) (2024): the paper behind Microsoft's GraphRAG, with entity extraction, Leiden communities and global search
- Microsoft, [GraphRAG documentation](https://microsoft.github.io/graphrag/) and [repository](https://github.com/microsoft/graphrag)
- Guo et al., [*LightRAG: Simple and Fast Retrieval-Augmented Generation*](https://arxiv.org/abs/2410.05779) (2024) and its [repository](https://github.com/HKUDS/LightRAG): a lighter design with incremental updates in mind
- Peng et al., [*Graph Retrieval-Augmented Generation: A Survey*](https://arxiv.org/abs/2408.08921) (2024)
- Gutiérrez et al., [*HippoRAG: Neurobiologically Inspired Long-Term Memory for Large Language Models*](https://arxiv.org/abs/2405.14831) (2024): graph-based retrieval as a memory model, relevant for Module 8
- Hogan et al., [*Knowledge Graphs*](https://arxiv.org/abs/2003.02320) (2020): the background on graphs, schemas and resolution
- Traag et al., [*From Louvain to Leiden: guaranteeing well-connected communities*](https://arxiv.org/abs/1810.08473) (2018) and Raghavan et al., [*Near linear time algorithm to detect community structures in large-scale networks*](https://arxiv.org/abs/0709.2938) (2007, label propagation)
- Neo4j, [GraphRAG for Python](https://neo4j.com/docs/neo4j-graphrag-python/current/)

**Next:** Module 8: Memory (coming next)
