# Lyftr LLM Chatbot — Key Failover & Response Caching

A full-stack chatbot: **React + Vite** frontend, **FastAPI** backend, **LiteLLM** gateway (Gemini by default),
**SQLite** session storage. Includes automatic API-key failover, LiteLLM's built-in response cache,
per-request token tracking, and an `X-Simulate-Failure` hook to demo failover on demand.

```
┌──────────────┐  POST /chat {session_id, message}   ┌──────────────────────────────────────────┐
│ React (Vite) │ ──────────────────────────────────▶ │ FastAPI                                   │
│  :3000       │ ◀── reply + metadata ────────────── │  1. load history + system prompt (SQLite) │
└──────────────┘                                     │  2. build messages [system, ...history,   │
                                                     │     new user msg]                         │
                                                     │  3. for key_1..key_n:                     │
                                                     │       simulated failure? -> next key      │
                                                     │       litellm.acompletion(caching=True)   │
                                                     │       429/quota/5xx/auth/network -> next  │
                                                     │  4. save user+assistant rows (success only)│
                                                     └───────────┬────────────────┬─────────────┘
                                                                 │                │
                                                     LiteLLM in-memory cache   SQLite /data/app.db
```

## 1. Live URLs

| Tier | URL |
|---|---|
| Frontend (Vercel) | https://lyftr-chatbot-black.vercel.app |
| Backend (Render) | https://lyftr-chatbot-h774.onrender.com |
| Repository | https://github.com/Mehakgujarati02/lyftr-chatbot |

> The backend runs on Render's **free** plan: it sleeps when idle, so the first request after a while can take
> 30–60 s, and because the free plan has no persistent disk, SQLite history resets when Render restarts or
> redeploys the service. History does persist across restarts locally with `make up` (named Docker volume).

## 2. Run locally: with Docker and without

### With Docker (recommended)

```bash
cp .env.example .env          # then put your real keys in LLM_API_KEYS
make up                       # builds and starts both services
# Backend:  http://localhost:8000/health
# Frontend: http://localhost:3000
make down                     # stop (history is kept in the named volume)
make clean                    # stop AND delete the SQLite volume
make logs                     # follow logs
```

`make up` creates `.env` from `.env.example` automatically if it is missing.
SQLite lives at `/data/app.db` on the named volume `chat_data`, so history survives `make down && make up`.

### Without Docker

