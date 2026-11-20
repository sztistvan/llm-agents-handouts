"""Module 6 lesson: a knowledge base that changes. Incremental sync, versions, deletions, a safe release.

The lesson copies the Modules 1-4 handouts into a work folder, indexes them, and then changes, adds and deletes
documents. Watch how many chunks are embedded each time (that is the cost), what a search finds "as of" an
earlier date, and how a bad update is stopped before it goes live. It uses a fake calendar (day 0, day 10, ...)
so that its output is the same every run. Needs an embedding model. Run:  python examples/python/m06_kb_update.py
"""
import re
import shutil
import sys

from kb import KnowledgeBase, ModelMismatch
from llm_client import embed_model, has_embeddings
from retrieval import CORPUS, DOCS_DIR, INDEX_DIR, load_golden, load_markdown, recall_at_k

WORK = INDEX_DIR / "kb_demo"
SOURCE, KB_DIR = WORK / "source", WORK / "kb"
T0, DAY = 1_700_000_000.0, 86_400.0
day = lambda n: T0 + n * DAY  # a fake calendar: day(0), day(10), ...


def docs():
    return load_markdown(SOURCE, "*.md")


def show(report: dict) -> None:
    print(f"   documents: +{len(report['docs_added'])} added {report['docs_added']}, ~{len(report['docs_changed'])} changed "
          f"{report['docs_changed']}, -{len(report['docs_deleted'])} deleted {report['docs_deleted']}, {report['docs_unchanged']} unchanged")
    print(f"   chunks:    {report['chunks_kept']} kept, {report['chunks_added']} added, {report['chunks_superseded']} "
          f"superseded (old version kept), {report['chunks_removed']} removed")
    print(f"   EMBEDDED:  {report['embedded']} chunks sent to the embedding model  <- this is the cost of the update")


def find(retriever, question: str, phrase: str) -> str:
    """Where does the answer live? Looks for the phrase in the top 3 chunks (a search always returns
    *something*, so 'nothing found' has to be checked on the content)."""
    for _, chunk in retriever.search(question, k=3, mode="hybrid"):
        if phrase in chunk["section"] + "\n" + chunk["text"]:
            line = next((ln.strip() for ln in chunk["text"].splitlines() if phrase in ln), "")
            return f"{chunk['doc_id']} > {chunk['section'].split(' > ')[-1]}" + (f"\n        {line}" if line else "")
    return "NOT FOUND in the top 3 chunks"


