import os, secrets, hashlib, time, json, sqlite3, asyncio
from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from groq import AsyncGroq

APP_NAME = "Fama AI Gateway"
FAMA_MODEL = "fama/Fama2-12.9b"
DB_PATH = os.getenv("DB_PATH", "fama.db")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
ADMIN_KEY = os.getenv("ADMIN_KEY")
FAMA_MODE = os.getenv("FAMA_MODE", "auto")  # auto | single | ensemble
FAMA_DEFAULT_MODEL = os.getenv("FAMA_DEFAULT_MODEL", "openai/gpt-oss-120b")
FAMA_ENSEMBLE_MODELS = [
    x.strip() for x in os.getenv(
        "FAMA_ENSEMBLE_MODELS",
        "openai/gpt-oss-120b,openai/gpt-oss-20b,llama-3.3-70b-versatile"
    ).split(",") if x.strip()
]
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "20"))
RPM_LIMIT = int(os.getenv("RPM_LIMIT", "60"))

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY belum di-set.")
if not ADMIN_KEY:
    raise RuntimeError("ADMIN_KEY belum di-set.")

groq = AsyncGroq(api_key=GROQ_API_KEY)
app = FastAPI(title=APP_NAME, version="1.0.0")

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    c = db()
    c.execute("""CREATE TABLE IF NOT EXISTS api_keys(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key_hash TEXT UNIQUE NOT NULL,
        key_prefix TEXT NOT NULL,
        name TEXT,
        active INTEGER DEFAULT 1,
        created_at INTEGER NOT NULL,
        requests INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS usage(
        key_hash TEXT,
        ts INTEGER
    )""")
    c.commit(); c.close()

init_db()

def hash_key(k: str) -> str:
    return hashlib.sha256(k.encode()).hexdigest()

def make_key() -> str:
    return "ag-" + secrets.token_urlsafe(24)

def create_key_record(name="user"):
    raw = make_key()
    h = hash_key(raw)
    c = db()
    c.execute(
        "INSERT INTO api_keys(key_hash,key_prefix,name,created_at) VALUES(?,?,?,?)",
        (h, raw[:12], name, int(time.time()))
    )
    c.commit(); c.close()
    return raw

def authenticate(auth: Optional[str] = Header(None)):
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(401, "Gunakan Authorization: Bearer ag-...")
    raw = auth[7:].strip()
    h = hash_key(raw)
    c = db()
    row = c.execute(
        "SELECT * FROM api_keys WHERE key_hash=? AND active=1", (h,)
    ).fetchone()
    if not row:
        c.close()
        raise HTTPException(401, "API key tidak valid atau sudah dinonaktifkan.")
    now = int(time.time())
    c.execute("DELETE FROM usage WHERE ts < ?", (now - 60,))
    count = c.execute(
        "SELECT COUNT(*) FROM usage WHERE key_hash=? AND ts>=?",
        (h, now - 60)
    ).fetchone()[0]
    if count >= RPM_LIMIT:
        c.close()
        raise HTTPException(429, "Rate limit API key tercapai.")
    c.execute("INSERT INTO usage(key_hash,ts) VALUES(?,?)", (h, now))
    c.execute("UPDATE api_keys SET requests=requests+1 WHERE key_hash=?", (h,))
    c.commit(); c.close()
    return row

class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str = FAMA_MODEL
    messages: list[Message]
    temperature: float = 0.7
    max_tokens: Optional[int] = 2048
    stream: bool = False

def clean_messages(messages):
    msgs = [{"role": m.role, "content": m.content} for m in messages]
    return msgs[-MAX_HISTORY:]

async def groq_call(model, messages, temperature, max_tokens):
    r = await groq.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens
    )
    return {
        "model": model,
        "text": r.choices[0].message.content or "",
        "usage": getattr(r, "usage", None)
    }

