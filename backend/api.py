"""Local HTTP API. Run: uvicorn api:app --reload   then open http://127.0.0.1:8000/docs"""
import secrets
from threading import Lock

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core import config
from core.inference import LLM, MockLLM, LlamaCppLLM
from core.storage import connect, get_db, migrate
from routes.records import router as records_router



def require_token(x_api_token: str | None = Header(default=None)):
    """No-op when API_TOKEN is unset (dev). Otherwise the header must match."""
    if config.API_TOKEN and not secrets.compare_digest(x_api_token or "", config.API_TOKEN):
        raise HTTPException(401, "invalid or missing X-API-Token")


app = FastAPI(title="GitKeepers Local API", version="1.0.0")
auth = [Depends(require_token)]
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
db = connect()
try:
    migrate(db)
finally:
    db.close()
model_path = config.MODELS_DIR / "Qwen3-4B-Q4_K_M.gguf"
llm: LLM | None = None
llm_lock = Lock()
app.include_router(records_router, prefix="/api/v1", dependencies=auth, tags=["records"])


def get_llm() -> LLM:
    global llm
    with llm_lock:
        if llm is None:
            llm = LlamaCppLLM(model_path=str(model_path)) if model_path.is_file() else MockLLM()
        return llm


class ChatRequest(BaseModel):
    message: str
    conversation_id: int | None = None


class ConversationRecord(BaseModel):
    id: int
    title: str | None
    created_at: str


class MessageRecord(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: str


class ConversationPage(BaseModel):
    items: list[ConversationRecord]
    total: int
    limit: int
    offset: int


class MessagePage(BaseModel):
    items: list[MessageRecord]
    total: int
    limit: int
    offset: int


@app.get("/health")  # open on purpose: the shell polls it before it has the token
def health():
    return {"status": "ok"}


def _conversation_page(limit: int | None, offset: int = 0) -> dict:
    db = connect()
    try:
        total = db.execute("SELECT count(*) FROM conversations").fetchone()[0]
        sql = "SELECT id, title, created_at FROM conversations ORDER BY id DESC"
        params = []
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        items = [
            dict(row) for row in db.execute(sql, params)
        ]
        return {"items": items, "total": total, "limit": limit, "offset": offset}
    finally:
        db.close()


def _message_page(cid: int, limit: int | None, offset: int = 0) -> dict:
    db = connect()
    try:
        total = db.execute(
            "SELECT count(*) FROM messages WHERE conversation_id = ?", (cid,)
        ).fetchone()[0]
        sql = (
            "SELECT id, conversation_id, role, content, created_at FROM messages "
            "WHERE conversation_id = ? ORDER BY id"
        )
        params = [cid]
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        items = [
            dict(row) for row in db.execute(sql, params)
        ]
        return {"items": items, "total": total, "limit": limit, "offset": offset}
    finally:
        db.close()


@app.get(
    "/api/v1/conversations",
    response_model=ConversationPage,
    dependencies=auth,
    tags=["conversations"],
)
def list_conversations(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return _conversation_page(limit, offset)


@app.get("/conversations", dependencies=auth, include_in_schema=False)
def list_conversations_legacy():
    return _conversation_page(None)["items"]


@app.get(
    "/api/v1/conversations/{cid}/messages",
    response_model=MessagePage,
    dependencies=auth,
    tags=["conversations"],
)
def get_messages(
    cid: int,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return _message_page(cid, limit, offset)


@app.get("/conversations/{cid}/messages", dependencies=auth, include_in_schema=False)
def get_messages_legacy(cid: int):
    return _message_page(cid, None)["items"]


@app.post("/api/v1/chat", dependencies=auth, tags=["chat"])
@app.post("/chat", dependencies=auth, include_in_schema=False)
def chat(req: ChatRequest):
    db = connect()
    try:
        cid = req.conversation_id
        if cid is None:
            cid = db.execute("INSERT INTO conversations (title) VALUES (?)",
                             (req.message[:40],)).lastrowid
        elif not db.execute("SELECT 1 FROM conversations WHERE id=?", (cid,)).fetchone():
            raise HTTPException(404, "conversation not found")
        db.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?,?,?)",
                   (cid, "user", req.message))
        db.commit()
    finally:
        db.close()

    def events():
        parts = []
        for piece in get_llm().stream(req.message):
            parts.append(piece)
            yield f"data: {piece}\n\n"
        db2 = connect()
        try:
            db2.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?,?,?)",
                        (cid, "assistant", "".join(parts)))
        finally:
            db2.close()
        yield "event: done\ndata: " + str(cid) + "\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
