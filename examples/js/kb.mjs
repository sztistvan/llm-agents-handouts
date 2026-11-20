// Knowledge base lifecycle (Module 5, part 2): incremental updates, versions, deletions and safe releases.
//
// Shared building block. Layers: llm_client (embed) -> retrieval (chunks, search) -> kb (lifecycle) -> m05_kb_update.
// The generation files have the same format as the Python ones, so both languages can open the same knowledge base.
//
// A knowledge base is a directory with numbered generation files (kb-0001.json, kb-0002.json, ...) and a CURRENT
// file that names the live one. Updates are built in memory, written as a NEW generation, validated, and only then
// made live by switching CURRENT (an atomic rename). The old generation stays on disk, so a rollback is one switch.
//
// What it does for the problems of a changing corpus:
//   sync():      finds new, changed and deleted documents by content hash, re-embeds only new chunks
//   versions:    replaced chunks are kept with a validity period (valid_from / valid_to), searchable "as of" a date
//   purgeHistory(): removes old versions for good (compliance)
//   commit():    writes a generation, optionally only releases it if a validation passes
//   model guard: refuses to mix vectors of different embedding models
import { existsSync, mkdirSync, readFileSync, readdirSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { embed, embedModel } from "./llm_client.mjs";
import { Retriever, VectorStore, chunkMarkdown, embedText, sha } from "./retrieval.mjs";

const CHUNKER = { maxChars: 1500, overlapParagraphs: 1 }; // recorded for reference: a changed chunker means a rebuild

export class ModelMismatch extends Error {}

export class KnowledgeBase {
  constructor(directory, keepVersions = false) {
    this.dir = directory;
    this.keepVersions = keepVersions; // true: replaced chunks stay (hidden) with a validity period
    this.generation = 0;
    this.model = ""; // the embedding model of all vectors
    this.docs = {}; // doc_id -> {hash, version, status: active|deleted, updated}
    this.records = []; // chunks plus doc_version, valid_from, valid_to (null = current)
    this.vectors = []; // parallel to records
  }

  // ------------------------------------------------------------ files

  /** The live generation of the directory, or an empty knowledge base if there is none yet. */
  static open(directory, keepVersions = false) {
    const kb = new KnowledgeBase(directory, keepVersions);
    const pointer = join(directory, "CURRENT");
    if (existsSync(pointer)) kb.#load(join(directory, readFileSync(pointer, "utf8").trim()));
    return kb;
  }

  #load(path) {
    const data = JSON.parse(readFileSync(path, "utf8"));
    this.generation = data.generation;
    this.model = data.model;
    this.keepVersions = data.keep_versions;
    this.docs = data.docs;
    this.records = data.chunks;
    this.vectors = data.vectors;
  }

  #write(path) {
    mkdirSync(this.dir, { recursive: true });
    const vectors = this.vectors.map((v) => v.map((x) => Math.round(x * 1e6) / 1e6));
    writeFileSync(path, JSON.stringify({
      generation: this.generation, model: this.model, keep_versions: this.keepVersions,
      chunker: { max_chars: CHUNKER.maxChars, overlap_paragraphs: CHUNKER.overlapParagraphs },
      docs: this.docs, chunks: this.records, vectors }), "utf8");
  }

  // ------------------------------------------------------------ updating

  /**
   * Bring the knowledge base in line with the source documents ({doc_id, title, text}, the whole current set).
   * Documents are compared by content hash and chunks by their own hash, so only what really changed is
   * embedded. Nothing is saved until commit(). Returns a report of what happened.
   */
  async sync(documents, now = Date.now() / 1000) {
    const model = embedModel();
    if (this.model && this.model !== model) {
      throw new ModelMismatch(`this knowledge base was embedded with '${this.model}' but the configured model is '${model}'. ` +
        "Vectors of different models cannot be mixed: call rebuild() to embed everything again.");
    }
    this.model = model;
    const report = { docs_added: [], docs_changed: [], docs_deleted: [], docs_unchanged: 0,
      chunks_kept: 0, chunks_added: 0, chunks_removed: 0, chunks_superseded: 0, embedded: 0 };
    const byHash = new Map(this.records.map((r, i) => [r.hash, this.vectors[i]])); // same content = same vector, reuse it
    const oldByDoc = new Map();
    this.records.forEach((record, i) => {
      if (!oldByDoc.has(record.doc_id)) oldByDoc.set(record.doc_id, []);
      oldByDoc.get(record.doc_id).push([record, this.vectors[i]]);
    });

    const out = []; // [record, vector], vector null = not embedded yet
    const sourceIds = new Set();
    for (const doc of documents) {
      const docId = doc.doc_id;
      const docHash = sha(doc.text);
      sourceIds.add(docId);
      const info = this.docs[docId];
      const old = oldByDoc.get(docId) ?? [];
      if (info && info.status === "active" && info.hash === docHash) {
        out.push(...old);
        report.docs_unchanged++;
        continue;
      }
      const version = info ? info.version + 1 : 1;
      (info && info.status === "active" ? report.docs_changed : report.docs_added).push(docId);
      const oldCurrent = new Map(old.filter(([r]) => r.valid_to === null).map(([r, v]) => [r.hash, [r, v]]));
      out.push(...old.filter(([r]) => r.valid_to !== null)); // earlier versions stay as they are
      const newHashes = new Set();
      for (const chunk of chunkMarkdown(doc, CHUNKER)) {
        newHashes.add(chunk.hash);
        if (oldCurrent.has(chunk.hash)) {
          const [record, vector] = oldCurrent.get(chunk.hash);
          out.push([{ ...record, id: chunk.id }, vector]); // same content; only its position may differ
          report.chunks_kept++;
        } else {
          out.push([{ ...chunk, doc_version: version, valid_from: now, valid_to: null }, byHash.get(chunk.hash) ?? null]);
          report.chunks_added++;
        }
      }
      for (const [hash, [record, vector]] of oldCurrent) {
        if (!newHashes.has(hash)) this.#retire(out, record, vector, now, report);
      }
      this.docs[docId] = { hash: docHash, version, status: "active", updated: now };
    }

    for (const [docId, old] of oldByDoc) { // documents that are no longer in the source
      if (sourceIds.has(docId)) continue;
      if (this.docs[docId].status === "active") {
        for (const [record, vector] of old) {
          if (record.valid_to === null) this.#retire(out, record, vector, now, report);
          else out.push([record, vector]);
        }
        Object.assign(this.docs[docId], { status: "deleted", updated: now });
        report.docs_deleted.push(docId);
      } else {
        out.push(...old);
      }
    }

    const missing = out.map(([, v], i) => (v === null ? i : -1)).filter((i) => i >= 0);
    if (missing.length) {
      const vectors = await embed(missing.map((i) => embedText(out[i][0])), "document");
      missing.forEach((i, j) => { out[i][1] = vectors[j]; });
      report.embedded = missing.length;
    }
    this.records = out.map(([record]) => record);
    this.vectors = out.map(([, vector]) => vector);
    return report;
  }

  /** A chunk that is no longer in its document: keep it as an old version, or drop it. */
  #retire(out, record, vector, now, report) {
    if (this.keepVersions) {
      out.push([{ ...record, valid_to: now }, vector]);
      report.chunks_superseded++;
    } else {
      report.chunks_removed++;
    }
  }

  /** Remove every old version for good (the 'right to be forgotten', or just housekeeping). */
  purgeHistory() {
    const keep = this.records.map((r, i) => (r.valid_to === null ? i : -1)).filter((i) => i >= 0);
    const removed = this.records.length - keep.length;
    this.records = keep.map((i) => this.records[i]);
    this.vectors = keep.map((i) => this.vectors[i]);
    return removed;
  }

  /** Forget everything and embed all documents again (needed when the embedding model or the chunking changes). */
  async rebuild(documents, now = Date.now() / 1000) {
    this.docs = {};
    this.records = [];
    this.vectors = [];
    this.model = "";
    return this.sync(documents, now);
  }

  // ------------------------------------------------------------ searching

  /** A retriever over what is visible: the current chunks (default), the chunks that were valid at the time
   *  `asOf`, or everything ever indexed (includeSuperseded). */
  retriever({ asOf = null, includeSuperseded = false } = {}) {
    const visible = (record) => {
      if (includeSuperseded) return true;
      if (asOf === null) return record.valid_to === null;
      return record.valid_from <= asOf && (record.valid_to === null || asOf < record.valid_to);
    };
    const idx = this.records.map((r, i) => (visible(r) ? i : -1)).filter((i) => i >= 0);
    const store = new VectorStore(this.model, String(this.generation));
    store.add(idx.map((i) => this.records[i]), idx.map((i) => this.vectors[i]));
    return new Retriever(idx.map((i) => this.records[i]), store);
  }

  currentChunks() {
    return this.records.filter((r) => r.valid_to === null).length;
  }

  // ------------------------------------------------------------ releasing

  /**
   * Write the next generation and make it the live one.
   * With `validate` (a function that gets this knowledge base and returns true or false) the generation is only
   * released if the check passes; otherwise it is deleted, the live generation stays as it was, and false is
   * returned (reopen the knowledge base afterwards: this object holds the rejected state). Switching CURRENT is
   * an atomic rename, so a reader sees the old generation or the new one, never half of each.
   */
  async commit(validate = null) {
    const previous = this.generation;
    this.generation = previous + 1;
    const name = `kb-${String(this.generation).padStart(4, "0")}.json`;
    const path = join(this.dir, name);
    this.#write(path);
    if (validate && !(await validate(this))) {
      unlinkSync(path);
      this.generation = previous;
      return false;
    }
    const temporary = join(this.dir, "CURRENT.tmp");
    writeFileSync(temporary, name, "utf8");
    renameSync(temporary, join(this.dir, "CURRENT"));
    return true;
  }

  /** Make the previous generation live again (the files of old generations are kept). */
  rollback() {
    const current = `kb-${String(this.generation).padStart(4, "0")}.json`;
    const older = readdirSync(this.dir).filter((f) => /^kb-\d+\.json$/.test(f) && f < current).sort();
    if (!older.length) return false;
    const target = older[older.length - 1];
    writeFileSync(join(this.dir, "CURRENT.tmp"), target, "utf8");
    renameSync(join(this.dir, "CURRENT.tmp"), join(this.dir, "CURRENT"));
    this.#load(join(this.dir, target));
    return true;
  }
}
