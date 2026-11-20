"""Knowledge base lifecycle (Module 5, part 2): incremental updates, versions, deletions and safe releases.

Shared building block. Layers: llm_client (embed) -> retrieval (chunks, search) -> kb (lifecycle) -> m05_kb_update.

A knowledge base is a directory with numbered generation files (kb-0001.json, kb-0002.json, ...) and a CURRENT
file that names the live one. Updates are built in memory, written as a NEW generation, validated, and only then
made live by switching CURRENT (an atomic rename). The old generation stays on disk, so a rollback is one switch.

What it does for the problems of a changing corpus:
  * sync():       finds new, changed and deleted documents by content hash, re-embeds only new chunks
  * versions:     replaced chunks are kept with a validity period (valid_from / valid_to), searchable "as of" a date
  * purge():      removes old versions for good (compliance)
  * commit():     writes a generation, optionally only releases it if a validation passes
  * model guard:  refuses to mix vectors of different embedding models
"""
import json
import os
import time
from pathlib import Path

from llm_client import embed, embed_model
from retrieval import Retriever, VectorStore, chunk_markdown, embed_text, sha

CHUNKER = {"max_chars": 1500, "overlap_paragraphs": 1}  # recorded for reference: a changed chunker means a rebuild


class ModelMismatch(RuntimeError):
    """The knowledge base was embedded with another model than the one configured now."""


