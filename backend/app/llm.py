"""LiteLLM gateway: key-pool failover, built-in response caching, failure simulation."""
import logging
import time
from dataclasses import dataclass

import litellm
from litellm.caching.caching import Cache

from .config import Settings

log = logging.getLogger("llm")

litellm.suppress_debug_info = True
litellm.drop_params = True

SIMULATABLE_STATUSES = {429, 500, 502, 503}


class AllProvidersFailed(Exception):
    """Every key in the pool failed for this request."""


@dataclass
class LLMResult:
    reply: str
    metadata: dict


def setup_cache(settings: Settings) -> None:
    """Enable LiteLLM's built-in in-memory response cache.

    (LiteLLM 1.110 supports local/redis/s3/... — no disk backend — and the assignment forbids Redis,
    so the in-process "local" cache is used.)"""
    # LiteLLM's in-memory cache expires entries after 10 minutes by default; keep them longer.
    litellm.cache = Cache(type="local", default_in_memory_ttl=settings.cache_ttl_seconds)


async def warm_up_cache() -> None:
    """Exercise LiteLLM's cache-hit code path once at startup.

    LiteLLM lazily imports several modules the first time it serves a cache hit, which makes the very first
    hit slow. A mocked round trip (no network, no real key) preloads them so every real hit is fast.
    """
    if litellm.cache is None:
        return
    kwargs = dict(model="openai/__warmup__", messages=[{"role": "user", "content": "__warmup__"}],
                  api_key="warmup", caching=True, mock_response="ok")
    try:
        first = await litellm.acompletion(**kwargs)
        await litellm.cache.async_add_cache(first, model=kwargs["model"], messages=kwargs["messages"])
        await litellm.acompletion(**kwargs)
    except Exception:
        log.info("cache warm-up skipped")


def parse_simulation_header(value: str | None, key_ids: list[str]) -> dict[str, int]:
    """'key_1=429,key_2=500' or '*=429' -> {key_id: status}. Invalid entries are ignored."""
    plan: dict[str, int] = {}
    if not value:
        return plan
    for part in value.split(","):
        if "=" not in part:
            continue
        target, _, status = part.partition("=")
        target, status = target.strip(), status.strip()
        if not status.isdigit() or int(status) not in SIMULATABLE_STATUSES:
            continue
        targets = key_ids if target == "*" else [target]
        for t in targets:
            if t in key_ids:
                plan[t] = int(status)
    return plan


def _simulated_error(status: int, model: str) -> Exception:
    """Build the same exception LiteLLM raises when a provider returns `status`."""
    provider = model.split("/", 1)[0]
    msg = f"Simulated provider failure (HTTP {status})"
    if status == 429:
        return litellm.RateLimitError(msg, llm_provider=provider, model=model)
    if status == 502:
        return litellm.BadGatewayError(msg, llm_provider=provider, model=model)
    if status == 503:
        return litellm.ServiceUnavailableError(msg, llm_provider=provider, model=model)
    return litellm.InternalServerError(msg, llm_provider=provider, model=model)


def _status_of(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None)


async def complete(
    messages: list[dict],
    settings: Settings,
    simulate: dict[str, int] | None = None,
) -> LLMResult:
    """Try each key in order; return the first success. Cache hits short-circuit the pool."""
    model = settings.default_model
    simulate = simulate or {}
    pool = settings.key_pool
    if not pool:
        raise AllProvidersFailed("no keys configured")

    start = time.perf_counter()
    failures = 0
    cache_control = {"no-cache": True} if simulate else None  # force real provider path when simulating

    for key_id, secret in pool:
        try:
            # Simulation happens *before* the provider is invoked with this key.
            if key_id in simulate:
                raise _simulated_error(simulate[key_id], model)

            kwargs = dict(
                model=model,
                messages=messages,
                api_key=secret,
                caching=True,
                num_retries=0,
                timeout=settings.request_timeout,
            )
            if cache_control:
                kwargs["cache"] = cache_control
            response = await litellm.acompletion(**kwargs)

            reply = (response.choices[0].message.content or "").strip()
            if not reply:
                raise litellm.InternalServerError("empty reply", llm_provider=model.split("/")[0], model=model)

            cache_hit = bool(getattr(response, "_hidden_params", {}).get("cache_hit"))
            if not cache_hit and litellm.cache is not None:
                # LiteLLM writes the cache in a background callback; write it synchronously too so an
                # immediate identical request is guaranteed to hit. Cache identity = model + messages.
                try:
                    await litellm.cache.async_add_cache(response, model=model, messages=messages)
                except Exception:  # cache write failure must never break the request
                    log.warning("cache write failed", exc_info=False)

            usage = getattr(response, "usage", None)
            input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
            output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
            if not input_tokens:
                input_tokens = litellm.token_counter(model=model, messages=messages)

            latency_ms = int(round((time.perf_counter() - start) * 1000))
            return LLMResult(
                reply=reply,
                metadata={
                    "resolution_source": "LLM_CACHE" if cache_hit else "LIVE_INFERENCE",
                    "model": model,
                    "latency_ms": latency_ms,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "key_id": None if cache_hit else key_id,
                    "fallback_attempts": 0 if cache_hit else failures,
                },
            )
        except Exception as exc:  # 429 / quota / 5xx / auth / network -> try next key
            failures += 1
            # Log the key *id* and error type only — never the secret or provider payload.
            log.warning("provider failure on %s: %s status=%s", key_id, type(exc).__name__, _status_of(exc))
            continue

    raise AllProvidersFailed(f"{failures} key(s) failed")