Backend (Python 3.11+), macOS / Linux:

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export LLM_API_KEYS=your_key_1,your_key_2
export DATABASE_URL=sqlite:///./app.db
export ALLOWED_ORIGINS=http://localhost:3000
export ENABLE_FAILURE_SIMULATION=true
uvicorn app.main:app --reload --port 8000
```

Backend, Windows (Command Prompt):

```cmd
cd backend
python -m pip install -r requirements.txt
set LLM_API_KEYS=your_key_1,your_key_2
set DATABASE_URL=sqlite:///./app.db
set ALLOWED_ORIGINS=http://localhost:3000
set ENABLE_FAILURE_SIMULATION=true
python -m uvicorn app.main:app --port 8000
```

Frontend (Node 20+), any OS:

```bash
cd frontend
npm install
npm run dev     # http://localhost:3000, talks to http://localhost:8000 by default
```

Set `VITE_API_URL` before `npm run dev` / `npm run build` to point the frontend at a different backend.

### Tests

```bash
cd backend
pip install -r requirements.txt pytest httpx
python -m pytest -q          # or: make test
```

The tests make **no paid API calls**: a LiteLLM `CustomLLM` provider (`fake/...`) is registered in
`tests/conftest.py`, so requests still flow through `litellm.acompletion` and LiteLLM's real cache layer,
but the provider itself is mocked. 27 tests cover: health, valid chat, missing / empty / >4000-char
messages, session_id rules, malformed JSON, SQLite persistence (including across app restart), the history
endpoint and 404, multi-turn history, session isolation, system prompt, cache hit / miss / identity,
real and simulated key_1 → key_2 failover, all-keys-fail 503, and failed requests not being stored.

### Environment variables

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `LLM_API_KEYS` | yes | – | Comma-separated key pool (≥2). Ids are `key_1`, `key_2`, … in order |
| `DATABASE_URL` | yes | `sqlite:///./app.db` (Docker: `sqlite:////data/app.db`) | SQLite file location |
| `ALLOWED_ORIGINS` | yes | `http://localhost:3000,http://localhost:5173` | Comma-separated CORS origins |
| `ENABLE_FAILURE_SIMULATION` | yes | `false` | `true` enables the `X-Simulate-Failure` header |
| `DEFAULT_MODEL` | no | `gemini/gemini-3.5-flash-lite` | LiteLLM model name |
| `DEFAULT_SYSTEM_PROMPT` | no | `You are a helpful, concise assistant.` | Used when the client sends none |
| `LLM_TIMEOUT_SECONDS` | no | `60` | Per-call provider timeout |
| `CACHE_TTL_SECONDS` | no | `86400` | How long LiteLLM keeps cached responses (LiteLLM's own default is 10 min) |
| `VITE_API_URL` | frontend | `http://localhost:8000` | Backend URL for the SPA (build-time; the Docker image also accepts `API_URL` at runtime) |

### API

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | `{"status":"ok","keys_configured":2,"cache_enabled":true}` |
| POST | `/chat` | Body `{session_id, message, system_prompt?}`; optional header `X-Simulate-Failure` |
| GET | `/sessions/{session_id}/messages` | History oldest-first, no system prompt; 404 `{"detail":"session not found"}` |

Errors are always JSON with `detail`: 422 for validation / malformed JSON, 503
`{"detail":"all providers unavailable"}` when every key fails, 404 for unknown sessions, and a generic 500
`{"detail":"internal server error"}` as a last resort. No stack traces or keys are ever returned or logged.

## 3. Design decisions: key fallback, caching, SQLite session storage

### Model choice
The brief's example model `gemini/gemini-2.0-flash` has been shut down by Google, and `gemini-2.5-*` is no longer
offered to new API keys, so the app uses **`gemini/gemini-3.5-flash-lite`**: fast, available on the free tier, and
configurable through `DEFAULT_MODEL` without code changes.

### Key fallback
* `LLM_API_KEYS` is parsed into an ordered pool `[(key_1, secret), (key_2, secret), …]`. Only the **id**
  ever leaves the process (response metadata, logs).
* `app/llm.py::complete()` walks the pool and calls `litellm.acompletion(..., api_key=secret, num_retries=0)`
  for each key. Any provider exception — LiteLLM's `RateLimitError` (429 and Gemini quota
  `RESOURCE_EXHAUSTED`), `InternalServerError` / `BadGatewayError` / `ServiceUnavailableError` (5xx), timeouts,
  connection errors, and auth errors on a revoked key — moves on to the next key. `fallback_attempts` is
  the number of keys that failed before the one that answered.
* If every key fails, the API returns **503 `{"detail":"all providers unavailable"}`** and nothing is stored.
* I used an explicit loop around `litellm.acompletion` rather than `litellm.Router` because the contract
  needs exact per-request `key_id` / `fallback_attempts` and a per-request failure-injection point *before*
  a specific key is used. The loop is ~30 lines and makes both of those explicit and testable.

**Failure simulation.** When `ENABLE_FAILURE_SIMULATION=true`, `X-Simulate-Failure` (`key_1=429`,
`key_1=429,key_2=500`, `*=429`; statuses 429/500/502/503) is parsed into a per-request plan. Inside the loop,
*before* a listed key is invoked, the code raises the same LiteLLM exception class the provider would
(`RateLimitError`, `InternalServerError`, …), which goes through the exact same `except` branch as a real
failure. The next key then makes a **real** LLM call. The plan is local to the request, so nothing leaks
into other requests. Requests carrying the header skip the cache *read* (`cache={"no-cache": True}`), so
a repeated demo message still shows real failover instead of a cache hit. The result is still written to
the cache.

