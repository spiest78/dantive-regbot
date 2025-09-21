# apps/api/main.py
from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List, Generator
import os
import json
import requests
import psycopg
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels  # For Filter, etc.

app = FastAPI(title="Dantive Regulatory Bot API", version="0.3.3")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

# ——— Config
DATABASE_URL = os.getenv("DATABASE_URL")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "mistral:7b-instruct")
COLLECTION = os.getenv("QDRANT_COLLECTION") or "regdocs_v1"
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# Strict RAG policy (Dantive: compliance + transparency)
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.82"))
RAG_MIN_DOCS_REQUIRED = int(os.getenv("RAG_MIN_DOCS_REQUIRED", "1"))
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
RAG_TEMPERATURE = float(os.getenv("RAG_TEMPERATURE", "0.1"))
RAG_MAX_CHARS = int(os.getenv("RAG_MAX_CHARS", "900"))

# Raw endpoints gate (default OFF)
ALLOW_RAW = os.getenv("ALLOW_RAW", "false").lower() == "true"

# Timeouts (seconds)
OLLAMA_CONNECT_TIMEOUT = int(os.getenv("OLLAMA_CONNECT_TIMEOUT", "10"))
OLLAMA_READ_TIMEOUT = int(os.getenv("OLLAMA_READ_TIMEOUT", "600"))

# Clients
qdrant = QdrantClient(url=QDRANT_URL, prefer_grpc=False)


# ——— Health
@app.get("/health")
def health():
    ok: Dict[str, Any] = {"api": "ok"}

    # DB
    try:
        if DATABASE_URL:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
            ok["db"] = "ok"
        else:
            ok["db"] = "skipped"
    except Exception as e:
        ok["db"] = f"err:{e}"

    # Qdrant
    try:
        r = requests.get(f"{QDRANT_URL}/readyz", timeout=1.5)
        ok["qdrant"] = "ok" if r.ok else f"err:{r.status_code}"
    except Exception as e:
        ok["qdrant"] = f"err:{e}"

    # Ollama
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=1.5)
        ok["ollama"] = "ok" if r.ok else f"err:{r.status_code}"
    except Exception as e:
        ok["ollama"] = f"err:{e}"

    ok["collection"] = COLLECTION
    ok["embed_model"] = EMBED_MODEL
    ok["rag"] = {
        "min_score": RAG_MIN_SCORE,
        "min_docs": RAG_MIN_DOCS_REQUIRED,
        "top_k": RAG_TOP_K,
        "temperature": RAG_TEMPERATURE,
    }
    ok["allow_raw"] = ALLOW_RAW
    return ok


@app.get("/")
def root():
    return {"message": "Dantive Regulatory Bot API — strict RAG (no hallucinations) with citations."}


# ——— Shared request model
class AskBase(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: Optional[str] = Field(None, description="Ollama model, e.g. 'mistral:7b-instruct'")
    # optional generation knobs (used by raw/stream)
    temperature: Optional[float] = Field(None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(None, ge=1)


# ——— RAW (optional, gated)
class AskResponseRaw(BaseModel):
    model: str
    output: str


def _build_payload(
    prompt: str,
    model: str,
    temperature: Optional[float],
    top_p: Optional[float],
    max_tokens: Optional[int],
    stream: bool,
) -> dict:
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": stream,  # IMPORTANT: explicit to avoid NDJSON surprises
        "options": {
            "temperature": RAG_TEMPERATURE if temperature is None else temperature,
            "top_p": 0.9 if top_p is None else top_p,
        },
    }
    if max_tokens:
        payload["options"]["num_predict"] = max_tokens
    return payload


def _ollama_nonstream(payload: dict) -> str:
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=(OLLAMA_CONNECT_TIMEOUT, OLLAMA_READ_TIMEOUT),
        )
        r.raise_for_status()
        # must be a single JSON object
        data = r.json()
        return (data.get("response") or "").strip()
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {e}")
    except json.JSONDecodeError as e:
        # This happens if Ollama streamed (NDJSON) unexpectedly
        raise HTTPException(status_code=502, detail=f"Ollama returned non-JSON (stream?) for non-stream request: {e}")


