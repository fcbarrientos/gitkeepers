"""Local HTTP API. Run: uvicorn api:app --reload   then open http://127.0.0.1:8000/docs"""
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exception_handlers import http_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from core import config
from core.assist import MODEL_LOCK, AIUnavailable, load_model
from core.auth import current_user
from core.errors import ApiError
from core.inference import LLM, MockLLM
from core.storage import connect, get_db, migrate
from routes.auth import router as auth_router
from routes.dashboard import router as dashboard_router
from routes.follow_ups import router as follow_ups_router
from routes.forms import router as forms_router
from routes.records import router as records_router
from routes.users import router as users_router
from routes.visits import router as visits_router



def require_token(x_api_token: str | None = Header(default=None)):
    """No-op when API_TOKEN is unset (dev). Otherwise the header must match."""
    if config.API_TOKEN and not secrets.compare_digest(x_api_token or "", config.API_TOKEN):
        raise HTTPException(401, "invalid or missing X-API-Token")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Migrate on startup, not on import, so tests can point config at a temp folder first.
    db = connect()
    try:
        migrate(db)
    finally:
        db.close()
    yield


app = FastAPI(title="GitKeepers Local API", version="1.0.0", lifespan=lifespan)
auth = [Depends(require_token)]
signed_in = [*auth, Depends(current_user)]  # shell token + an active user session
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(records_router, prefix="/api/v1", dependencies=signed_in, tags=["records"])
app.include_router(auth_router, prefix="/api/v1", dependencies=auth, tags=["auth"])
app.include_router(users_router, prefix="/api/v1", dependencies=auth, tags=["users"])
app.include_router(forms_router, prefix="/api/v1", dependencies=signed_in, tags=["forms"])
app.include_router(visits_router, prefix="/api/v1", dependencies=signed_in, tags=["visits"])
app.include_router(follow_ups_router, prefix="/api/v1", dependencies=signed_in, tags=["follow-ups"])
app.include_router(dashboard_router, prefix="/api/v1", dependencies=signed_in, tags=["dashboard"])


@app.exception_handler(ApiError)
async def api_error_handler(_request, exc: ApiError):
    headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=headers)


@app.exception_handler(sqlite3.OperationalError)
async def database_busy_handler(_request, exc: sqlite3.OperationalError):
    if "locked" not in str(exc) and "busy" not in str(exc):
        raise exc
    return JSONResponse(status_code=503, content={"detail": "Database is busy, please try again"})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request, exc: RequestValidationError):
    # Drop the echoed "input" from request-body errors: it can contain the submitted
    # password, and frontends may log or display these bodies.
    errors = [
        {key: value for key, value in error.items() if key != "input"}
        if error.get("loc", ())[:1] == ("body",) else error
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


RESERVED_PREFIXES = {"api", "docs", "redoc", "openapi.json", "health"}


def _frontend_file(path: str) -> Path | None:
    """The built web app's file for a GET that matched no API route, or None."""
    dist = config.FRONTEND_DIST
    index = dist / "index.html"
    relative = path.lstrip("/")
    if relative.split("/", 1)[0] in RESERVED_PREFIXES or not index.is_file():
        return None
    candidate = (dist / relative).resolve()
    if relative and candidate.is_file() and candidate.is_relative_to(dist.resolve()):
        return candidate
    if "." in relative.rsplit("/", 1)[-1]:
        return None  # a missing asset stays a 404 instead of returning the page
    return index  # a client-side route such as /patients/5


@app.exception_handler(StarletteHTTPException)
async def frontend_fallback(request, exc: StarletteHTTPException):
    file = None
    if exc.status_code == 404 and request.method in ("GET", "HEAD"):
        file = _frontend_file(request.url.path)
    if file is None:
        return await http_exception_handler(request, exc)
    return FileResponse(file)


def get_llm() -> LLM:
    """The shared local model for chat, or the mock when it's unavailable."""
    try:
        return load_model()
    except AIUnavailable:
        return MockLLM()


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
    dependencies=signed_in,
    tags=["conversations"],
)
def list_conversations(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return _conversation_page(limit, offset)


@app.get("/conversations", dependencies=signed_in, include_in_schema=False)
def list_conversations_legacy():
    return _conversation_page(None)["items"]


@app.get(
    "/api/v1/conversations/{cid}/messages",
    response_model=MessagePage,
    dependencies=signed_in,
    tags=["conversations"],
)
def get_messages(
    cid: int,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    return _message_page(cid, limit, offset)


@app.get("/conversations/{cid}/messages", dependencies=signed_in, include_in_schema=False)
def get_messages_legacy(cid: int):
    return _message_page(cid, None)["items"]


@app.post("/api/v1/chat", dependencies=signed_in, tags=["chat"])
@app.post("/chat", dependencies=signed_in, include_in_schema=False)
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
        with MODEL_LOCK:
            for piece in get_llm().stream(req.message):
                parts.append(piece)
                yield f"data: {piece}\n\n"
        db2 = connect()
        try:
            with db2:
                db2.execute("INSERT INTO messages (conversation_id, role, content) VALUES (?,?,?)",
                            (cid, "assistant", "".join(parts)))
        finally:
            db2.close()
        yield "event: done\ndata: " + str(cid) + "\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")
