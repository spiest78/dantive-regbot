import os
import time
import hashlib
import re
from typing import List

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
        def __iter__(self):
            if self.iterable is None:
                return iter([])
            return iter(self.iterable)

# ---------- Config ----------
DATA_DIR = os.getenv("DATA_DIR", "./data")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")   # if running inside Docker network
# If running on your host, you may need "http://localhost:6333"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")  # or "http://localhost:11434"
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")   # 768-d
COLLECTION = os.getenv("QDRANT_COLLECTION", "regdocs_v1")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "1200"))            # ~ characters
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "200"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "64"))
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
        texts = []
        for page in reader.pages:
            t = page.extract_text() or ""
            texts.append(t)
        return "\n".join(texts)
    raise RuntimeError(f"Unsupported file type: {path}")

def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def chunk_text(text: str, size: int, overlap: int) -> List[str]:
    text = normalize_ws(text)
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap
        if start < 0:
            start = 0
        if start >= n:
            break
    return chunks

def file_sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()

def ensure_collection(client: QdrantClient, collection: str, vector_size: int = 768, distance="Cosine"):
    try:
        client.get_collection(collection_name=collection)
        return
    except Exception:
        pass
    client.recreate_collection(
        collection_name=collection,
        vectors_config=qmodels.VectorParams(size=vector_size, distance=distance),
    )

def guess_vector_size_for_model(name: str) -> int:
    # Known defaults for common Ollama embed models
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

def embed_text(t: str, model: str, base_url: str, timeout: int = 120) -> List[float]:
    r = requests.post(f"{base_url}/api/embeddings", json={"model": model, "prompt": t}, timeout=timeout)
    r.raise_for_status()
    return r.json()["embedding"]

def main():
    vec_size = guess_vector_size_for_model(EMBED_MODEL)
    client = QdrantClient(url=QDRANT_URL, prefer_grpc=False)
    ensure_collection(client, COLLECTION, vector_size=vec_size, distance="Cosine")

    files = scan_files(DATA_DIR)
    if not files:
        print(f"No files found in {DATA_DIR}. Add PDFs or TXTs and re-run.")
        return

    print(f"Found {len(files)} files under {DATA_DIR}. Embedding with {EMBED_MODEL} via {OLLAMA_URL}")

    # -------- First pass: read & chunk so we know total work --------
    file_chunks = []
    total_chunks = 0
    read_start = time.time()
    for path in files:
        print(f"[READ] {path}")  # 👈 add this line
        try:
            text = read_text_from_file(path)
        except Exception as e:
            print(f"[SKIP] {path}: {e}")
            continue
        chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
        if not chunks:
            print(f"[SKIP] {path}: no text extracted")
            continue
        file_chunks.append((path, chunks))
        total_chunks += len(chunks)
    read_start = time.time()
    for path in files:
        try:
            text = read_text_from_file(path)
        except Exception as e:
            print(f"[SKIP] {path}: {e}")
            continue
        chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
        if not chunks:
            print(f"[SKIP] {path}: no text extracted")
            continue
        file_chunks.append((path, chunks))
        total_chunks += len(chunks)
    read_elapsed = time.time() - read_start

    if total_chunks == 0:
        print("No chunks to embed. Exiting.")
        return

    print(f"Prepared {total_chunks} chunks from {len(file_chunks)} files in {format_duration(read_elapsed)}.")

    # -------- Second pass: embed + upsert with global progress/ETA --------
    global_start = time.time()
    processed = 0
    total_points = 0
    pbar = tqdm(total=total_chunks, desc=f"Embedding all chunks ({EMBED_MODEL})", unit="chunk")

    for path, chunks in file_chunks:
        file_start = time.time()
        vectors = []
        # per-file progress (lightweight; avoid nested bars)
        for chunk in chunks:
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

        # Build points & upsert
        sha1 = file_sha1(path)
        now = int(time.time())
        points = []
        for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
            pid = int(hashlib.md5(f"{sha1}:{idx}".encode()).hexdigest()[:16], 16) % (2**63 - 1)
            payload = {
                "source_path": os.path.abspath(path),
                "source_name": os.path.basename(path),
                "file_sha1": sha1,
                "chunk_index": idx,
                "created_at": now,
                # Extend with regulatory metadata if you want
                # "regulation": "REACH",
                # "article": "57",
                # "language": "en",
            }
            points.append(qmodels.PointStruct(id=pid, vector=vec, payload=payload))

        upsert_batches(client, COLLECTION, points, BATCH_SIZE)
        total_points += len(points)

        rate_file = len(chunks) / file_elapsed if file_elapsed > 0 else 0.0
        print(f"[OK] {path}: {len(points)} chunks upserted in {format_duration(file_elapsed)} ({rate_file:.1f} ch/s)")

    pbar.close()
    total_elapsed = time.time() - global_start

    info = client.get_collection(COLLECTION)
    approx_count = client.count(COLLECTION, exact=False).count

    print("\nDone.")
    print(f"Collection: {COLLECTION}")
    print(f"Status: {info.status}, vectors count (approx): {approx_count}")
    print(f"Total upserted this run: {total_points}")
    rate_global = total_chunks / total_elapsed if total_elapsed > 0 else 0.0
    print(f"Total embedding time: {format_duration(total_elapsed)} ({rate_global:.1f} chunks/sec)")
    remaining = total_chunks - processed
    if remaining > 0:
        print(f"⚠️  Warning: {remaining} chunks unprocessed.")

if __name__ == "__main__":
    main()