class KnowledgeBase:
    def __init__(self, directory, keep_versions: bool = False):
        self.dir = Path(directory)
        self.keep_versions = keep_versions  # True: replaced chunks stay (hidden) with a validity period
        self.generation = 0
        self.model = ""  # the embedding model of all vectors
        self.docs: dict[str, dict] = {}  # doc_id -> {hash, version, status: active|deleted, updated}
        self.records: list[dict] = []  # chunks plus doc_version, valid_from, valid_to (None = current)
        self.vectors: list[list[float]] = []  # parallel to records

    # ------------------------------------------------------------ files

    @classmethod
    def open(cls, directory, keep_versions: bool = False) -> "KnowledgeBase":
        """The live generation of the directory, or an empty knowledge base if there is none yet."""
        kb = cls(directory, keep_versions)
        pointer = kb.dir / "CURRENT"
        if pointer.exists():
            kb._load(kb.dir / pointer.read_text(encoding="utf-8").strip())
        return kb

    def _load(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        self.generation, self.model, self.keep_versions = data["generation"], data["model"], data["keep_versions"]
        self.docs, self.records, self.vectors = data["docs"], data["chunks"], data["vectors"]

    def _write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"generation": self.generation, "model": self.model, "keep_versions": self.keep_versions,
                "chunker": CHUNKER, "docs": self.docs, "chunks": self.records,
                "vectors": [[round(x, 6) for x in v] for v in self.vectors]}
        path.write_text(json.dumps(data), encoding="utf-8")

    # ------------------------------------------------------------ updating

    def sync(self, documents: list[dict], now: float | None = None) -> dict:
        """Bring the knowledge base in line with the source documents ({doc_id, title, text}, the whole current
        set). Documents are compared by content hash and chunks by their own hash, so only what really changed
        is embedded. Nothing is saved until commit(). Returns a report of what happened."""
        now = time.time() if now is None else now
        model = embed_model()
        if self.model and self.model != model:
            raise ModelMismatch(
                f"this knowledge base was embedded with '{self.model}' but the configured model is '{model}'. "
                "Vectors of different models cannot be mixed: call rebuild() to embed everything again.")
        self.model = model
        report = {"docs_added": [], "docs_changed": [], "docs_deleted": [], "docs_unchanged": 0,
                  "chunks_kept": 0, "chunks_added": 0, "chunks_removed": 0, "chunks_superseded": 0, "embedded": 0}
        by_hash = {r["hash"]: v for r, v in zip(self.records, self.vectors)}  # same content = same vector, reuse it
        old_by_doc: dict[str, list] = {}
        for record, vector in zip(self.records, self.vectors):
            old_by_doc.setdefault(record["doc_id"], []).append((record, vector))

        out: list[tuple[dict, list[float] | None]] = []  # None = not embedded yet
        source_ids = set()
        for doc in documents:
            doc_id, doc_hash = doc["doc_id"], sha(doc["text"])
            source_ids.add(doc_id)
            info, old = self.docs.get(doc_id), old_by_doc.get(doc_id, [])
            if info and info["status"] == "active" and info["hash"] == doc_hash:
                out += old
                report["docs_unchanged"] += 1
                continue
            version = info["version"] + 1 if info else 1
            report["docs_changed" if info and info["status"] == "active" else "docs_added"].append(doc_id)
            old_current = {r["hash"]: (r, v) for r, v in old if r["valid_to"] is None}
            out += [(r, v) for r, v in old if r["valid_to"] is not None]  # earlier versions stay as they are
            new_hashes = set()
            for chunk in chunk_markdown(doc, **CHUNKER):
                new_hashes.add(chunk["hash"])
                if chunk["hash"] in old_current:
                    record, vector = old_current[chunk["hash"]]
                    out.append(({**record, "id": chunk["id"]}, vector))  # same content; only its position may differ
                    report["chunks_kept"] += 1
                else:
                    record = {**chunk, "doc_version": version, "valid_from": now, "valid_to": None}
                    out.append((record, by_hash.get(chunk["hash"])))
                    report["chunks_added"] += 1
            for chunk_hash, (record, vector) in old_current.items():
                if chunk_hash not in new_hashes:
                    self._retire(out, record, vector, now, report)
            self.docs[doc_id] = {"hash": doc_hash, "version": version, "status": "active", "updated": now}

        for doc_id, old in old_by_doc.items():  # documents that are no longer in the source
            if doc_id in source_ids:
                continue
            if self.docs[doc_id]["status"] == "active":
                for record, vector in old:
                    if record["valid_to"] is None:
                        self._retire(out, record, vector, now, report)
                    else:
                        out.append((record, vector))
                self.docs[doc_id].update(status="deleted", updated=now)
                report["docs_deleted"].append(doc_id)
            else:
                out += old

        missing = [i for i, (_, vector) in enumerate(out) if vector is None]
        if missing:
            vectors = embed([embed_text(out[i][0]) for i in missing], kind="document")
            for i, vector in zip(missing, vectors):
                out[i] = (out[i][0], vector)
            report["embedded"] = len(missing)
        self.records = [record for record, _ in out]
        self.vectors = [vector for _, vector in out]
        return report

    def _retire(self, out: list, record: dict, vector: list[float], now: float, report: dict) -> None:
        """A chunk that is no longer in its document: keep it as an old version, or drop it."""
        if self.keep_versions:
            out.append(({**record, "valid_to": now}, vector))
            report["chunks_superseded"] += 1
        else:
            report["chunks_removed"] += 1

    def purge_history(self) -> int:
        """Remove every old version for good (the 'right to be forgotten', or just housekeeping)."""
        keep = [i for i, record in enumerate(self.records) if record["valid_to"] is None]
        removed = len(self.records) - len(keep)
        self.records = [self.records[i] for i in keep]
        self.vectors = [self.vectors[i] for i in keep]
        return removed

    def rebuild(self, documents: list[dict], now: float | None = None) -> dict:
        """Forget everything and embed all documents again (needed when the embedding model or the chunking changes)."""
        self.docs, self.records, self.vectors, self.model = {}, [], [], ""
        return self.sync(documents, now)

    # ------------------------------------------------------------ searching

    def retriever(self, as_of: float | None = None, include_superseded: bool = False) -> Retriever:
        """A retriever over what is visible: the current chunks (default), the chunks that were valid at the
        time `as_of`, or everything ever indexed (include_superseded)."""
        def visible(record: dict) -> bool:
            if include_superseded:
                return True
            if as_of is None:
                return record["valid_to"] is None
            return record["valid_from"] <= as_of and (record["valid_to"] is None or as_of < record["valid_to"])

        pairs = [(r, v) for r, v in zip(self.records, self.vectors) if visible(r)]
        store = VectorStore(self.model, str(self.generation))
        store.add([r for r, _ in pairs], [v for _, v in pairs])
        return Retriever([r for r, _ in pairs], store)

    def current_chunks(self) -> int:
        return sum(1 for record in self.records if record["valid_to"] is None)

    # ------------------------------------------------------------ releasing

    def commit(self, validate=None) -> bool:
        """Write the next generation and make it the live one.

        With `validate` (a function that gets this knowledge base and returns True or False) the generation is only
        released if the check passes; otherwise it is deleted, the live generation stays as it was, and False is
        returned (reopen the knowledge base afterwards: this object holds the rejected state). Switching CURRENT
        is an atomic rename, so a reader sees the old generation or the new one, never half of each."""
        previous, self.generation = self.generation, self.generation + 1
        path = self.dir / f"kb-{self.generation:04d}.json"
        self._write(path)
        if validate is not None and not validate(self):
            path.unlink()
            self.generation = previous
            return False
        temporary = self.dir / "CURRENT.tmp"
        temporary.write_text(path.name, encoding="utf-8")
        os.replace(temporary, self.dir / "CURRENT")
        return True

    def rollback(self) -> bool:
        """Make the previous generation live again (the files of old generations are kept)."""
        older = sorted(p for p in self.dir.glob("kb-*.json") if p.name < f"kb-{self.generation:04d}.json")
        if not older:
            return False
        (self.dir / "CURRENT.tmp").write_text(older[-1].name, encoding="utf-8")
        os.replace(self.dir / "CURRENT.tmp", self.dir / "CURRENT")
        self._load(older[-1])
        return True
