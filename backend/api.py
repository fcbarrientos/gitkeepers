"""Local HTTP API. Run: uvicorn api:app --reload   then open http://127.0.0.1:8000/docs"""
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core import config
from core.inference import MockLLM, LlamaCppLLM
from core.storage import connect, get_db



def require_token(x_api_token: str | None = Header(default=None)):
    """No-op when API_TOKEN is unset (dev). Otherwise the header must match."""
    if config.API_TOKEN and not secrets.compare_digest(x_api_token or "", config.API_TOKEN):
        raise HTTPException(401, "invalid or missing X-API-Token")


app = FastAPI(title="Local AI Backend")
auth = [Depends(require_token)]
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
get_db().close()  # run migrations once at startup
model_path = config.MODELS_DIR / "Qwen3-4B-Q4_K_M.gguf"
llm = LlamaCppLLM(model_path=str(model_path))
# llm = MockLLM() - fallback when file missing


class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None


@app.get("/health")  # open on purpose: the shell polls it before it has the token
def health():
    return {"status": "ok"}


@app.get("/conversations", dependencies=auth)
def list_conversations():
    with connect() as db:
        return [dict(r) for r in db.execute("SELECT * FROM conversations ORDER BY id DESC")]


@app.get("/conversations/{cid}/messages", dependencies=auth)
def get_messages(cid: int):
    with connect() as db:
        rows = db.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (cid,))
        return [dict(r) for r in rows]


@app.post("/chat", dependencies=auth)
def chat(req: ChatRequest):
    db = connect()
    cid = req.conversation_id
    if cid is None:
        cid = db.execute("INSERT INTO conversations (title) VALUES (?)",
                         (req.message[:40],)).lastrowid
    elif not db.execute("SELECT 1 FROM conversations WHERE id=?", (cid,)).fetchone():
        db.close()
        raise HTTPException(404, "conversation not found")
    db.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?,?,?)",
               (cid, "user", req.message))
    db.commit()
    db.close()

    def events():
        parts = []
        for piece in llm.stream(req.message):
            parts.append(piece)
            yield f"data: {piece}\n\n"
        with connect() as db2:
            db2.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?,?,?)",
                        (cid, "assistant", "".join(parts)))
        yield "event: done\ndata: " + str(cid) + "\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
