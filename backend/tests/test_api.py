"""/chat endpoint tests. run_agent is stubbed, so no graph/LLM runs — we only
exercise the API layer: auth, session-id handling, and the error path."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("langgraph")

from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from config import settings  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    async def fake_run_agent(message, session_id):
        return {"response": f"echo: {message}", "intent": "greeting", "needs_human": False}

    monkeypatch.setattr(main, "run_agent", fake_run_agent)
    # Disable rate limiting noise for tests.
    main.app.state.limiter.enabled = False
    return TestClient(main.app)


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_chat_returns_response_and_session(client):
    r = client.post("/chat", json={"message": "hi"})
    assert r.status_code == 200
    body = r.json()
    assert body["response"] == "echo: hi"
    assert body["session_id"]  # server minted one


def test_chat_rejects_blank_message(client):
    r = client.post("/chat", json={"message": ""})
    assert r.status_code == 422


def test_chat_replaces_non_uuid_session(client):
    r = client.post("/chat", json={"message": "hi", "session_id": "not-a-uuid"})
    assert r.status_code == 200
    # a fresh valid uuid is returned, not the bogus one
    assert r.json()["session_id"] != "not-a-uuid"


def test_chat_keeps_valid_uuid_session(client):
    import uuid

    sid = str(uuid.uuid4())
    r = client.post("/chat", json={"message": "hi", "session_id": sid})
    assert r.json()["session_id"] == sid


def test_chat_requires_api_key_when_set(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    assert client.post("/chat", json={"message": "hi"}).status_code == 401
    ok = client.post("/chat", json={"message": "hi"}, headers={"X-API-Key": "secret"})
    assert ok.status_code == 200


def test_chat_503_on_agent_failure(client, monkeypatch):
    async def boom(message, session_id):
        raise RuntimeError("down")

    monkeypatch.setattr(main, "run_agent", boom)
    assert client.post("/chat", json={"message": "hi"}).status_code == 503
