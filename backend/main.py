"""FastAPI entrypoint.

Exposes POST /chat, which runs one message through the LangGraph agent and
returns the reply. Conversation state is kept per session via the agent's
checkpointer (keyed by session_id), so the HTTP layer itself stays stateless —
it just carries the session_id back and forth.

Cross-cutting concerns wired here: CORS, slowapi rate limiting, and config that
comes only from the environment.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from agent.graph import run_agent
from config import settings
from models.schemas import ChatRequest, ChatResponse
from tools.store import get_supabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("restaurant-ai")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Surface the runtime config so whoever runs the demo knows the state.
    backend = "Supabase" if get_supabase() is not None else "in-memory (no Supabase configured)"
    logger.info("Persistence backend: %s", backend)
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY is not set — /chat will fail until it is configured.")
    yield


# Rate limit per client IP.
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title=f"{settings.restaurant_name} — Customer Service AI",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS so the Vite frontend (its own origin) can call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "restaurant": settings.restaurant_name}


@app.post("/chat", response_model=ChatResponse)
@limiter.limit(settings.rate_limit)
def chat(request: Request, body: ChatRequest) -> ChatResponse:
    # No session id from the client => start a new conversation.
    session_id = body.session_id or str(uuid.uuid4())

    try:
        result = run_agent(body.message, session_id)
    except Exception:
        # e.g. OpenAI is unreachable or the key is missing. Return a clean 503
        # (the frontend shows a friendly fallback) instead of leaking a 500.
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
