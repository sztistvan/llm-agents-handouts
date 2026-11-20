// Module 6 lesson: a knowledge base that changes. Incremental sync, versions, deletions, a safe release.
//
// The lesson copies the Modules 1-4 handouts into a work folder, indexes them, and then changes, adds and deletes
// documents. Watch how many chunks are embedded each time (that is the cost), what a search finds "as of" an
// earlier date, and how a bad update is stopped before it goes live. It uses a fake calendar (day 0, day 10, ...)
// so that its output is the same every run. Needs an embedding model. Run:  node examples/js/m06_kb_update.mjs
import { copyFileSync, mkdirSync, readFileSync, readdirSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { KnowledgeBase, ModelMismatch } from "./kb.mjs";
import { embedModel, hasEmbeddings } from "./llm_client.mjs";
import { CORPUS, DOCS_DIR, INDEX_DIR, loadGolden, loadMarkdown, recallAtK } from "./retrieval.mjs";

const WORK = join(INDEX_DIR, "kb_demo");
const SOURCE = join(WORK, "source");
const KB_DIR = join(WORK, "kb");
const T0 = 1_700_000_000;
const DAY = 86_400;
const day = (n) => T0 + n * DAY; // a fake calendar: day(0), day(10), ...

const docs = () => loadMarkdown(SOURCE, /\.md$/);
const read = (path) => readFileSync(path, "utf8");

function show(report) {
  const list = (a) => JSON.stringify(a).replace(/","/g, "', '").replace(/"/g, "'");
  console.log(`   documents: +${report.docs_added.length} added ${list(report.docs_added)}, ~${report.docs_changed.length} changed ` +
    `${list(report.docs_changed)}, -${report.docs_deleted.length} deleted ${list(report.docs_deleted)}, ${report.docs_unchanged} unchanged`);
  console.log(`   chunks:    ${report.chunks_kept} kept, ${report.chunks_added} added, ${report.chunks_superseded} ` +
    `superseded (old version kept), ${report.chunks_removed} removed`);
  console.log(`   EMBEDDED:  ${report.embedded} chunks sent to the embedding model  <- this is the cost of the update`);
}

/** Where does the answer live? Looks for the phrase in the top 3 chunks (a search always returns *something*,
 *  so 'nothing found' has to be checked on the content). */
async function find(retriever, question, phrase) {
  for (const [, chunk] of await retriever.search(question, 3, { mode: "hybrid" })) {
    if ((`${chunk.section}\n${chunk.text}`).includes(phrase)) {
      const line = chunk.text.split("\n").find((ln) => ln.includes(phrase))?.trim() ?? "";
      return `${chunk.doc_id} > ${chunk.section.split(" > ").pop()}` + (line ? `\n        ${line}` : "");
    }
  }
  return "NOT FOUND in the top 3 chunks";
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (!hasEmbeddings()) {
    console.error("This lesson needs an embedding model: set <PROVIDER>_EMBED_MODEL in .env (see docs/05-rag.md).");
    process.exit(1);
  }
  console.log(`Embedding model: ${embedModel()}. Work folder: ${WORK}`);
  rmSync(WORK, { recursive: true, force: true });
  mkdirSync(SOURCE, { recursive: true });
  for (const name of readdirSync(DOCS_DIR).filter((f) => CORPUS.test(f)).sort()) copyFileSync(join(DOCS_DIR, name), join(SOURCE, name));

  console.log("\n1. First sync (day 0): every chunk is new, so every chunk is embedded");
  let kb = KnowledgeBase.open(KB_DIR, true);
  show(await kb.sync(docs(), day(0)));
  await kb.commit();

  console.log("\n2. The same sync again: nothing changed, so nothing is embedded (content hashes match)");
  kb = KnowledgeBase.open(KB_DIR);
  show(await kb.sync(docs(), day(1)));

  console.log("\n3. Edit ONE table row in 03-patterns.md (day 10) and sync: only the chunk that contains it is new");
  const patterns = join(SOURCE, "03-patterns.md");
  const oldRow = "| LLM calls | 2 at least, up to `1 + 2 * MAX_ROUNDS` | Always 3 |";
  const text = read(patterns);
  if (!text.includes(oldRow)) throw new Error("the row this lesson edits was not found; the handout changed");
  writeFileSync(patterns, text.replace(oldRow, "| LLM calls | 2 at least, up to `1 + 2 * MAX_ROUNDS` | 3 (2 if you skip the final revision) |"), "utf8");
  show(await kb.sync(docs(), day(10)));
  await kb.commit();
  const question = "How many LLM calls does reflection make?";
  console.log("   today:          ", await find(kb.retriever(), question, "LLM calls"));
  console.log("   as of day 5:    ", await find(kb.retriever({ asOf: day(5) }), question, "LLM calls"));
  console.log("   (the old version is kept with a validity period: queries default to the current one)");

  console.log("\n4. A new document appears (day 20), later it is deleted (day 30)");
  const note = join(SOURCE, "06-notes.md");
  writeFileSync(note, "# Team notes\n\n## Release freeze\n\nThe team agreed on a release freeze from 15 December. During the freeze " +
    "only fixes for production incidents may be merged, and every fix needs two reviewers.\n", "utf8");
  kb = KnowledgeBase.open(KB_DIR);
  show(await kb.sync(docs(), day(20)));
  await kb.commit();
  const freeze = "When is the release freeze?";
  console.log("   'When is the release freeze?' ->", await find(kb.retriever(), freeze, "release freeze"));
  unlinkSync(note);
  show(await kb.sync(docs(), day(30)));
  await kb.commit();
  console.log("   after the delete:             ->", await find(kb.retriever(), freeze, "release freeze"));
  console.log("   as of day 25 (still kept):    ->", await find(kb.retriever({ asOf: day(25) }), freeze, "release freeze"));

  console.log("\n5. A deleted document must be gone for good (compliance): purge the history");
  const before = kb.records.length;
  const purged = kb.purgeHistory();
  console.log(`   chunks before: ${before}, purged old versions: ${purged}, chunks after: ${kb.records.length}`);
  await kb.commit();
  console.log("   as of day 25 now:             ->", await find(kb.retriever({ asOf: day(25) }), freeze, "release freeze"));

  console.log("\n6. A safe release: build the next generation, validate it on the golden questions, only then make it live");
  const golden = loadGolden();
  kb = KnowledgeBase.open(KB_DIR);
  const baseline = await recallAtK(kb.retriever(), golden, 5);
  console.log(`   live generation ${kb.generation}: recall@5 = ${baseline.toFixed(2)}`);
  const passes = async (candidate) => {
    const recall = await recallAtK(candidate.retriever(), golden, 5);
    console.log(`   validation of generation ${candidate.generation}: recall@5 = ${recall.toFixed(2)} (must be at least ${baseline.toFixed(2)})`);
    return recall >= baseline;
  };

  const goodText = read(patterns);
  writeFileSync(patterns, goodText.replace(/### Reflection vs\. evaluator-optimizer[\s\S]*?(?=## 9\. Choosing a pattern)/, ""), "utf8");
  console.log("   (a bad edit: a whole section was deleted by mistake)");
  show(await kb.sync(docs(), day(40)));
  let released = await kb.commit(passes);
  console.log("   ->", released ? "released" : "REJECTED: the live generation does not change");
  kb = KnowledgeBase.open(KB_DIR);
  console.log(`   live generation is still ${kb.generation}; the section is still found:`,
    await find(kb.retriever(), "difference between reflection and evaluator-optimizer", "Reflection vs. evaluator-optimizer"));

  writeFileSync(patterns, goodText, "utf8");
  const page = join(SOURCE, "04-multi-agent.md");
  writeFileSync(page, read(page).replace("Keep depth to 2 levels;", "Keep depth to 2 levels (3 at most);"), "utf8");
  console.log("   (the bad edit is reverted; now a harmless edit in 04-multi-agent.md)");
  show(await kb.sync(docs(), day(41)));
  released = await kb.commit(passes);
  console.log("   ->", released ? `released as generation ${kb.generation}` : "REJECTED");

  console.log("\n7. Rollback is one pointer switch (the files of older generations are kept)");
  console.log(`   generation files: ${JSON.stringify(readdirSync(KB_DIR).filter((f) => /^kb-\d+\.json$/.test(f)).sort()).replace(/"/g, "'").replace(/,/g, ", ")}`);
  kb.rollback();
  console.log(`   after rollback the live generation is ${kb.generation}`);

  console.log("\n8. Changing the embedding model: the knowledge base refuses to mix vectors");
  kb = KnowledgeBase.open(KB_DIR);
  kb.model = "some-other-embedding-model"; // pretend it had been built with another model
  try {
    await kb.sync(docs(), day(50));
  } catch (error) {
    if (!(error instanceof ModelMismatch)) throw error;
    console.log("   refused:", error.message);
  }
  const chars = kb.records.filter((r) => r.valid_to === null).reduce((s, r) => s + r.text.length, 0);
  console.log(`   a rebuild would embed all ${kb.currentChunks()} chunks again (about ${Math.floor(chars / 4).toLocaleString("en-US")} tokens): plan it like a release`);
}
