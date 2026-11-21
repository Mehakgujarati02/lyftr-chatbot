import json
import sqlite3

from fastapi.testclient import TestClient

SECRETS = ("test-secret-one", "test-secret-two")


def chat(client, sid, msg, headers=None, **extra):
    return client.post("/chat", json={"session_id": sid, "message": msg, **extra}, headers=headers or {})


def assert_no_secrets(resp):
    for s in SECRETS:
        assert s not in resp.text


# ---------- health ----------
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


# ---------- chat + validation ----------
def test_valid_chat(client, fake):
    r = chat(client, "s-1", "  What is the capital of France?  ")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "s-1"
    assert body["reply"]
    m = body["metadata"]
    assert m["resolution_source"] == "LIVE_INFERENCE"
    assert m["model"] == "fake/test-model"
    assert isinstance(m["latency_ms"], int) and m["latency_ms"] >= 0
    assert m["input_tokens"] > 0 and m["output_tokens"] == 7
    assert m["key_id"] == "key_1"
    assert m["fallback_attempts"] == 0
    assert fake.calls[0]["messages"][-1]["content"] == "What is the capital of France?"  # trimmed
    assert_no_secrets(r)


def test_missing_message_422(client):
    r = client.post("/chat", json={"session_id": "s-x"})
    assert r.status_code == 422
    assert "detail" in r.json()


def test_empty_and_whitespace_message_422(client):
    assert chat(client, "s-x", "").status_code == 422
    assert chat(client, "s-x", "    ").status_code == 422


def test_message_over_4000_chars_422(client):
    assert chat(client, "s-x", "a" * 4001).status_code == 422
    assert chat(client, "s-x", "a" * 4000).status_code == 200


def test_session_id_validation_422(client):
    assert chat(client, "", "hi").status_code == 422
    assert chat(client, "x" * 129, "hi").status_code == 422
    assert client.post("/chat", json={"message": "hi"}).status_code == 422


