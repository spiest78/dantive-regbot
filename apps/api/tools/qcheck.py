import os, json, collections
from qdrant_client import QdrantClient

COL = os.getenv("QDRANT_COLLECTION", "regdocs_v1")
QURL = os.getenv("QDRANT_URL", "http://qdrant:6333")

qc = QdrantClient(url=QURL)

# Counts
approx = qc.count(COL, exact=False).count
exact  = qc.count(COL, exact=True).count
print(f"Collection: {COL}")
print(f"Count approx: {approx}")
print(f"Count exact : {exact}")

# Sample a few payloads
pts, _ = qc.scroll(collection_name=COL, limit=3, with_payload=True, with_vectors=False)
print("\nSample payloads:")
print(json.dumps([p.payload for p in pts], indent=2)[:2000])

# Top sources (first 5)
agg = collections.Counter()
off = None
while True:
    chunk, off = qc.scroll(collection_name=COL, limit=1000, offset=off, with_payload=True, with_vectors=False)
    for p in chunk:
        sn = (p.payload or {}).get("source_name", "<unknown>")
        agg[sn] += 1
    if not off:
        break

print("\nTop sources (by chunks):")
for name, cnt in agg.most_common(5):
    print(f"{cnt:6d}  {name}")