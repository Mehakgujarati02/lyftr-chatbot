import { useEffect, useRef, useState } from 'react'

// Runtime config (window.__APP_CONFIG__, injected by the Docker image) wins over build-time VITE_API_URL.
const API_URL = (
  (window.__APP_CONFIG__ && window.__APP_CONFIG__.API_URL) ||
  import.meta.env.VITE_API_URL ||
  'http://localhost:8000'
).replace(/\/+$/, '')

function newSessionId() {
  const rand =
    typeof crypto !== 'undefined' && crypto.randomUUID
      ? crypto.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  return `s-${rand}`
}

function errorText(status, body) {
  const d = body && body.detail
  if (status === 503) return 'All providers are unavailable right now. Please try again in a moment.'
  if (status === 422) {
    if (Array.isArray(d) && d.length) return `Invalid request: ${d.map((e) => e.msg).join('; ')}`
    return 'Invalid request. Messages must be 1–4000 characters.'
  }
  if (typeof d === 'string') return `Error ${status}: ${d}`
  return `Unexpected error (HTTP ${status}).`
}

function Meta({ m }) {
  const cached = m.resolution_source === 'LLM_CACHE'
  return (
    <div className="meta">
      <span className={`badge ${cached ? 'badge-cache' : 'badge-live'}`} data-testid="meta-source">
        {m.resolution_source}
      </span>
      <span className="chip" title="Model">
        <span data-testid="meta-model">{m.model}</span>
      </span>
      <span className="chip" title="Latency">
        <span data-testid="meta-latency">{m.latency_ms} ms</span>
      </span>
      <span className="chip" title="Input tokens">
        in <b data-testid="meta-input-tokens">{m.input_tokens}</b>
      </span>
      <span className="chip" title="Output tokens">
        out <b data-testid="meta-output-tokens">{m.output_tokens}</b>
      </span>
      <span className="chip muted" title="Key that answered">
        key <b data-testid="meta-key-id">{m.key_id ?? 'null'}</b>
      </span>
      <span className="chip muted" title="Failed keys before success">
        fallbacks <b data-testid="meta-fallback-attempts">{m.fallback_attempts}</b>
      </span>
    </div>
  )
}

export default function App() {
  const [sessionId, setSessionId] = useState(newSessionId) // new session on every page load
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [systemPrompt, setSystemPrompt] = useState('')
  const [showSettings, setShowSettings] = useState(false)
  const [simulate, setSimulate] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages, loading])

  async function send() {
    const text = input.trim()
    if (!text || loading) return
    setInput('')
    setMessages((prev) => [...prev, { role: 'user', content: text }])
    setLoading(true)
    try {
      const headers = { 'Content-Type': 'application/json' }
      if (simulate.trim()) headers['X-Simulate-Failure'] = simulate.trim()
      const payload = { session_id: sessionId, message: text }
      if (systemPrompt.trim()) payload.system_prompt = systemPrompt.trim()
      const res = await fetch(`${API_URL}/chat`, { method: 'POST', headers, body: JSON.stringify(payload) })
      let body = null
      try {
        body = await res.json()
      } catch {
        /* non-JSON body */
      }
      if (!res.ok || !body) {
        setMessages((prev) => [...prev, { role: 'error', content: errorText(res.status, body) }])
      } else {
        setMessages((prev) => [...prev, { role: 'assistant', content: body.reply, metadata: body.metadata }])
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'error', content: `Could not reach the server at ${API_URL}. Check that the backend is running.` },
      ])
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  function resetChat() {
    setSessionId(newSessionId())
    setMessages([])
  }

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="logo">L</div>
          <div>
            <h1>Lyftr Chat</h1>
            <p className="sub">Key failover · LiteLLM response cache</p>
          </div>
        </div>
        <div className="header-actions">
          <button className="ghost" onClick={() => setShowSettings((v) => !v)} aria-expanded={showSettings}>
            {showSettings ? 'Hide settings' : 'Settings'}
          </button>
          <button className="ghost" onClick={resetChat}>New chat</button>
        </div>
      </header>

      {showSettings && (
        <section className="settings">
          <label>
            System prompt <span className="muted">(optional, applies to this session)</span>
            <textarea
              data-testid="system-prompt-input"
              rows={2}
              value={systemPrompt}
              onChange={(e) => setSystemPrompt(e.target.value)}
              placeholder="You are a helpful, concise assistant."
            />
          </label>
          <label>
            X-Simulate-Failure <span className="muted">(demo only, e.g. key_1=429 or *=429)</span>
            <input value={simulate} onChange={(e) => setSimulate(e.target.value)} placeholder="leave empty for normal requests" />
          </label>
          <p className="muted small">Session: <code>{sessionId}</code></p>
        </section>
      )}

      <main className="chat">
        {messages.length === 0 && !loading && (
          <div className="empty">
            <h2>How can I help today?</h2>
            <p>Each reply shows whether it came from the LLM cache or live inference, plus its latency and token usage.</p>
          </div>
        )}
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="row row-user">
              <div className="bubble bubble-user" data-testid="user-message">{m.content}</div>
            </div>
          ) : m.role === 'assistant' ? (
            <div key={i} className="row row-assistant">
              <div className="avatar">AI</div>
              <div className="bubble bubble-assistant" data-testid="assistant-message">
                <div className="reply">{m.content}</div>
                <Meta m={m.metadata} />
              </div>
            </div>
          ) : (
            <div key={i} className="row row-assistant">
              <div className="avatar avatar-err">!</div>
              <div className="bubble bubble-error" role="alert" data-testid="error-message">{m.content}</div>
            </div>
          ),
        )}
        {loading && (
          <div className="row row-assistant">
            <div className="avatar">AI</div>
            <div className="bubble bubble-assistant typing" aria-label="Generating response" data-testid="loading-indicator">
              <span /><span /><span />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </main>

      <footer className="composer">
        <textarea
          ref={inputRef}
          data-testid="chat-input"
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Type a message… (Enter to send, Shift+Enter for a new line)"
          maxLength={4000}
          autoFocus
        />
        <button data-testid="send-button" onClick={send} disabled={loading || !input.trim()}>
          {loading ? 'Sending…' : 'Send'}
        </button>
      </footer>
    </div>
  )
}