def test_malformed_json_422(client):
    r = client.post("/chat", content="{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert "detail" in r.json()


# ---------- storage / history ----------
def test_sqlite_persistence_and_history_endpoint(client, tmp_path):
    chat(client, "s-persist", "hello")
    r = client.get("/sessions/s-persist/messages")
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["content"] == "hello"
    assert msgs[1]["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert "metadata" not in msgs[0]

    # Data is really in the SQLite file, with assistant metadata stored as JSON.
    conn = sqlite3.connect(tmp_path / "test.db")
    rows = conn.execute("SELECT role, content, metadata, created_at FROM messages WHERE session_id='s-persist'").fetchall()
    assert len(rows) == 2 and rows[0][2] is None
    assert json.loads(rows[1][2])["key_id"] == "key_1"


def test_history_survives_app_restart(client, tmp_path):
    chat(client, "s-restart", "remember me")
    from app.main import app
    with TestClient(app) as c2:  # lifespan runs again against the same DB file
        r = c2.get("/sessions/s-restart/messages")
        assert r.status_code == 200 and len(r.json()["messages"]) == 2


def test_unknown_session_404(client):
    r = client.get("/sessions/does-not-exist/messages")
    assert r.status_code == 404
    assert r.json() == {"detail": "session not found"}


def test_multi_turn_history_sent_to_llm(client, fake):
    chat(client, "s-mt", "My name is Ada.")
    chat(client, "s-mt", "What is my name?")
    sent = fake.calls[-1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[1]["content"] == "My name is Ada."
    assert sent[-1]["content"] == "What is my name?"
    assert len(client.get("/sessions/s-mt/messages").json()["messages"]) == 4


def test_session_isolation(client, fake):
    chat(client, "s-a", "Secret A")
    chat(client, "s-b", "Hello from B")
    sent_b = fake.calls[-1]["messages"]
    assert all("Secret A" not in m["content"] for m in sent_b)
    assert len(client.get("/sessions/s-a/messages").json()["messages"]) == 2
    assert len(client.get("/sessions/s-b/messages").json()["messages"]) == 2


def test_system_prompt_used_and_remembered(client, fake):
    chat(client, "s-sp", "hi", system_prompt="Talk like a pirate.")
    assert fake.calls[-1]["messages"][0] == {"role": "system", "content": "Talk like a pirate."}
    chat(client, "s-sp", "again")
    assert fake.calls[-1]["messages"][0]["content"] == "Talk like a pirate."
    # system prompt is not part of history
    assert all(m["role"] != "system" for m in client.get("/sessions/s-sp/messages").json()["messages"])


# ---------- caching ----------
def test_cache_hit_same_first_message_new_session(client, fake):
    r1 = chat(client, "s-c1", "Tell me a fact about owls").json()
    r2 = chat(client, "s-c2", "Tell me a fact about owls").json()
    assert len(fake.calls) == 1  # second request never reached the provider
    assert r1["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    m2 = r2["metadata"]
    assert m2["resolution_source"] == "LLM_CACHE"
    assert r2["reply"] == r1["reply"]
    assert m2["input_tokens"] == r1["metadata"]["input_tokens"]
    assert m2["output_tokens"] == r1["metadata"]["output_tokens"]
    assert m2["key_id"] is None and m2["fallback_attempts"] == 0
    assert m2["latency_ms"] < r1["metadata"]["latency_ms"]
    # cached reply is stored in the second session's history too
    assert client.get("/sessions/s-c2/messages").json()["messages"][1]["metadata"]["resolution_source"] == "LLM_CACHE"


def test_different_message_not_cached(client, fake):
    r1 = chat(client, "s-d1", "Question one").json()
    r2 = chat(client, "s-d2", "Question two").json()
    assert r2["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r1["reply"] != r2["reply"]
    assert len(fake.calls) == 2


def test_cache_depends_on_history_and_system_prompt(client, fake):
    chat(client, "s-h1", "first")
    r = chat(client, "s-h1", "Tell me a fact about owls").json()  # same text, different history
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    r = chat(client, "s-h2", "first", system_prompt="different system").json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"


# ---------- failover ----------
def test_real_key1_failure_falls_back_to_key2(client, fake):
    fake.failing_keys = {"test-secret-one": 429}
    r = chat(client, "s-f1", "hello failover")
    assert r.status_code == 200
    m = r.json()["metadata"]
    assert m["key_id"] == "key_2" and m["fallback_attempts"] == 1
    assert m["resolution_source"] == "LIVE_INFERENCE"
    assert [c["api_key"] for c in fake.calls] == ["test-secret-one", "test-secret-two"]
    assert_no_secrets(r)


def test_real_5xx_falls_back(client, fake):
    fake.failing_keys = {"test-secret-one": 500}
    m = chat(client, "s-f5", "hello 5xx").json()["metadata"]
    assert m["key_id"] == "key_2" and m["fallback_attempts"] == 1


def test_simulated_key1_429_falls_back_to_key2(client, fake):
    r = chat(client, "s-sim1", "simulated", headers={"X-Simulate-Failure": "key_1=429"})
    assert r.status_code == 200
    m = r.json()["metadata"]
    assert m["key_id"] == "key_2" and m["fallback_attempts"] == 1
    # key_1 was never sent to the provider: the simulated failure fired before invoking it
    assert [c["api_key"] for c in fake.calls] == ["test-secret-two"]
    assert r.json()["reply"].startswith("reply#")  # a real provider-generated reply


def test_simulated_key1_500(client, fake):
    m = chat(client, "s-sim2", "sim500", headers={"X-Simulate-Failure": "key_1=500"}).json()["metadata"]
    assert m["key_id"] == "key_2"


def test_simulation_is_per_request(client, fake):
    chat(client, "s-sim3", "one", headers={"X-Simulate-Failure": "key_1=429"})
    m = chat(client, "s-sim3", "two").json()["metadata"]
    assert m["key_id"] == "key_1" and m["fallback_attempts"] == 0


def test_all_keys_fail_503_simulated(client, fake):
    for header in ("*=429", "key_1=429,key_2=500"):
        r = chat(client, "s-dead", "anyone there?", headers={"X-Simulate-Failure": header})
        assert r.status_code == 503
        assert r.json() == {"detail": "all providers unavailable"}
    assert fake.calls == []


def test_all_keys_fail_503_real(client, fake):
    fake.failing_keys = {"test-secret-one": 429, "test-secret-two": 503}
    r = chat(client, "s-dead2", "anyone?")
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert_no_secrets(r)


def test_failed_requests_not_stored(client, fake):
    chat(client, "s-store", "ok message")
    chat(client, "s-store", "this will fail", headers={"X-Simulate-Failure": "*=429"})
    chat(client, "s-store", "x" * 5000)  # 422
    msgs = client.get("/sessions/s-store/messages").json()["messages"]
    assert [m["content"] for m in msgs if m["role"] == "user"] == ["ok message"]
    # a session whose only request failed does not exist
    chat(client, "s-never", "fail", headers={"X-Simulate-Failure": "*=503"})
    assert client.get("/sessions/s-never/messages").status_code == 404


def test_simulation_disabled_ignores_header(client, fake, monkeypatch):
    monkeypatch.setenv("ENABLE_FAILURE_SIMULATION", "false")
    r = chat(client, "s-off", "no sim", headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_1"


def test_simulation_bypasses_cache_read(client, fake):
    chat(client, "s-cb1", "cached question")
    r = chat(client, "s-cb2", "cached question", headers={"X-Simulate-Failure": "key_1=429"}).json()
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert r["metadata"]["key_id"] == "key_2" and r["metadata"]["fallback_attempts"] == 1
    assert chat(client, "s-cb3", "cached question").json()["metadata"]["resolution_source"] == "LLM_CACHE"


def test_cache_ttl_is_long():
    import litellm
    from app.config import get_settings
    from app.llm import setup_cache
    setup_cache(get_settings())
    assert litellm.cache.ttl == 86400  # not LiteLLM's 10-minute default