if ALLOW_RAW:
    @app.post("/ask_raw", response_model=AskResponseRaw)
    def ask_raw(req: AskBase):
        model = req.model or DEFAULT_MODEL
        payload = _build_payload(req.prompt, model, req.temperature, req.top_p, req.max_tokens, stream=False)
        out = _ollama_nonstream(payload)
        return AskResponseRaw(model=model, output=out)

    @app.post("/ask_stream")
    def ask_stream(req: AskBase):
        model = req.model or DEFAULT_MODEL
        payload = _build_payload(req.prompt, model, req.temperature, req.top_p, req.max_tokens, stream=True)

        def gen() -> Generator[str, None, None]:
            try:
                with requests.post(
                    f"{OLLAMA_URL}/api/generate",
                    json=payload,
                    stream=True,
                    timeout=(OLLAMA_CONNECT_TIMEOUT, OLLAMA_READ_TIMEOUT),
                ) as r:
                    r.raise_for_status()
                    for line in r.iter_lines(decode_unicode=True):
                        if not line:
                            continue
                        try:
                            j = json.loads(line)
                            if "response" in j and j["response"]:
                                yield j["response"]
                            if j.get("done"):
                                break
                        except json.JSONDecodeError:
                            # Pass through raw line if it isn't JSON (rare)
                            yield line
            except requests.exceptions.RequestException as e:
                yield f"\n[stream error: {e}]"

        return StreamingResponse(gen(), media_type="text/plain")


# ——— STRICT RAG
class Citation(BaseModel):
    ref_num: int
    source_name: Optional[str]
    source_path: Optional[str]
    chunk_index: Optional[int]
    score: float
    excerpt: Optional[str] = None


class AskResponseRAG(BaseModel):
    model: str
    answer: str
    citations: List[Citation]
    retrieval: dict
    policy: dict


def embed_query(q: str) -> List[float]:
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": q},
            timeout=(OLLAMA_CONNECT_TIMEOUT, OLLAMA_READ_TIMEOUT),
        )
        r.raise_for_status()
        j = r.json()
        return j["embedding"]
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Embedding request failed: {e}")
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=502, detail=f"Embedding response malformed: {e}")


def retrieve(vec: List[float]) -> List[dict]:
    try:
        hits = qdrant.search(collection_name=COLLECTION, query_vector=vec, limit=RAG_TOP_K)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Vector search failed: {e}")

    results = []
    for h in hits:
        p = h.payload or {}
        txt = p.get("text")
        if txt:
            txt = txt[:RAG_MAX_CHARS]
        results.append(
            {
                "score": float(h.score),
                "source_name": p.get("source_name"),
                "source_path": p.get("source_path"),
                "chunk_index": p.get("chunk_index"),
                "text": txt,
            }
        )
    return results


def eligible(results: List[dict]) -> List[dict]:
    return [r for r in results if r["score"] >= RAG_MIN_SCORE]


def build_sources_block(els: List[dict]) -> str:
    if not els:
        return "(none)"
    lines = []
    for i, r in enumerate(els, start=1):
        if r.get("text"):
            lines.append(f"[{i}] {r['text']}")
        else:
            lines.append(f"[{i}] (from {r.get('source_name')} chunk #{r.get('chunk_index')})")
    return "\n".join(lines)


def system_prompt(user_q: str, sources_block: str) -> str:
    return f"""You are Dantive RegBot. Compliance & transparency first.

Rules:
- Answer ONLY using the SOURCES below.
- If the SOURCES do not contain sufficient information, reply exactly: "I don't know based on the provided sources."
- Always include footnote-style citations [^n] matching the numbered SOURCES you used.
- Be concise and factual. No speculation.

User question:
{user_q}

SOURCES (numbered):
{sources_block}

Respond in this format:
Answer: <your answer>
Citations: [^n], [^m] ...
"""


def call_ollama_strict(prompt: str, model: str) -> str:
    # IMPORTANT: force non-stream to get a single JSON object
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": RAG_TEMPERATURE},
    }
    return _ollama_nonstream(payload)


