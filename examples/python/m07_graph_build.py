"""Module 7 lesson: build a knowledge graph from the handouts.

An LLM reads every chunk once and lists the entities (concepts, patterns, components, files, ...) and the relations
between them. The result is a graph in which every node and edge remembers the chunks it came from. This lesson shows
the cost, what comes out, what is still wrong (entity resolution), and how an update touches only the changed chunk.
The first run makes one LLM call per chunk (about a minute on Azure); later runs reuse the saved graph.
Run:  python examples/python/m07_graph_build.py
"""
from graph_store import Graph
from retrieval import chunk_markdown, load_markdown, sha  # noqa: E402

if __name__ == "__main__":
    chunks = [c for doc in load_markdown() for c in chunk_markdown(doc)]
    graph = Graph.open()

    print(f"1. Extraction: one LLM call per chunk ({len(chunks)} chunks), cached by chunk hash in {graph.path.name}")
    report = graph.sync(chunks)
    graph.save()
    print(f"   {report['extracted']} chunks extracted, {report['kept']} reused from the cache, {report['failed']} failed, "
          f"{report['seconds']:.1f} s")

    stats = graph.stats()
    print("\n2. What came out")
    print(f"   {stats['entities']} entities and {stats['relations']} relations from {stats['chunks']} chunks "
          f"({stats['entities'] / stats['chunks']:.1f} entities and {stats['relations'] / stats['chunks']:.1f} relations per chunk)")
    print("   entity types:", ", ".join(f"{kind} {n}" for kind, n in sorted(stats["types"].items(), key=lambda kv: (-kv[1], kv[0]))))
    print("   best connected entities (name: relations, chunks):")
    for name, relations, in_chunks in graph.top_entities(8):
        print(f"     {name:22} {relations:3} relations, in {in_chunks} chunks")
    target = next(c for c in chunks if c["section"].endswith("Reflection vs. evaluator-optimizer"))
    record = graph.extractions[target["hash"]]
    print(f"   one chunk's extraction ({target['section'].split(' > ')[-1]}):")
    print("     entities: ", ", ".join(f"{e['name']} ({e['type']})" for e in record["entities"]))
    print("     relations:", "; ".join(f"{r['s']} --{r['r']}--> {r['t']}" for r in record["relations"][:5]))

    print("\n3. Entity resolution: the same thing under several names is the main quality problem")
    print(f"   merged automatically (plural forms): {stats['merged_variants']}, for example",
          ", ".join(f"'{a}' -> '{b}'" for a, b in graph.merged[:4]))
    print("   still suspicious (a person, a rule or an LLM has to decide whether these are one entity):")
    for similarity, a, b in graph.near_duplicates(limit=6):
        print(f"     {similarity:.2f}  '{a}'  ~  '{b}'")

    print("\n4. An update: change ONE chunk and only that chunk is extracted again (on a copy; the saved graph stays)")
    text = target["text"] + "\n\nA third variant, tree of thought, explores several candidate answers in parallel and keeps the best one."
    changed = [{**c, "text": text, "hash": sha(c["section"] + "\n" + text)} if c["hash"] == target["hash"] else c for c in chunks]
    trial = graph.copy()
    update = trial.sync(changed)
    print(f"   re-extracted {update['extracted']}, kept {update['kept']}, removed the record of {update['removed']} (the old text)")
    before = {node["name"] for node in graph.nodes.values()}
    after = {node["name"] for node in trial.nodes.values()} if trial.stats() else set()
    print(f"   entities {stats['entities']} -> {len(after)}; new: {sorted(after - before) or 'none'}; "
          f"no longer in the graph: {sorted(before - after) or 'none'}")
    print("   (re-extracting the chunk can change more than the sentence you added: an LLM does not give the same answer twice)")
    print("   every fact knows its source chunk, so nothing else had to be touched: the same idea as the sync of Module 6")
