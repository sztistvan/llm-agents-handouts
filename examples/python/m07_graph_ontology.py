"""Module 7 lesson: an ontology-guided graph, compared with the open one.

examples/ontology.json is a small ontology for the handouts: classes with a taxonomy (a WorkflowPattern is a Pattern) and
relations that say which classes they may connect (domain -> range). The lesson puts the ontology in the extraction
prompt and then VALIDATES every answer: unknown classes and relations are dropped, and a relation whose endpoints break
its domain or range is rejected with a reason. It compares the result with the open extraction of the same 6 chunks and
prints the schema and the guided graph as Mermaid diagrams. 6 LLM calls; the output varies a little from run to run.
Run:  python examples/python/m07_graph_ontology.py
"""
import json
import re

from graph_store import Graph, json_reply, mermaid_diagram, normalize
from retrieval import ROOT, chunk_markdown, load_markdown

ONTOLOGY = ROOT / "examples" / "ontology.json"
SECTIONS = ("Reflection vs. evaluator-optimizer", "9. Example: supervisor with workers as tools", "6. The agent loop, made reusable",
            "5. Swarm / handoff", "6. ReAct (reason + act)", "7. Debate and critic")
PALETTE = {"Pattern": ("#dcfce7", "#15803d"), "WorkflowPattern": ("#bbf7d0", "#15803d"), "AgentPattern": ("#d9f99d", "#4d7c0f"),
           "MultiAgentStructure": ("#a7f3d0", "#047857"), "Component": ("#fef9c3", "#a16207"), "File": ("#f1f5f9", "#475569"),
           "Parameter": ("#ffedd5", "#c2410c"), "Concept": ("#e0f2fe", "#0369a1")}


def ancestors(ontology: dict, name: str) -> set[str]:
    """A class and all its parents: a WorkflowPattern is also a Pattern."""
    found = set()
    while name:
        found.add(name)
        name = ontology["classes"][name]["parent"]
    return found


def system_prompt(ontology: dict) -> str:
    classes = "\n".join(f"- {name}: {spec['description']}" for name, spec in ontology["classes"].items())
    relations = "\n".join(f"- {name} ({' or '.join(spec['domain'])} -> {' or '.join(spec['range'])}): {spec['description']}"
                          for name, spec in ontology["relations"].items())
    return ("You extract a knowledge graph from a passage of technical documentation about building LLM agents. Use ONLY this ontology.\n"
            f"Classes:\n{classes}\nRelations (name, domain -> range):\n{relations}\n"
            'Reply with JSON only: {"entities": [{"name": "...", "class": "..."}], "relations": [{"source": "...", "relation": "...", "target": "..."}]}\n'
            "Rules: at most 8 entities with short, canonical, lower-case, singular names; every entity gets exactly one class from the list "
            "(Concept only if nothing else fits); every relation uses exactly one relation name from the list and two of your entities; "
            "leave out anything that does not fit the ontology.")


def validate(data: dict, ontology: dict):
    """Keep what follows the ontology. Returns (entities, accepted relations, rejected relations with the reason, notes)."""
    by_lower = {name.lower(): name for name in ontology["classes"]}
    entities: dict[str, tuple[str, str]] = {}
    notes = []
    for item in data.get("entities") or []:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            entity_id, cls = normalize(item["name"]), by_lower.get(str(item.get("class", "")).strip().lower())
            if entity_id and entity_id not in entities:
                if cls is None:
                    notes.append(f"class '{item.get('class')}' of '{item['name']}' is not in the ontology: it became Concept")
                    cls = "Concept"
                entities[entity_id] = (item["name"].strip().lower(), cls)
    accepted, rejected = [], []
    for item in data.get("relations") or []:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in ("source", "relation", "target")):
            continue
        triple = (item["source"], item["relation"], item["target"])
        name = re.sub(r"[^a-z0-9]+", "_", item["relation"].lower()).strip("_")
        source, target = normalize(item["source"]), normalize(item["target"])
        if name not in ontology["relations"]:
            rejected.append((triple, f"'{item['relation']}' is not a relation of the ontology"))
        elif source not in entities or target not in entities:
            rejected.append((triple, "an endpoint is not one of the extracted entities"))
        else:
            spec = ontology["relations"][name]
            if not set(spec["domain"]) & ancestors(ontology, entities[source][1]):
                rejected.append((triple, f"domain: a {entities[source][1]} cannot be the source of {name} (needs {' or '.join(spec['domain'])})"))
            elif not set(spec["range"]) & ancestors(ontology, entities[target][1]):
                rejected.append((triple, f"range: a {entities[target][1]} cannot be the target of {name} (needs {' or '.join(spec['range'])})"))
            else:
                accepted.append((source, name, target))
    return entities, accepted, rejected, notes