@app.post("/ask", response_model=AskResponseRAG)
def ask_rag(req: AskBase):
    """Strict RAG endpoint: refuses to answer if retrieval is weak; always returns citations."""
    model = req.model or DEFAULT_MODEL
    question = req.prompt.strip()

    # 1) Embed & retrieve
    vec = embed_query(question)
    results = retrieve(vec)
    els = eligible(results)[:RAG_TOP_K]

    # 2) Guardrail: no strong matches => refuse to answer
    if len(els) < RAG_MIN_DOCS_REQUIRED:
        return AskResponseRAG(
            model=model,
            answer='I don\'t know based on the provided sources.',
            citations=[],
            retrieval={"top_k": RAG_TOP_K, "min_score": RAG_MIN_SCORE, "used": 0, "total_found": len(results)},
            policy={"answered": False, "reason": "no_relevant_documents_above_threshold"},
        )

    # 3) Build prompt with numbered sources
    sources_block = build_sources_block(els)
    prompt = system_prompt(question, sources_block)

    # 4) Generate
    answer = call_ollama_strict(prompt, model=model)

    # 5) Structure citations aligned with [^n]
    cits: List[Citation] = []
    for i, r in enumerate(els, start=1):
        cits.append(
            Citation(
                ref_num=i,
                source_name=r.get("source_name"),
                source_path=r.get("source_path"),
                chunk_index=r.get("chunk_index"),
                score=r["score"],
                excerpt=r.get("text"),
            )
        )

    return AskResponseRAG(
        model=model,
        answer=answer,
        citations=cits,
        retrieval={"top_k": RAG_TOP_K, "min_score": RAG_MIN_SCORE, "used": len(els), "total_found": len(results)},
        policy={"answered": True, "reason": "sufficient_retrieval"},
    )


# ——— Streaming RAG (guardrails + streaming)
@app.post("/ask_stream_rag")
def ask_stream_rag(req: AskBase):
    """
    Streams text with strict RAG guardrail.
    If retrieval is weak, immediately yields the no-answer line and stops.
    """
    model = req.model or DEFAULT_MODEL
    question = req.prompt.strip()

    # Retrieval first (non-streaming paths)
    vec = embed_query(question)
    results = retrieve(vec)
    els = eligible(results)[:RAG_TOP_K]

    if len(els) < RAG_MIN_DOCS_REQUIRED:
        return StreamingResponse(iter(["I don't know based on the provided sources."]), media_type="text/plain")

    sources_block = build_sources_block(els)
    prompt = system_prompt(question, sources_block)

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": True,  # explicit streaming for NDJSON
        "options": {"temperature": RAG_TEMPERATURE},
    }

    def gen() -> Generator[str, None, None]:
        try:
            with requests.post(
                f"{OLLAMA_URL}/api/generate",
                json=payload,
                stream=True,
                timeout=(OLLAMA_CONNECT_TIMEOUT, OLLAMA_READ_TIMEOUT),
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    try:
                        j = json.loads(line)
                        if "response" in j and j["response"]:
                            yield j["response"]
                        if j.get("done"):
                            break
                    except json.JSONDecodeError:
                        # Pass-through any occasional non-JSON line
                        yield line
        except requests.exceptions.RequestException as e:
            yield f"\n[stream error: {e}]"

    return StreamingResponse(gen(), media_type="text/plain")


# ——— Qdrant debug helpers
@app.post("/qdrant_scroll")
def qdrant_scroll(body: dict = Body(...)):
    """
    Inspect Qdrant: returns a small sample of payloads.
    Body accepts: limit, with_payload, with_vectors, filter (dict), offset (dict).
    """
    try:
        # Coerce/guard inputs
        limit = int(body.get("limit", 5))
        if limit <= 0:
            limit = 5
        with_payload = bool(body.get("with_payload", True))
        with_vectors = bool(body.get("with_vectors", False))

        # Filter: accept dict and try to parse into qmodels.Filter; otherwise ignore
        filt = body.get("filter")
        if isinstance(filt, dict):
            try:
                filt = qmodels.Filter(**filt)
            except Exception:
                filt = None
        else:
            filt = None

        # Offset can be a dict or None; pass through as-is if dict
        offset = body.get("offset")
        if not isinstance(offset, dict):
            offset = None

        points, next_off = qdrant.scroll(
            collection_name=COLLECTION,
            limit=limit,
            with_payload=with_payload,
            with_vectors=with_vectors,
            scroll_filter=filt,
            offset=offset,
        )

        # next_off is already serializable (dict) in modern clients; guard anyway
        next_offset = next_off if isinstance(next_off, dict) or next_off is None else None

        return {
            "points": [p.payload for p in points],
            "next_offset": next_offset,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"qdrant_scroll failed: {e}")


@app.post("/qdrant_counts_by_source")
def qdrant_counts_by_source():
    """
    Returns [{source_name, count}] for up to the whole collection (batched scroll).
    """
    import collections

    agg = collections.Counter()
    next_off = None
    while True:
        points, next_off = qdrant.scroll(
            collection_name=COLLECTION,
            limit=1000,
            offset=next_off,
            with_payload=True,
            with_vectors=False,
        )
        for p in points:
            sn = (p.payload or {}).get("source_name", "<unknown>")
            agg[sn] += 1
        if not next_off:
            break
    return [{"source_name": k, "count": v} for k, v in agg.most_common(100)]