### Caching
* `litellm.cache = Cache(type="local", default_in_memory_ttl=CACHE_TTL_SECONDS)`: LiteLLM's built-in in-memory cache. Every call passes
  `caching=True`. LiteLLM 1.110 has no disk cache backend, and Redis is not allowed here, so the in-process
  cache is used, with a 24 h TTL (`CACHE_TTL_SECONDS`) instead of LiteLLM's 10-minute default. It is cleared when
  the backend restarts (SQLite history is not).
* **Cache identity** = LiteLLM's own cache key, built from the model and the full `messages` list
  (system prompt + history + new message). I checked in LiteLLM 1.110.2 that `api_key` is *not* part of
  the key, so a reply produced by `key_2` is reusable whichever key would have been tried. The same first
  message in a new session gives the same message list, so it hits. Any different message, history or
  system prompt gives a different key, so it misses.
* **Hit detection** uses LiteLLM's supported flag `response._hidden_params["cache_hit"]`. On a hit the
  API returns `resolution_source="LLM_CACHE"`, the identical stored reply, the **usage stored with the
  cached response** (`prompt_tokens` / `completion_tokens`), `key_id=null` and `fallback_attempts=0`.
* LiteLLM writes the cache from a background success callback. To make "send the same message right away"
  deterministic, the backend also awaits `litellm.cache.async_add_cache(response, model=…, messages=…)`,
  LiteLLM's own API with the same key derivation.
* LiteLLM lazily imports several modules the first time it serves a hit, which made the first hit slower than
  a live call. A mocked warm-up round trip at startup (no network, no real key) preloads them, so hits are
  ~1–3 ms against hundreds of ms for live inference.

### SQLite session storage
* `messages(id, session_id, role, content, metadata, created_at)` exactly as specified, plus an index on
  `(session_id, id)` and a small `sessions(session_id, system_prompt, created_at)` table so a system prompt
  set once is remembered for later turns in that session. The schema is created on startup (`CREATE TABLE IF NOT EXISTS`).
* Each successful turn writes the user row and the assistant row (with metadata JSON) in **one
  transaction**, *after* the LLM succeeds. A 422 or 503 therefore never touches history.
* History is loaded per request and sent with the new message, so the client only sends the new message.
  Sessions are isolated by `session_id`. The frontend generates a fresh `crypto.randomUUID()` id on every
  page load.
* A new short-lived connection per operation keeps it simple and safe with uvicorn's event loop.
  `DATABASE_URL=sqlite:////data/app.db` sits on the Compose named volume.

## 4. Verification: how to see failover, cache hits and per-message token usage

```bash
B=http://localhost:8000
curl -s $B/health

# Live inference
curl -s -XPOST $B/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-1","message":"What is the capital of France?"}'
# -> resolution_source LIVE_INFERENCE, key_id key_1, fallback_attempts 0

# Cache hit: same first message, new session
curl -s -XPOST $B/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"demo-2","message":"What is the capital of France?"}'
# -> LLM_CACHE, identical reply, same tokens, key_id null, latency ~1-3 ms

# Failover: key_1 rate-limited -> key_2 answers with a real reply
curl -s -XPOST $B/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: key_1=429' \
  -d '{"session_id":"demo-1","message":"And of Germany?"}'
# -> 200, key_id key_2, fallback_attempts 1 (and multi-turn: it knows the context)

# All keys down -> 503, not stored
curl -s -i -XPOST $B/chat -H 'Content-Type: application/json' -H 'X-Simulate-Failure: *=429' \
  -d '{"session_id":"demo-1","message":"hello?"}'

# History (oldest first, assistant metadata included)
curl -s $B/sessions/demo-1/messages
```

**In the UI** every assistant bubble shows `LIVE_INFERENCE` / `LLM_CACHE`, the model, latency, input and
output tokens for that request only, plus key id and fallback count. Reload the page (new session) and
resend the first message to see `LLM_CACHE`. Open **Settings** to set a system prompt or type an
`X-Simulate-Failure` value (e.g. `key_1=429`, or `*=429` to see the in-chat error message).