async def choose_model(messages):
    # Simple deterministic router. The alias remains Fama2-12.9b.
    text = " ".join(m["content"] for m in messages[-4:]).lower()
    if any(x in text for x in ["kode", "python", "javascript", "html", "css", "program"]):
        candidates = FAMA_ENSEMBLE_MODELS
    elif any(x in text for x in ["hitung", "matematika", "rumus", "persamaan"]):
        candidates = FAMA_ENSEMBLE_MODELS[:2] or [FAMA_DEFAULT_MODEL]
    else:
        candidates = [FAMA_DEFAULT_MODEL]
    return candidates[0]

async def fama_generate(messages, temperature, max_tokens):
    if FAMA_MODE == "single":
        return await groq_call(FAMA_DEFAULT_MODEL, messages, temperature, max_tokens)

    if FAMA_MODE == "ensemble":
        models = FAMA_ENSEMBLE_MODELS[:3]
        results = await asyncio.gather(*[
            groq_call(m, messages, temperature, max_tokens) for m in models
        ], return_exceptions=True)
        texts = [r["text"] for r in results if isinstance(r, dict) and r.get("text")]
        if not texts:
            raise HTTPException(502, "Semua backend model gagal.")
        if len(texts) == 1:
            return {"model": FAMA_MODEL, "text": texts[0], "backend_models": models}
        synthesis = messages + [{
            "role": "system",
            "content": (
                "Kamu adalah final synthesizer Fama. Gabungkan kandidat jawaban "
                "menjadi satu jawaban paling akurat. Jangan menyebut proses internal "
                "atau nama backend. Kandidat:\n\n" + "\n\n---\n\n".join(texts)
            )
        }]
        final = await groq_call(FAMA_DEFAULT_MODEL, synthesis, temperature, max_tokens)
        return {"model": FAMA_MODEL, "text": final["text"], "backend_models": models}

    selected = await choose_model(messages)
    result = await groq_call(selected, messages, temperature, max_tokens)
    result["model"] = FAMA_MODEL
    result["backend_model"] = selected
    return result

@app.get("/")
async def root():
    return {"name": APP_NAME, "model": FAMA_MODEL, "status": "online"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/v1/models")
async def models(_=Depends(authenticate)):
    return {
        "object": "list",
        "data": [{
            "id": FAMA_MODEL,
            "object": "model",
            "owned_by": "fama",
            "active": True
        }]
    }

@app.post("/v1/chat/completions")
async def chat(req: ChatRequest, _=Depends(authenticate)):
    if req.model != FAMA_MODEL:
        raise HTTPException(404, f"Model tidak tersedia. Gunakan {FAMA_MODEL}")

    if req.stream:
        raise HTTPException(400, "stream=true belum diaktifkan pada starter ini.")

    messages = clean_messages(req.messages)
    result = await fama_generate(messages, req.temperature, req.max_tokens)

    return {
        "id": "chatcmpl-" + secrets.token_hex(12),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": FAMA_MODEL,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": result["text"]},
            "finish_reason": "stop"
        }],
        "fama": {
            "backend_model": result.get("backend_model"),
            "backend_models": result.get("backend_models")
        }
    }

@app.post("/admin/keys")
async def create_api_key(x_admin_key: Optional[str] = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Admin key tidak valid.")
    raw = create_key_record("generated")
    return {"api_key": raw, "model": FAMA_MODEL}

@app.get("/admin/keys")
async def list_api_keys(x_admin_key: Optional[str] = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Admin key tidak valid.")
    c = db()
    rows = c.execute(
        "SELECT id,key_prefix,name,active,created_at,requests FROM api_keys ORDER BY id DESC"
    ).fetchall()
    c.close()
    return {"data": [dict(r) for r in rows]}

@app.delete("/admin/keys/{key_id}")
async def revoke_api_key(key_id: int, x_admin_key: Optional[str] = Header(None)):
    if x_admin_key != ADMIN_KEY:
        raise HTTPException(401, "Admin key tidak valid.")
    c = db()
    c.execute("UPDATE api_keys SET active=0 WHERE id=?", (key_id,))
    c.commit(); c.close()
    return {"revoked": True, "id": key_id}