if __name__ == "__main__":
    if not has_embeddings():
        sys.exit("This lesson needs an embedding model: set <PROVIDER>_EMBED_MODEL in .env (see docs/05-rag.md).")
    print(f"Embedding model: {embed_model()}. Work folder: {WORK}")
    shutil.rmtree(WORK, ignore_errors=True)
    SOURCE.mkdir(parents=True)
    for path in sorted(DOCS_DIR.glob(CORPUS)):
        shutil.copy(path, SOURCE / path.name)

    print("\n1. First sync (day 0): every chunk is new, so every chunk is embedded")
    kb = KnowledgeBase.open(KB_DIR, keep_versions=True)
    show(kb.sync(docs(), now=day(0)))
    kb.commit()

    print("\n2. The same sync again: nothing changed, so nothing is embedded (content hashes match)")
    kb = KnowledgeBase.open(KB_DIR)
    show(kb.sync(docs(), now=day(1)))

    print("\n3. Edit ONE table row in 03-patterns.md (day 10) and sync: only the chunk that contains it is new")
    path = SOURCE / "03-patterns.md"
    text = path.read_text(encoding="utf-8")
    old_row = "| LLM calls | 2 at least, up to `1 + 2 * MAX_ROUNDS` | Always 3 |"
    assert old_row in text, "the row this lesson edits was not found; the handout changed"
    path.write_text(text.replace(old_row, "| LLM calls | 2 at least, up to `1 + 2 * MAX_ROUNDS` | 3 (2 if you skip the final revision) |"), encoding="utf-8")
    show(kb.sync(docs(), now=day(10)))
    kb.commit()
    question = "How many LLM calls does reflection make?"
    print("   today:          ", find(kb.retriever(), question, "LLM calls"))
    print("   as of day 5:    ", find(kb.retriever(as_of=day(5)), question, "LLM calls"))
    print("   (the old version is kept with a validity period: queries default to the current one)")

    print("\n4. A new document appears (day 20), later it is deleted (day 30)")
    note = SOURCE / "06-notes.md"
    note.write_text("# Team notes\n\n## Release freeze\n\nThe team agreed on a release freeze from 15 December. During the freeze "
                    "only fixes for production incidents may be merged, and every fix needs two reviewers.\n", encoding="utf-8")
    kb = KnowledgeBase.open(KB_DIR)
    show(kb.sync(docs(), now=day(20)))
    kb.commit()
    print("   'When is the release freeze?' ->", find(kb.retriever(), "When is the release freeze?", "release freeze"))
    note.unlink()
    show(kb.sync(docs(), now=day(30)))
    kb.commit()
    print("   after the delete:             ->", find(kb.retriever(), "When is the release freeze?", "release freeze"))
    print("   as of day 25 (still kept):    ->", find(kb.retriever(as_of=day(25)), "When is the release freeze?", "release freeze"))

    print("\n5. A deleted document must be gone for good (compliance): purge the history")
    print(f"   chunks before: {len(kb.records)}, purged old versions: {kb.purge_history()}, chunks after: {len(kb.records)}")
    kb.commit()
    print("   as of day 25 now:             ->", find(kb.retriever(as_of=day(25)), "When is the release freeze?", "release freeze"))

    print("\n6. A safe release: build the next generation, validate it on the golden questions, only then make it live")
    golden = load_golden()
    kb = KnowledgeBase.open(KB_DIR)
    baseline = recall_at_k(kb.retriever(), golden, k=5)
    print(f"   live generation {kb.generation}: recall@5 = {baseline:.2f}")

    def passes(candidate: KnowledgeBase) -> bool:
        recall = recall_at_k(candidate.retriever(), golden, k=5)
        print(f"   validation of generation {candidate.generation}: recall@5 = {recall:.2f} (must be at least {baseline:.2f})")
        return recall >= baseline

    path = SOURCE / "03-patterns.md"
    good_text = path.read_text(encoding="utf-8")
    path.write_text(re.sub(r"### Reflection vs\. evaluator-optimizer.*?(?=## 9\. Choosing a pattern)", "", good_text, flags=re.S), encoding="utf-8")
    print("   (a bad edit: a whole section was deleted by mistake)")
    show(kb.sync(docs(), now=day(40)))
    released = kb.commit(validate=passes)
    print("   ->", "released" if released else "REJECTED: the live generation does not change")
    kb = KnowledgeBase.open(KB_DIR)
    print(f"   live generation is still {kb.generation}; the section is still found:",
          find(kb.retriever(), "difference between reflection and evaluator-optimizer", "Reflection vs. evaluator-optimizer"))

    path.write_text(good_text, encoding="utf-8")
    page = SOURCE / "04-multi-agent.md"
    page.write_text(page.read_text(encoding="utf-8").replace("Keep depth to 2 levels;", "Keep depth to 2 levels (3 at most);"), encoding="utf-8")
    print("   (the bad edit is reverted; now a harmless edit in 04-multi-agent.md)")
    show(kb.sync(docs(), now=day(41)))
    released = kb.commit(validate=passes)
    print("   ->", f"released as generation {kb.generation}" if released else "REJECTED")

    print("\n7. Rollback is one pointer switch (the files of older generations are kept)")
    print(f"   generation files: {[p.name for p in sorted(KB_DIR.glob('kb-*.json'))]}")
    kb.rollback()
    print(f"   after rollback the live generation is {kb.generation}")

    print("\n8. Changing the embedding model: the knowledge base refuses to mix vectors")
    kb = KnowledgeBase.open(KB_DIR)
    kb.model = "some-other-embedding-model"  # pretend it had been built with another model
    try:
        kb.sync(docs(), now=day(50))
    except ModelMismatch as error:
        print("   refused:", error)
    chars = sum(len(r["text"]) for r in kb.records if r["valid_to"] is None)
    print(f"   a rebuild would embed all {kb.current_chunks()} chunks again (about {chars // 4:,} tokens): plan it like a release")
