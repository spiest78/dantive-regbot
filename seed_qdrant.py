import os
import time
import hashlib
import re
from typing import List, Set, Optional

import requests
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

# Progress bar (tqdm); degrade gracefully if not installed
try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    class tqdm:  # minimal shim
        def __init__(self, iterable=None, total=None, desc=None, unit=None):
            self.iterable = iterable
        def update(self, n=1): pass
        def close(self): pass
        def set_description(self, *_args, **_kwargs): pass
        def __iter__(self):
            if self.iterable is None:
                return iter([])
            return iter(self.iterable)

# ---------- Config ----------
DATA_DIR = os.getenv("DATA_DIR", "./data")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")   # if running inside Docker network
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")  # or "http://localhost:11434"
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")   # 768-d
COLLECTION = os.getenv("QDRANT_COLLECTION", "regdocs_v1")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))            # ~ characters
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "64"))
# Optional: cap pages for problematic PDFs (0 = no cap)
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "0"))
# Resume: skip already-present chunks (by file_sha1 + chunk_index)
RESUME = os.getenv("RESUME", "true").lower() == "true"
# Simple retries for Ollama embeddings
EMBED_MAX_RETRIES = int(os.getenv("EMBED_MAX_RETRIES", "3"))
EMBED_RETRY_BACKOFF = float(os.getenv("EMBED_RETRY_BACKOFF", "1.5"))
# ----------------------------

# --- Helpers ---

def read_text_from_file(path: str) -> str:
    lower = path.lower()
    if lower.endswith(".txt"):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    if lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError("pypdf is required for PDFs. Install with: pip install pypdf") from e

        reader = PdfReader(path)
        total_pages = len(reader.pages)
        n_pages = total_pages
        if MAX_PDF_PAGES and total_pages > MAX_PDF_PAGES:
            n_pages = MAX_PDF_PAGES  # soft cap if you set it via env

        texts = []
        bar = tqdm(range(n_pages), desc=f"PDF read: {os.path.basename(path)}", unit="page")
        for i in bar:
            try:
                page = reader.pages[i]
                t = page.extract_text() or ""
            except Exception:
                t = ""  # skip unreadable page but keep going
            texts.append(t)
        return "\n".join(texts)

    raise RuntimeError(f"Unsupported file type: {path}")

def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def chunk_text(text: str, size: int, overlap: int) -> List[str]:
    if size <= 0:
        raise ValueError("CHUNK_SIZE must be > 0")
    if overlap < 0:
        raise ValueError("CHUNK_OVERLAP must be >= 0")
    if overlap >= size:
        # Overlap must be strictly smaller than size to make forward progress
        raise ValueError("CHUNK_OVERLAP must be < CHUNK_SIZE")

    text = normalize_ws(text)
    chunks = []
    n = len(text)
    start = 0

    while start < n:
        end = min(start + size, n)
        chunks.append(text[start:end])
        if end == n:          # ✅ we're at the end; stop
            break
        start = max(end - overlap, 0)  # always move forward

    return chunks

def file_sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()

def ensure_collection(client: QdrantClient, collection: str, vector_size: int = 768, distance="Cosine"):
    # Try to get; if missing, create (avoid deprecated recreate_collection)
    try:
        client.get_collection(collection_name=collection)
        return
    except Exception:
        pass
    client.create_collection(
        collection_name=collection,
        vectors_config=qmodels.VectorParams(size=vector_size, distance=distance),
    )

def guess_vector_size_for_model(name: str) -> int:
    table = {
        "nomic-embed-text": 768,
        "mxbai-embed-large": 1024,
        "snowflake-arctic-embed": 1024,
        "bge-small-en": 384,
        "bge-base-en": 768,
    }
    return table.get(name, 768)

def scan_files(folder: str) -> List[str]:
    paths = []
    for root, _, files in os.walk(folder):
        for f in files:
            if f.lower().endswith((".pdf", ".txt")):
                paths.append(os.path.join(root, f))
    return sorted(paths)

def upsert_batches(
    client: QdrantClient,
    collection: str,
    points: List[qmodels.PointStruct],
    batch_size: int = 64
):
    for i in range(0, len(points), batch_size):
        batch = points[i:i+batch_size]
        client.upsert(collection_name=collection, points=batch)

def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

def embed_text_once(t: str, model: str, base_url: str, timeout: int = 120) -> List[float]:
    r = requests.post(f"{base_url}/api/embeddings", json={"model": model, "prompt": t}, timeout=timeout)
    r.raise_for_status()
    return r.json()["embedding"]

def embed_text(t: str, model: str, base_url: str, timeout: int = 120) -> List[float]:
    # simple retry/backoff for transient Ollama errors
    delay = 0.0
    last_err: Optional[Exception] = None
    for attempt in range(1, EMBED_MAX_RETRIES + 1):
        try:
            if delay > 0:
                time.sleep(delay)
            return embed_text_once(t, model, base_url, timeout)
        except Exception as e:
            last_err = e
            delay = delay * EMBED_RETRY_BACKOFF + 0.25 if delay > 0 else 0.5
    # if we reach here, all retries failed
    raise RuntimeError(f"Embedding failed after {EMBED_MAX_RETRIES} attempts: {last_err}")

# --- NEW: resume support -------------------------------------------------------

