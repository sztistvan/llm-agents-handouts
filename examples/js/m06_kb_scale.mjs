// Module 6 lesson: what happens when the knowledge base grows. Exact search vs approximate search.
//
// Brute force compares the query with EVERY vector: exact, but the time grows with the size of the corpus.
// Approximate search looks at only a part of the vectors and is much faster, but it can miss a true neighbour.
// This lesson measures that trade-off on SYNTHETIC vectors (random clusters, no model needed) with a simple IVF
// index: k-means groups the vectors into lists, and a query scans only the `nprobe` closest lists.
// Real systems use optimized libraries (FAISS, HNSW in a vector database); the trade-off is the same.
// Your own embeddings will give different numbers: measure recall on YOUR data. Run:
//     node examples/js/m06_kb_scale.mjs
import { pathToFileURL } from "node:url";

const DIM = 64, CLUSTERS = 40, SIGMA = 0.08, QUERIES = 20, K = 10;
const SIZES = [2_000, 10_000];
const NPROBES = [1, 2, 4, 8];

/** A small seeded random generator (the same in the Python version, so both build the same data). */
function mulberry32(seed) {
  let a = seed | 0;
  return () => {
    a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const gauss = (rand) => Math.sqrt(-2 * Math.log(Math.max(rand(), 1e-12))) * Math.cos(2 * Math.PI * rand());
const normalize = (v) => { const norm = Math.sqrt(v.reduce((s, x) => s + x * x, 0)) || 1; return v.map((x) => x / norm); };
const dot = (a, b) => { let s = 0; for (let i = 0; i < a.length; i++) s += a[i] * b[i]; return s; };
const sample = (rand, centers) => {
  const center = centers[Math.floor(rand() * centers.length)];
  return normalize(center.map((c) => c + SIGMA * gauss(rand)));
};

/** The k indexes with the highest score; ties keep the lower index first. */
const topK = (indexes, score, k) => indexes.map((i) => [score(i), i]).sort((a, b) => b[0] - a[0] || a[1] - b[1]).slice(0, k).map(([, i]) => i);
const range = (n) => Array.from({ length: n }, (_, i) => i);

const exactSearch = (vectors, query, k) => topK(range(vectors.length), (i) => dot(vectors[i], query), k);

const nearest = (centroids, v) => {
  let best = 0, bestScore = -Infinity;
  centroids.forEach((c, j) => { const s = dot(c, v); if (s > bestScore) { bestScore = s; best = j; } });
  return best;
};

/** k-means on a sample gives the list centers; then every vector goes to its nearest list. */
function buildIvf(vectors, rand, nLists, iterations = 4) {
  const pool = Array.from({ length: Math.min(vectors.length, 20 * nLists) }, () => vectors[Math.floor(rand() * vectors.length)]);
  let centroids = pool.slice(0, nLists).map((v) => [...v]);
  for (let it = 0; it < iterations; it++) {
    const sums = centroids.map(() => new Array(DIM).fill(0));
    for (const v of pool) { const j = nearest(centroids, v); for (let d = 0; d < DIM; d++) sums[j][d] += v[d]; }
    centroids = sums.map((s, j) => (s.some((x) => x !== 0) ? normalize(s) : centroids[j]));
  }
  const lists = centroids.map(() => []);
  vectors.forEach((v, i) => lists[nearest(centroids, v)].push(i));
  return [centroids, lists];
}

function ivfSearch(vectors, centroids, lists, query, k, nprobe) {
  const probes = topK(range(centroids.length), (j) => dot(centroids[j], query), nprobe);
  const candidates = probes.flatMap((j) => lists[j]);
  return [topK(candidates, (i) => dot(vectors[i], query), k), candidates.length];
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const rand = mulberry32(42);
  const centers = Array.from({ length: CLUSTERS }, () => normalize(Array.from({ length: DIM }, () => gauss(rand))));
  const queries = Array.from({ length: QUERIES }, () => sample(rand, centers));
  let nsPerOp = 0;
  for (const n of SIZES) {
    const vectors = Array.from({ length: n }, () => sample(rand, centers));
    let started = performance.now();
    const truth = queries.map((q) => new Set(exactSearch(vectors, q, K)));
    const exactMs = (performance.now() - started) / QUERIES;
    nsPerOp = (exactMs * 1e6) / (n * DIM);
    started = performance.now();
    const [centroids, lists] = buildIvf(vectors, rand, Math.round(Math.sqrt(n)));
    const buildS = (performance.now() - started) / 1000;
    console.log(`\n${n.toLocaleString("en-US")} vectors, ${DIM} dimensions, ${QUERIES} queries, recall measured against the exact top ${K}` +
      `   (IVF index: ${lists.length} lists, built in ${buildS.toFixed(1)} s)`);
    console.log(`  ${"method".padEnd(14)}${"ms/query".padStart(10)}${"scanned".padStart(10)}${("recall@" + K).padStart(11)}`);
    console.log(`  ${"exact".padEnd(14)}${exactMs.toFixed(1).padStart(10)}${"100%".padStart(10)}${(1).toFixed(2).padStart(11)}`);
    for (const nprobe of NPROBES) {
      started = performance.now();
      const results = queries.map((q) => ivfSearch(vectors, centroids, lists, q, K, nprobe));
      const ms = (performance.now() - started) / QUERIES;
      const recall = results.reduce((s, [found], qi) => s + found.filter((i) => truth[qi].has(i)).length / K, 0) / QUERIES;
      const scanned = results.reduce((s, [, count]) => s + count, 0) / QUERIES / n;
      console.log(`  ${("ivf nprobe=" + nprobe).padEnd(14)}${ms.toFixed(1).padStart(10)}${(Math.round(scanned * 100) + "%").padStart(10)}${recall.toFixed(2).padStart(11)}`);
    }
  }
  const seconds = nsPerOp * 1e-9 * 1_000_000 * 1536;
  console.log(`\nExact search cost here: about ${Math.round(nsPerOp)} ns per vector element. For 1,000,000 vectors of 1536 numbers ` +
    `(a real embedding model)\nthat is about ${Math.round(seconds).toLocaleString("en-US")} s per query in this teaching code. Optimized libraries are far faster, ` +
    "but the lesson stays: past some size you search a part of the index and pay with recall.");
}
