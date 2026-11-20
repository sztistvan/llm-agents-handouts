# Module 6: Knowledge Bases: Updates, Versions and Scale

**Goal:** keep a RAG system correct and fast as its documents change, are replaced and deleted, and as the corpus grows, and release index changes safely.
**Time:** ~30 min. **Prerequisites:** [Module 5](05-rag.md) (chunks, the retriever, hybrid search and the golden set are reused here).

How this module relates to RAG (Module 5) and [GraphRAG](07-graphrag.md) (Module 7): see the [overview in the README](../README.md#how-modules-5-to-7-fit-together).

The index of Module 5 is built once. A real **knowledge base** lives for years: documents are edited, new versions replace old ones, some must disappear, the corpus grows from hundreds to millions of chunks, and one day the embedding model changes. Two lessons cover this: `m06_kb_update` (the lifecycle) and `m06_kb_scale` (growth), on top of a shared building block, [`kb.py`](../examples/python/kb.py) / [`kb.mjs`](../examples/js/kb.mjs).

## Setup

The lessons use the embedding model configured in Module 5 ([setup](05-rag.md#setup-an-embedding-model)) and the handouts of Modules 1-4 as their documents. Run from the project root:

| Lesson | Python | JavaScript |
|---|---|---|
| A knowledge base that changes | `python examples/python/m06_kb_update.py` | `node examples/js/m06_kb_update.mjs` |
| Growth: exact vs approximate search | `python examples/python/m06_kb_scale.py` | `node examples/js/m06_kb_scale.mjs` |

`m06_kb_update` needs an embedding model (it has no keyword-only mode) and writes only to `examples/.rag_index/kb_demo/` (git-ignored). `m06_kb_scale` needs no model at all, it uses synthetic vectors.

## 1. What goes wrong if you ignore it

| Event | What goes wrong | What to do | Lesson step |
|---|---|---|---|
| A document is new or changed | You re-embed everything every night (slow, costly), or you never update (stale answers) | Detect changes by content hash, embed only new chunks | 1 to 3 |
| A new version replaces an old one | Old and new text are both retrieved, and the answer contradicts itself | Give chunks a validity period, search the current one by default, "as of" for history | 3 |
| A document is deleted | The system still answers from it (a legal and trust problem) | Tombstone it, purge old versions, clean caches and backups | 4 and 5 |
| An update is bad (a parser bug, a wrong edit) | Recall drops silently for everybody | Build a new generation, validate it on the golden set, then switch | 6 |
| The embedding model or the chunking changes | Mixed vectors give meaningless scores | Record the model, refuse to mix, rebuild as a planned release | 8 |
| The corpus grows | Latency, cost, and recall all suffer | The levers of section 7 | `m06_kb_scale` |

## 2. Incremental sync: pay for the change, not for the corpus

`KnowledgeBase.sync(documents)` compares each document with the stored one by **content hash**. For a changed document it re-chunks and compares the **chunks** by their own hash (section path plus text). Chunks whose hash is known keep their vector; only new chunks go to the embedding model. The identity of a chunk is its content, not its position, because an inserted paragraph shifts every position after it. Real output of the lesson (shortened):

```text
1. First sync (day 0): every chunk is new
   chunks:    0 kept, 66 added          EMBEDDED:  66 chunks sent to the embedding model
2. The same sync again
   documents: 4 unchanged               EMBEDDED:  0 chunks
3. Edit ONE table row in 03-patterns.md
   documents: ~1 changed ['03-patterns.md'], 3 unchanged
   chunks:    15 kept, 1 added, 1 superseded (old version kept)
   EMBEDDED:  1 chunks
```

The cost of an update follows the size of the *change*, and running the sync twice changes nothing (it is **idempotent**, so a scheduled job can retry safely). Two practical points: structure-aware chunks keep a change local (an edit touches one section, not the rest of the document), and detecting deletions needs the full list of current documents from the source (or delete events from it), because a document that simply stops arriving is invisible otherwise.

## 3. Versions and "as of" queries

When a chunk is replaced, `keep_versions=True` keeps the old one with a validity period (`valid_from`, `valid_to`) instead of dropping it. Searches default to the current chunks; `retriever(as_of=date)` answers "what did the handbook say on that date?":

```text
   today:        | LLM calls | 2 at least, up to `1 + 2 * MAX_ROUNDS` | 3 (2 if you skip the final revision) |
   as of day 5:  | LLM calls | 2 at least, up to `1 + 2 * MAX_ROUNDS` | Always 3 |
```

| Policy | When it fits | Watch out for |
|---|---|---|
| Replace: only the latest is stored | Most documentation, FAQs | No history, no audit, no "what applied on that date" |
| Keep old versions hidden, with validity periods | Policies, contracts, regulations: you may need to prove what applied then | Index size, and a purge path for deletions |
| Keep all versions searchable | Research archives, where old versions are content | Contradictions in one answer: always show version and date in the citation, and prefer one version per document |

Never let two versions of one document compete in the same prompt. Related: **duplicates**. Exact duplicates are found by hash. Near-duplicates (the same text with small edits, copies in several places) fill the top results with the same content and push out other answers: detect them (for example by embedding similarity above a high threshold) and keep one.

## 4. Deleting for real

A deleted document is first *hidden* (its chunks get a `valid_to`), which is why "as of day 25" still finds it. For a **compliance** deletion that is not enough: the content must leave the index.

```text
   'When is the release freeze?' -> 06-notes.md > Release freeze
   after the delete:             -> NOT FOUND in the top 3 chunks
   as of day 25 (still kept):    -> 06-notes.md > Release freeze
   purged old versions: 2 ...
   as of day 25 now:             -> NOT FOUND in the top 3 chunks
```

(A search always returns *something*, so the lesson checks the content of the top results, not whether the list is empty.) In production the content must also leave every place derived from it: the keyword index, embedding and result caches, logs, backups, evaluation sets and, with GraphRAG ([Module 7](07-graphrag.md#9-keeping-the-graph-up-to-date)), the entities and relations extracted from it. Verify by searching for the deleted text.

## 5. Releasing safely: generations and a validation gate

Updating the live index in place means a crash or a bad batch leaves it half-changed, and everybody sees it. The lesson works with **generations**: each commit writes a new file (`kb-0006.json`), validates it, and only then switches the `CURRENT` pointer (an atomic rename, so a reader sees the old generation or the new one, never half of each). The previous generation stays on disk, so a rollback is one switch. The validation is the golden set from [Module 5, section 6](05-rag.md#6-measuring-recall-m05_rag_eval):

```text
   live generation 5: recall@5 = 1.00
   (a bad edit: a whole section was deleted by mistake)
   validation of generation 6: recall@5 = 0.94 (must be at least 1.00)
   -> REJECTED: the live generation does not change
   ...
   (the bad edit is reverted; now a harmless edit in 04-multi-agent.md)
   validation of generation 6: recall@5 = 1.00 (must be at least 1.00)
   -> released as generation 6
```

The bad edit would have gone live unnoticed in an in-place update. Good gates check recall on the golden set, include questions that must return "no answer", and sanity-check sizes (the number of chunks should not suddenly halve). Vector databases and search services offer the same idea under names such as aliases or index swaps.

## 6. Changing the embedding model or the chunking

Vectors of different models are not comparable, and neither are vectors made from differently cut chunks of the same model. The knowledge base records the model it was built with and refuses to mix:

```text
   refused: this knowledge base was embedded with 'some-other-embedding-model' but the configured model is
   'text-embedding-3-small'. Vectors of different models cannot be mixed: call rebuild() to embed everything again.
   a rebuild would embed all 66 chunks again (about 12,058 tokens): plan it like a release
```

The cost is every chunk once: tokens times your model's price per million tokens, plus the time under the provider's rate limits. For a large corpus, rebuild into a **new generation** while the old one keeps serving, compare recall on the golden set (a "better" model can be worse on your data), then switch. Providers retire models, so plan this before you are forced to.

## 7. Many documents, and keeping recall

As a corpus grows, recall tends to fall: more near-duplicates and similar sections compete for the top places, generic text crowds the embedding space, and approximate search starts to skip true neighbours. The levers, with what each fixes and how to check it:

| Lever | Fixes | Cost or risk | How to check |
|---|---|---|---|
| Hybrid search (BM25 plus embeddings) | Exact terms, names, identifiers | Almost none | Golden-set recall, as in Module 5, section 6 |
| A wide candidate pool plus a reranker | The right chunk is retrieved but not at the top | Latency and cost per question | Compare recall@20 with recall@5: a big gap means the reranker has room to help |
| Metadata filters and routing (product, language, date, tenant) | Removes distractors, shrinks the search space | Needs clean metadata | Recall with and without the filter |
| Hierarchical retrieval (pick documents by their summaries first, then search inside them) | Very large corpora of long documents | Two stages, summary quality | Does stage 1 select the right document? |
| Better chunks: section paths, parent-child, context per chunk | Chunks that lose their meaning out of context | A re-index | Golden-set recall |
| Query rewriting, decomposition, multi-query | Vague or multi-part questions | An extra LLM call | Recall on the hard questions |
| De-duplication | Duplicates filling the top results | Extra processing | Share of duplicates in the top results |
| An approximate index, tuned and measured | Search latency at scale | Recall lost to approximation | Recall against exact search, see below |

**Approximate search, measured.** Brute force compares the query with every vector, so its time grows with the corpus. Approximate nearest-neighbour (ANN) indexes look at a part of the vectors. `m06_kb_scale` builds a simple IVF index (k-means groups the vectors into lists; a query scans only the `nprobe` closest lists) on synthetic clustered vectors and compares it with exact search. Real output for 10,000 vectors of 64 dimensions (recall is identical in Python and JavaScript; times are Python's, JavaScript is about 7 times faster):

| Method | ms per query | Share of vectors scanned | recall@10 against exact |
|---|---|---|---|
| exact | 30.1 | 100% | 1.00 |
| IVF, `nprobe=1` | 1.3 | 2% | 0.83 |
| IVF, `nprobe=2` | 2.0 | 3% | 0.95 |
| IVF, `nprobe=4` | 3.9 | 4% | 1.00 |
| IVF, `nprobe=8` | 5.6 | 9% | 1.00 |

What to take from it:

- **It is a trade-off you set.** Scanning 2% of the vectors is 20 times faster and loses 17% of the true neighbours; scanning 4% recovers all of them on this data. A parameter such as `nprobe` (or `ef_search` in HNSW) is a recall dial.
- **The same setting loses more on a bigger index.** With 2,000 vectors, `nprobe=1` already reached 0.97; with 10,000 it fell to 0.83. Tune again as the corpus grows.
- **Brute force does not disappear overnight.** Exact search cost about 47 ns per vector element in this pure-Python teaching code, which extrapolates to about 72 s per query for 1,000,000 vectors of 1536 numbers (JavaScript: about 10 s). Optimized libraries are far faster, so the real switch point depends on your latency target and hardware: measure it, do not guess.
- **The data here is synthetic.** Real embeddings are not neat clusters, so your numbers will differ. Measure two recalls on your own data: the ANN recall against exact search, and the end-to-end golden-set recall, because approximation is only one of the places recall is lost.

Keep the golden set growing with the corpus, slice its metrics by document type and age, and read the queries that returned nothing or only weak matches: they show where the knowledge base has holes.

## 8. Permissions on a shared knowledge base

When different users may see different documents, apply the permission as a **filter at retrieval** (the `where` argument of [Module 5, section 5](05-rag.md#5-better-retrieval-m05_rag_hybrid), with an owner or group stored as metadata on each chunk). Never retrieve first and hide afterwards: the hidden text has already been ranked and may already be in a prompt. A permission change touches only metadata, so it needs no re-embedding, but it must reach the index quickly, or a person who lost access still gets answers from the document.

## From tutorial to production

The examples are small on purpose. What changes with a real knowledge base, and what to look for:

| Area | In this tutorial | What to look for in production |
|---|---|---|
| Updates and versions | `sync` by content hash, validity periods | A reliable source of truth (a crawler, a CMS, change events), idempotent jobs, a freshness target and a metric for the lag, one version of a document per answer, visible version and date in citations |
| Deletion and retention | `purge_history` | Deletion reaches the index, caches, logs, backups, evaluation sets and derived data. Test it by searching. Keep a record of what was deleted and when |
| Index releases | generations, a golden-set gate, a pointer switch, rollback | Blue/green indexes, gates for recall, "no answer" cases and size, automatic rollback, a changelog of what each release contained |
| Scale | brute force, and a synthetic IVF experiment | An ANN index in a vector database or search service, recall against exact search as a tracked number, sharding or routing by tenant or topic, re-tuning as the corpus grows, a rebuild plan for model changes |
| Ingestion | markdown files | Parsers per format (PDF, HTML, Office, scans with OCR) and checks on what they extract, tables and images, source credentials and rate limits, errors and retries per source, a way to re-run one failed document |

## Key takeaways

- A knowledge base changes: detect changes by content hash and embed only what is new, so the cost follows the change and not the corpus.
- Keep old versions with a validity period instead of mixing them, delete for real when you must, and release a new index only after it passes the golden set.
- Vectors of different embedding models cannot be mixed: record the model and treat a change as a planned rebuild.
- Approximate search trades recall for speed through a dial you must measure on your own data, and re-tune as the corpus grows.

## Exercises

1. In `m06_kb_update` set `keep_versions=False` and compare the reports of steps 3 and 4. What do you gain, and what can you no longer answer?
2. Add a second check to the release gate: the number of current chunks must not change by more than 20%. Test it with an edit that removes half of a handout.
3. Add near-duplicate detection to `sync`: report new chunks whose vector is more than 0.95 cosine-similar to an existing one. Which threshold separates "copy with small edits" from "similar topic"?
4. In `m06_kb_scale` set `CLUSTERS = 5` and `SIGMA = 0.3` (data with less structure). How does recall at `nprobe=1` change, and what does that say about trusting numbers from synthetic data?
5. Rebuild the knowledge base with a different `max_chars` in `CHUNKER` (see `kb.py`). Why must this be treated like a model change?

## Further reading

- Scaling the search: Malkov and Yashunin, [*Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs*](https://arxiv.org/abs/1603.09320) (HNSW, 2016); Johnson et al., [*Billion-scale similarity search with GPUs*](https://arxiv.org/abs/1702.08734) (the FAISS paper, 2017); [FAISS](https://github.com/facebookresearch/faiss), [pgvector](https://github.com/pgvector/pgvector), [Qdrant](https://qdrant.tech/documentation/) and [Azure AI Search vector search](https://learn.microsoft.com/en-us/azure/search/vector-search-overview)
- Choosing and tuning an index: the FAISS wiki pages [*Faiss indexes*](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes) and [*Indexing 1M vectors*](https://github.com/facebookresearch/faiss/wiki/Indexing-1M-vectors), and [ANN-Benchmarks](https://ann-benchmarks.com/) for the recall-versus-speed curves of many libraries

**Next:** [Module 7: GraphRAG](07-graphrag.md)
