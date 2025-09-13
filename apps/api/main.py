# apps/api/main.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import os
import json
import requests
import psycopg

app = FastAPI()

# ——— Config
DATABASE_URL = os.getenv("DATABASE_URL")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "mistral:7b-instruct")

# Timeouts (seconds)
# - CONNECT timeout: time to establish TCP connection
# - READ timeout: total time waiting for server to send data
OLLAMA_CONNECT_TIMEOUT = int(os.getenv("OLLAMA_CONNECT_TIMEOUT", "10"))
OLLAMA_READ_TIMEOUT = int(os.getenv("OLLAMA_READ_TIMEOUT", "600"))

# ——— Health
@app.get("/health")
def health():
    ok: Dict[str, Any] = {"api": "ok"}
    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                ok["db"] = "ok"
    except Exception as e:
        ok["db"] = f"err:{e}"

    try:
        r = requests.get(f"{QDRANT_URL}/readyz", timeout=1.5)
        ok["qdrant"] = "ok" if r.ok else f"err:{r.status_code}"
    except Exception as e:
        ok["qdrant"] = f"err:{e}"

    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=1.5)
        ok["ollama"] = "ok" if r.ok else f"err:{r.status_code}"
    except Exception as e:
        ok["ollama"] = f"err:{e}"

    return ok

@app.get("/")
def root():
    return {"message": "Dantive Regulatory Bot API — bring your own ingestion."}

# ——— /ask schema
class AskRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: Optional[str] = Field(None, description="Ollama model name, e.g. 'mistral:7b-instruct' or 'llama3:8b-instruct'")
    # optional generation knobs
    temperature: Optional[float] = Field(0.2, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(0.9, ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(None, ge=1, description="limit tokens in the reply")

class AskResponse(BaseModel):
    model: str
    output: str

def _build_payload(prompt: str, model: str, temperature: Optional[float], top_p: Optional[float], max_tokens: Optional[int], stream: bool) -> dict:
    payload: Dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "options": {
            "temperature": temperature if temperature is not None else 0.2,
            "top_p": top_p if top_p is not None else 0.9,
        },
    }
    if max_tokens:
        payload["options"]["num_predict"] = max_tokens
    return payload

def call_ollama(prompt: str, model: str, temperature: Optional[float], top_p: Optional[float], max_tokens: Optional[int]) -> str:
    payload = _build_payload(prompt, model, temperature, top_p, max_tokens, stream=False)
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json=payload,
            timeout=(OLLAMA_CONNECT_TIMEOUT, OLLAMA_READ_TIMEOUT),
        )
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        # surface a clean 502 with the underlying message
        raise HTTPException(status_code=502, detail=f"Ollama request failed: {e}")
    data = r.json()
    # /api/generate returns {response: "...", done: true, ...}
    return data.get("response", "")

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    model = req.model or DEFAULT_MODEL
    if not model:
        raise HTTPException(status_code=400, detail="No model specified and no OLLAMA_DEFAULT_MODEL set.")
    out = call_ollama(
        prompt=req.prompt,
        model=model,
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens,
    )
    return AskResponse(model=model, output=out)

# ——— Streaming variant (ChatGPT-like typing effect)
@app.post("/ask_stream")
def ask_stream(req: AskRequest):
    """
    Streams plain text tokens as they arrive from Ollama.
    """
    model = req.model or DEFAULT_MODEL
    if not model:
        raise HTTPException(status_code=400, detail="No model specified and no OLLAMA_DEFAULT_MODEL set.")

    payload = _build_payload(req.prompt, model, req.temperature, req.top_p, req.max_tokens, stream=True)

    def gen():
        try:
            with requests.post(
                f"{OLLAMA_URL}/api/generate",
                json=payload,
                stream=True,
                timeout=(OLLAMA_CONNECT_TIMEOUT, OLLAMA_READ_TIMEOUT),
            ) as r:
                r.raise_for_status()
                # Ollama streams JSONL lines like: {"response":"…","done":false} ... {"done":true}
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
                        # pass-through any non-JSON line defensively
                        yield line
        except requests.exceptions.RequestException as e:
            # Stream an error message so the client shows something
            yield f"\n[stream error: {e}]"

    # stream as text/plain so clients can accumulate/display incrementally
    return StreamingResponse(gen(), media_type="text/plain")