Data-testids: `chat-input`, `send-button`, `assistant-message`, `meta-source`, `meta-model`,
`meta-latency`, `meta-input-tokens`, `meta-output-tokens`, `system-prompt-input`
(plus `meta-key-id`, `meta-fallback-attempts`, `error-message`, `loading-indicator`).

## 5. Setup Used

* AI tool: Claude (Anthropic), used to generate, run and debug the code.
* Local machine: Windows, Command Prompt, Python 3.13, Node 22.
* Backend: FastAPI, LiteLLM 1.110.2, SQLite (stdlib `sqlite3`), pytest. Docker image uses Python 3.12.
* Frontend: React 19, Vite 8, plain CSS; served by nginx in the Docker image.
* Hosting: backend on Render (Docker, free plan), frontend on Vercel.
* Verified: 27 pytest tests passing, end-to-end curl checks, a headless Chromium run of the UI, and manual
  testing of the live site (live replies with `gemini/gemini-3.5-flash-lite`, multi-turn memory, cache hit
  after reload, simulated `key_1=429` failover, `*=429` error).

## 6. Bonus features (if any)

* **Per-session system prompt persistence**: set it once and later turns reuse it (stored in `sessions`).
* **Failure simulation from the UI** (Settings panel), so failover can be demoed without curl.
* **Key id and fallback count shown per message**, and a "New chat" button.
* **Runtime-configurable frontend image**: `API_URL` env writes `/config.js` at container start, so one
  image can point at any backend without rebuilding.
* Non-root backend container with a Docker `HEALTHCHECK`. Atomic per-turn writes.
* Failover also covers auth/permission errors (a revoked key), timeouts and network errors, not only 429/5xx.

---

### Project structure

```
.
├── backend/
│   ├── app/
│   │   ├── config.py      # env-var settings, key pool
│   │   ├── db.py          # SQLite schema + queries
│   │   ├── llm.py         # LiteLLM calls, failover loop, cache, failure simulation
│   │   └── main.py        # FastAPI routes, validation, error handlers, CORS
│   ├── tests/             # pytest suite (mocked LiteLLM provider)
│   ├── Dockerfile         # multi-stage (venv builder -> slim runtime)
│   └── requirements.txt
├── frontend/
│   ├── src/App.jsx, main.jsx, styles.css
│   ├── public/config.js   # runtime API_URL hook
│   ├── nginx.conf, docker-entrypoint.d/
│   └── Dockerfile         # multi-stage (node build -> nginx)
├── docker-compose.yml     # backend :8000, frontend :3000, named volume at /data
├── Makefile               # up, down, logs, test, clean
├── .env.example
└── README.md
```

### Deployment checklist

**Backend → Render (Web Service, Docker)**
1. New Web Service from the repo, Root Directory `backend`, runtime Docker.
2. Optional (paid plans): add a **Persistent Disk** mounted at `/data` so history survives redeploys. The current
   deployment uses the free plan without a disk.
3. Env vars: `LLM_API_KEYS`, `DATABASE_URL=sqlite:////data/app.db`, `ENABLE_FAILURE_SIMULATION=true`,
   `DEFAULT_MODEL=gemini/gemini-3.5-flash-lite`, `LLM_TIMEOUT_SECONDS=60`, and `ALLOWED_ORIGINS` set to the Vercel
   URL (or `*`). Render sets `PORT`, which the image honors.
4. Health check path `/health`. Deploy, then `curl https://<backend>/health`.

**Frontend → Vercel**
1. Import the repo, Root Directory `frontend`, framework preset Vite (build `npm run build`, output `dist`).
2. Env var `VITE_API_URL=https://<backend>.onrender.com`, then redeploy so it is baked into the build.
3. Make sure the Vercel URL is in the backend's `ALLOWED_ORIGINS`, then fill in section 1 above.