def existing_chunk_indexes(client: QdrantClient, collection: str, file_sha1: str) -> Set[int]:
    """
    Return the set of chunk_index values already present in Qdrant for a given file_sha1.
    Uses scroll with a filter; IMPORTANT: use 'scroll_filter' kwarg for this client.
    """
    found: Set[int] = set()
    offset = None
    flt = qmodels.Filter(
        must=[qmodels.FieldCondition(key="file_sha1", match=qmodels.MatchValue(value=file_sha1))]
    )
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=1000,
            with_payload=True,
            with_vectors=False,
            scroll_filter=flt,  # <- not "filter"
            offset=offset,
        )
        for p in points:
            ci = (p.payload or {}).get("chunk_index")
            if isinstance(ci, int):
                found.add(ci)
        if not offset:
            break
    return found

# ------------------------------------------------------------------------------

def main():
    vec_size = guess_vector_size_for_model(EMBED_MODEL)
    client = QdrantClient(url=QDRANT_URL, prefer_grpc=False)
    ensure_collection(client, COLLECTION, vector_size=vec_size, distance="Cosine")

    files = scan_files(DATA_DIR)
    if not files:
        print(f"No files found in {DATA_DIR}. Add PDFs or TXTs and re-run.", flush=True)
        return

    print(f"Found {len(files)} files under {DATA_DIR}. Embedding with {EMBED_MODEL} via {OLLAMA_URL}", flush=True)

    # -------- First pass: read & chunk so we know total work --------
    file_chunks = []  # list[(path, [chunks])]
    total_chunks = 0
    read_start = time.time()

    for path in files:
        print(f"[READ] {path}", flush=True)
        try:
            text = read_text_from_file(path)
        except Exception as e:
            print(f"[SKIP] {path}: {e}", flush=True)
            continue

        chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
        if not chunks:
            print(f"[SKIP] {path}: no text extracted", flush=True)
            continue

        file_chunks.append((path, chunks))
        total_chunks += len(chunks)

    read_elapsed = time.time() - read_start

    if total_chunks == 0:
        print("No chunks to embed. Exiting.", flush=True)
        return

    print(f"Prepared {total_chunks} chunks from {len(file_chunks)} files in {format_duration(read_elapsed)}.", flush=True)

    # -------- Second pass: embed + upsert with global progress/ETA --------
    global_start = time.time()
    processed = 0
    total_points = 0
    pbar = tqdm(total=total_chunks, desc=f"Embedding all chunks ({EMBED_MODEL})", unit="chunk")

    for path, chunks in file_chunks:
        file_start = time.time()
        sha1 = file_sha1(path)

        # Resume: figure out which chunk indexes already exist
        already: Set[int] = set()
        if RESUME:
            try:
                already = existing_chunk_indexes(client, COLLECTION, sha1)
            except Exception as e:
                print(f"[WARN] resume lookup failed for {os.path.basename(path)}: {e}", flush=True)

        # Select only missing chunks
        to_embed = [(i, c) for i, c in enumerate(chunks) if i not in already] if RESUME else list(enumerate(chunks))

        if RESUME:
            print(f"[RESUME] {os.path.basename(path)}: have {len(already)}/{len(chunks)}; embedding {len(to_embed)} missing.", flush=True)

        if not to_embed:
            # nothing to do for this file
            continue

        # Embed (only missing)
        vectors: List[List[float]] = []
        for _, chunk in to_embed:
            vec = embed_text(chunk, EMBED_MODEL, OLLAMA_URL)
            vectors.append(vec)
            processed += 1
            pbar.update(1)

            # ETA estimate (global)
            elapsed = time.time() - global_start
            if processed % 25 == 0 or processed == total_chunks:
                rate = processed / elapsed if elapsed > 0 else 0.0
                remaining = total_chunks - processed
                eta = remaining / rate if rate > 0 else 0
                pbar.set_description(
                    f"Embedding all chunks ({EMBED_MODEL}) | {rate:.1f} ch/s | ETA {format_duration(eta)}"
                )

        file_elapsed = time.time() - file_start

        # Build points & upsert (only for missing indexes)
        now = int(time.time())
        points: List[qmodels.PointStruct] = []
        for (idx, chunk), vec in zip(to_embed, vectors):
            pid = int(hashlib.md5(f"{sha1}:{idx}".encode()).hexdigest()[:16], 16) % (2**63 - 1)
            payload = {
                "source_path": os.path.abspath(path),
                "source_name": os.path.basename(path),
                "file_sha1": sha1,
                "chunk_index": idx,
                "created_at": now,
                "text": chunk[:1200],  # enable excerpts in API responses
            }
            points.append(qmodels.PointStruct(id=pid, vector=vec, payload=payload))

        if points:
            upsert_batches(client, COLLECTION, points, BATCH_SIZE)
            total_points += len(points)

        have_now = len(already) + len(points) if RESUME else len(points)
        rate_file = (len(to_embed) / file_elapsed) if file_elapsed > 0 else 0.0
        print(
            f"[OK] {os.path.basename(path)}: upserted {len(points)} missing chunks "
            f"(now have ~{have_now}/{len(chunks)}). Took {format_duration(file_elapsed)} ({rate_file:.1f} ch/s)",
            flush=True
        )

    pbar.close()
    total_elapsed = time.time() - global_start

    info = client.get_collection(COLLECTION)
    approx_count = client.count(COLLECTION, exact=False).count

    print("\nDone.", flush=True)
    print(f"Collection: {COLLECTION}", flush=True)
    print(f"Status: {info.status}, vectors count (approx): {approx_count}", flush=True)
    print(f"Total upserted this run: {total_points}", flush=True)
    rate_global = (processed / total_elapsed) if total_elapsed > 0 else 0.0
    print(f"Total embedding time: {format_duration(total_elapsed)} ({rate_global:.1f} chunks/sec)", flush=True)

if __name__ == "__main__":
    main()