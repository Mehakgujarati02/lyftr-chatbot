"""FastAPI app: /health, /chat, /sessions/{id}/messages."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import db, llm
from .config import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    db.init_db(s.database_path)
    llm.setup_cache(s)
    await llm.warm_up_cache()
    log.info("started: keys=%d model=%s cache=%s simulation=%s",
             len(s.api_keys), s.default_model, s.cache_type, s.enable_failure_simulation)
    yield


app = FastAPI(title="Lyftr LLM Chatbot", lifespan=lifespan)

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.allowed_origins or ["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ---------- error handling: always JSON with `detail`, never stack traces ----------
@app.exception_handler(StarletteHTTPException)
async def http_exc_handler(_: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    errors = [{"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.exception_handler(Exception)
async def unhandled_handler(_: Request, exc: Exception):
    log.error("unhandled error: %s", type(exc).__name__)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


# ---------- schemas ----------
class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str
    system_prompt: str | None = Field(default=None, max_length=8000)

    @field_validator("session_id")
    @classmethod
    def _session_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("session_id must not be blank")
        return v

    @field_validator("message")
    @classmethod
    def _message_len(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 4000:
            raise ValueError("message must be 1-4000 characters after trimming")
        return v

    @field_validator("system_prompt")
    @classmethod
    def _sp(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


# ---------- routes ----------
@app.get("/health")
async def health():
    s = get_settings()
    db_ok = db.ping()
    body = {
        "status": "ok" if db_ok and s.api_keys else "degraded",
        "keys_configured": len(s.api_keys),
        "cache_enabled": llm.litellm.cache is not None,
    }
    return JSONResponse(status_code=200 if db_ok else 503, content=body)


@app.post("/chat")
async def chat(req: ChatRequest, x_simulate_failure: str | None = Header(default=None)):
    s = get_settings()

    system_prompt = req.system_prompt or db.get_system_prompt(req.session_id) or s.default_system_prompt
    history = db.get_history(req.session_id)
    messages = [{"role": "system", "content": system_prompt}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": req.message})

    simulate = {}
    if s.enable_failure_simulation and x_simulate_failure:
        simulate = llm.parse_simulation_header(x_simulate_failure, [k for k, _ in s.key_pool])

    try:
        result = await llm.complete(messages, s, simulate=simulate)
    except llm.AllProvidersFailed:
        return JSONResponse(status_code=503, content={"detail": "all providers unavailable"})

    db.save_exchange(req.session_id, req.message, result.reply, result.metadata, req.system_prompt)
    return {"session_id": req.session_id, "reply": result.reply, "metadata": result.metadata}


@app.get("/sessions/{session_id}/messages")
async def session_messages(session_id: str):
    history = db.get_history(session_id)
    if not history:
        return JSONResponse(status_code=404, content={"detail": "session not found"})
    return {"session_id": session_id, "messages": history}
