from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import os, requests, psycopg

app = FastAPI()

# ——— Config
DATABASE_URL = os.getenv("DATABASE_URL")
QDRANT_URL = os.getenv("QDRANT_URL", "http://qdrant:6333")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "mistral:7b-instruct")

# ——— Health
@app.get("/health")
def health():
    ok = {"api":"ok"}
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
    return {"message":"Dantive Regulatory Bot API — bring your own ingestion."}

# ——— /ask schema
class AskRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str | None = Field(None, description="Ollama model name, e.g. 'mistral:7b-instruct' or 'llama3:8b-instruct'")
    # optional generation knobs
    temperature: float | None = Field(0.2, ge=0.0, le=2.0)
    top_p: float | None = Field(0.9, ge=0.0, le=1.0)
    max_tokens: int | None = Field(None, ge=1, description="limit tokens in the reply")

class AskResponse(BaseModel):
    model: str
    output: str

def call_ollama(prompt: str, model: str, temperature: float | None, top_p: float | None, max_tokens: int | None) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature if temperature is not None else 0.2,
            "top_p": top_p if top_p is not None else 0.9,
        }
    }
    if max_tokens:
        payload["options"]["num_predict"] = max_tokens

    r = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120)
    if not r.ok:
        raise HTTPException(status_code=502, detail=f"Ollama error {r.status_code}: {r.text}")
    data = r.json()
    # /api/generate returns {response: "...", done: true, ...}
    return data.get("response", "")

@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    model = req.model or DEFAULT_MODEL
    if not model:
        raise HTTPException(status_code=400, detail="No model specified and no OLLAMA_DEFAULT_MODEL set.")

    # Simple guard: ensure Ollama knows about this model (pull first if needed)
    # We intentionally avoid auto-pulling here; better to pull explicitly for clearer ops.

    out = call_ollama(
        prompt=req.prompt,
        model=model,
        temperature=req.temperature,
        top_p=req.top_p,
        max_tokens=req.max_tokens
    )
    return AskResponse(model=model, output=out)