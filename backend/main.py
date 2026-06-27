from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from agent.graph import run_agent
from config import settings
from models.schemas import ChatRequest, ChatResponse
from rag.retriever import warm_up
from tools.store import get_supabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("restaurant-ai")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    backend = "Supabase" if get_supabase() is not None else "in-memory (no Supabase configured)"
    logger.info("Persistence backend: %s", backend)
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY is not set — /chat will fail until it is configured.")
    if not settings.api_key:
        logger.warning("API_KEY is not set — /chat is open. Set API_KEY to require a header.")
    warm_up()
    yield


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title=f"{settings.restaurant_name} — Customer Service AI",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """When API_KEY is configured, require a matching X-API-Key header."""
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def _valid_session_id(raw: str | None) -> str:
    """Trust a client session id only if it's a well-formed UUID; otherwise mint a
    fresh one so ids can't be guessed/enumerated to reach another conversation."""
    if raw:
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError):
            pass
    return str(uuid.uuid4())


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "restaurant": settings.restaurant_name}


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(require_api_key)])
@limiter.limit(settings.rate_limit)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    session_id = _valid_session_id(body.session_id)

    try:
        result = await run_agent(body.message, session_id)
    except Exception:
        logger.exception("Agent run failed for session %s", session_id)
        raise HTTPException(
            status_code=503,
            detail="The assistant is temporarily unavailable. Please try again in a moment.",
        )

    return ChatResponse(
        session_id=session_id,
        response=result.get("response", ""),
        intent=result.get("intent", "other"),
        needs_human=result.get("needs_human", False),
    )
