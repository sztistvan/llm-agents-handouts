"""Module 6 lesson: what happens when the knowledge base grows. Exact search vs approximate search.

Brute force compares the query with EVERY vector: exact, but the time grows with the size of the corpus.
Approximate search looks at only a part of the vectors and is much faster, but it can miss a true neighbour.
This lesson measures that trade-off on SYNTHETIC vectors (random clusters, no model needed) with a simple IVF
index: k-means groups the vectors into lists, and a query scans only the `nprobe` closest lists.
Real systems use optimized libraries (FAISS, HNSW in a vector database); the trade-off is the same.
Your own embeddings will give different numbers: measure recall on YOUR data. Run:
    python examples/python/m06_kb_scale.py
"""
import heapq
import math
import time

DIM, CLUSTERS, SIGMA, QUERIES, K = 64, 40, 0.08, 20, 10
SIZES = (2_000, 10_000)
NPROBES = (1, 2, 4, 8)


def mulberry32(seed: int):
    """A small seeded random generator (the same in the JavaScript version, so both build the same data)."""
    state = seed & 0xFFFFFFFF

    def rand() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((state ^ (state >> 15)) * (1 | state)) & 0xFFFFFFFF
        t = ((t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF)) ^ t) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return rand


def gauss(rand) -> float:
    return math.sqrt(-2 * math.log(max(rand(), 1e-12))) * math.cos(2 * math.pi * rand())


def normalize(v: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def sample(rand, centers: list[list[float]]) -> list[float]:
    center = centers[int(rand() * len(centers))]
    return normalize([c + SIGMA * gauss(rand) for c in center])


def exact_search(vectors, query, k):
    return heapq.nlargest(k, range(len(vectors)), key=lambda i: dot(vectors[i], query))


def nearest(centroids, v):
    return max(range(len(centroids)), key=lambda j: dot(centroids[j], v))


def build_ivf(vectors, rand, n_lists, iterations=4):
    """k-means on a sample gives the list centers; then every vector goes to its nearest list."""
    pool = [vectors[int(rand() * len(vectors))] for _ in range(min(len(vectors), 20 * n_lists))]
    centroids = [list(v) for v in pool[:n_lists]]
    for _ in range(iterations):
        sums = [[0.0] * DIM for _ in centroids]
        for v in pool:
            j = nearest(centroids, v)
            sums[j] = [s + x for s, x in zip(sums[j], v)]
        centroids = [normalize(s) if any(s) else c for s, c in zip(sums, centroids)]
    lists = [[] for _ in centroids]
    for i, v in enumerate(vectors):
        lists[nearest(centroids, v)].append(i)
    return centroids, lists


def ivf_search(vectors, centroids, lists, query, k, nprobe):
    probes = heapq.nlargest(nprobe, range(len(centroids)), key=lambda j: dot(centroids[j], query))
    candidates = [i for j in probes for i in lists[j]]
    return heapq.nlargest(k, candidates, key=lambda i: dot(vectors[i], query)), len(candidates)


if __name__ == "__main__":
    rand = mulberry32(42)
    centers = [normalize([gauss(rand) for _ in range(DIM)]) for _ in range(CLUSTERS)]
    queries = [sample(rand, centers) for _ in range(QUERIES)]
    ns_per_op = 0.0
    for n in SIZES:
        vectors = [sample(rand, centers) for _ in range(n)]
        started = time.perf_counter()
        truth = [set(exact_search(vectors, q, K)) for q in queries]
        exact_ms = (time.perf_counter() - started) / QUERIES * 1000
        ns_per_op = exact_ms * 1e6 / (n * DIM)
        started = time.perf_counter()
        centroids, lists = build_ivf(vectors, rand, round(math.sqrt(n)))
        build_s = time.perf_counter() - started
        print(f"\n{n:,} vectors, {DIM} dimensions, {QUERIES} queries, recall measured against the exact top {K}"
              f"   (IVF index: {len(lists)} lists, built in {build_s:.1f} s)")
        print(f"  {'method':14}{'ms/query':>10}{'scanned':>10}{'recall@' + str(K):>11}")
        print(f"  {'exact':14}{exact_ms:>10.1f}{'100%':>10}{1.0:>11.2f}")
        for nprobe in NPROBES:
            started = time.perf_counter()
            results = [ivf_search(vectors, centroids, lists, q, K, nprobe) for q in queries]
            ms = (time.perf_counter() - started) / QUERIES * 1000
            recall = sum(len(set(found) & t) / K for (found, _), t in zip(results, truth)) / QUERIES
            scanned = sum(count for _, count in results) / QUERIES / n
            print(f"  {'ivf nprobe=' + str(nprobe):14}{ms:>10.1f}{scanned:>10.0%}{recall:>11.2f}")

    seconds = ns_per_op * 1e-9 * 1_000_000 * 1536
    print(f"\nExact search cost here: about {ns_per_op:.0f} ns per vector element. For 1,000,000 vectors of 1536 numbers "
          f"(a real embedding model)\nthat is about {seconds:,.0f} s per query in this teaching code. Optimized libraries are far faster, "
          "but the lesson stays: past some size you search a part of the index and pay with recall.")