def schema_diagram(ontology: dict) -> str:
    """The ontology as a Mermaid class diagram: inheritance for the taxonomy, an arrow per allowed domain -> range."""
    lines = ["classDiagram"]
    lines += [f"    {spec['parent']} <|-- {name}" for name, spec in ontology["classes"].items() if spec["parent"]]
    lines += [f"    {d} --> {r} : {name}" for name, spec in ontology["relations"].items() for d in spec["domain"] for r in spec["range"]]
    return "\n".join(lines)


def block(title: str, text: str) -> None:
    print(f"\n{title}\n```mermaid\n{text}\n```")


if __name__ == "__main__":
    ontology = json.loads(ONTOLOGY.read_text(encoding="utf-8"))
    chunks = [c for doc in load_markdown() for c in chunk_markdown(doc)]
    graph = Graph.open()
    graph.sync(chunks)
    picked = [next(c for c in chunks if c["section"].endswith(s)) for s in SECTIONS]

    print(f"1. The ontology ({len(ontology['classes'])} classes, {len(ontology['relations'])} relations)")
    for name, spec in ontology["classes"].items():
        if not spec["parent"]:
            children = [n for n, s in ontology["classes"].items() if s["parent"] == name]
            print(f"   {name}" + (f"  (subclasses: {', '.join(children)})" if children else ""))
    for name, spec in ontology["relations"].items():
        print(f"   {name}: {' or '.join(spec['domain'])} -> {' or '.join(spec['range'])}")
    block("   As a diagram:", schema_diagram(ontology))

    print(f"\n2. Open extraction (Modules 7.4) vs ontology-guided extraction of the same {len(picked)} chunks")
    print(f"   {'chunk':44}{'open: ent / rel':>17}{'guided: ent / ok / rejected':>30}")
    all_entities: dict[str, tuple[str, str]] = {}
    all_edges: set[tuple[str, str, str]] = set()
    rejections, per_chunk = [], {}
    open_labels, guided_labels = set(), set()
    totals = {"open_e": 0, "open_r": 0, "e": 0, "ok": 0, "bad": 0, "fixed": 0}
    for chunk in picked:
        record = graph.extractions[chunk["hash"]]
        data = json_reply([{"role": "system", "content": system_prompt(ontology)},
                           {"role": "user", "content": f"Section: {chunk['section']}\n\nPassage:\n{chunk['text'][:3000]}"}])
        entities, accepted, rejected, notes = validate(data if isinstance(data, dict) else {}, ontology)
        per_chunk[chunk["hash"]] = (entities, accepted)
        for entity_id, value in entities.items():
            all_entities.setdefault(entity_id, value)
        all_edges.update(accepted)
        rejections += [(chunk["section"].split(" > ")[-1], t, why) for t, why in rejected]
        open_labels |= {" ".join(re.split(r"[-_\s]+", r["r"])) for r in record["relations"]}
        guided_labels |= {name for _, name, _ in accepted}
        totals["open_e"] += len(record["entities"]); totals["open_r"] += len(record["relations"])
        totals["e"] += len(entities); totals["ok"] += len(accepted); totals["bad"] += len(rejected); totals["fixed"] += len(notes)
        print(f"   {chunk['section'].split(' > ')[-1][:42]:44}{len(record['entities']):>8} /{len(record['relations']):>3}"
              f"{len(entities):>14} /{len(accepted):>3} /{len(rejected):>3}")
    print(f"   {'total':44}{totals['open_e']:>8} /{totals['open_r']:>3}{totals['e']:>14} /{totals['ok']:>3} /{totals['bad']:>3}")
    print(f"\n   distinct relation labels: open {len(open_labels)} (free text), guided {len(guided_labels)} (at most {len(ontology['relations'])})")
    classes: dict[str, int] = {}
    for _, cls in all_entities.values():
        classes[cls] = classes.get(cls, 0) + 1
    print("   guided entities by class:", ", ".join(f"{k} {v}" for k, v in sorted(classes.items(), key=lambda kv: (-kv[1], kv[0]))))
    print(f"   relations rejected by the validator: {totals['bad']} of {totals['ok'] + totals['bad']}; classes the model invented and the validator repaired: {totals['fixed']}")
    print("   some rejections (this is where the ontology bites):")
    for section, triple, why in rejections[:6]:
        print(f"     [{section[:28]}] {triple[0]} --{triple[1]}--> {triple[2]}: {why}")

    first_entities, first_edges = per_chunk[picked[0]["hash"]]
    block("\n3. The guided graph of the first chunk (colours are ontology classes; compare it with the open graph of m07_graph_diagrams):",
          mermaid_diagram([(i, n, c) for i, (n, c) in sorted(first_entities.items())], [(s, r.replace("_", " "), t) for s, r, t in sorted(set(first_edges))], styles=PALETTE))
    used = sorted({e for s, _, t in all_edges for e in (s, t)})
    block(f"\n4. The guided graph of all {len(picked)} chunks together:",
          mermaid_diagram([(i, all_entities[i][0], all_entities[i][1]) for i in used], [(s, r.replace("_", " "), t) for s, r, t in sorted(all_edges)], styles=PALETTE))
