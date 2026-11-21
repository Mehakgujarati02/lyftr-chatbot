"""Test fixtures.

Provider calls are mocked with a LiteLLM CustomLLM provider registered as "fake/...". The request still
goes through litellm.acompletion, so LiteLLM's real caching layer is exercised — no paid API calls.
"""
import asyncio
import os

import litellm
import pytest
from fastapi.testclient import TestClient
from litellm import CustomLLM, ModelResponse

os.environ.setdefault("LLM_API_KEYS", "test-secret-one,test-secret-two")
os.environ.setdefault("DEFAULT_MODEL", "fake/test-model")
os.environ.setdefault("ENABLE_FAILURE_SIMULATION", "true")


class FakeProvider(CustomLLM):
    def __init__(self):
        super().__init__()
        self.calls: list[dict] = []
        self.failing_keys: dict[str, int] = {}

    async def acompletion(self, model, messages, api_key=None, **kwargs):
        self.calls.append({"api_key": api_key, "messages": [dict(m) for m in messages]})
        status = self.failing_keys.get(api_key)
        if status == 429:
            raise litellm.RateLimitError("quota exhausted", llm_provider="fake", model=model)
        if status:
            raise litellm.InternalServerError("upstream error", llm_provider="fake", model=model)
        await asyncio.sleep(0.05)  # simulate network latency so cache hits are measurably faster
        n = len(self.calls)
        content = f"reply#{n} to '{messages[-1]['content']}' (saw {len(messages)} msgs)"
        prompt_tokens = sum(len(m["content"].split()) for m in messages) + 3 * len(messages)
        return ModelResponse(
            model=model,
            choices=[{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            usage={"prompt_tokens": prompt_tokens, "completion_tokens": 7, "total_tokens": prompt_tokens + 7},
        )


@pytest.fixture
def fake():
    provider = FakeProvider()
    litellm.custom_provider_map = [{"provider": "fake", "custom_handler": provider}]
    from litellm.utils import custom_llm_setup
    custom_llm_setup()
    return provider


@pytest.fixture
def client(tmp_path, monkeypatch, fake):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    from app.main import app
    with TestClient(app) as c:  # lifespan creates schema and a fresh LiteLLM cache
        yield c
