"""Runtime configuration, read from environment variables."""
import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str = "") -> list[str]:
    return [v.strip() for v in os.getenv(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    api_keys: list[str] = field(default_factory=list)
    database_url: str = "sqlite:///./app.db"
    allowed_origins: list[str] = field(default_factory=list)
    enable_failure_simulation: bool = False
    default_model: str = "gemini/gemini-3.5-flash-lite"
    default_system_prompt: str = "You are a helpful, concise assistant."
    cache_type: str = "local"  # LiteLLM in-memory cache
    request_timeout: float = 60.0
    cache_ttl_seconds: int = 86400

    @property
    def key_pool(self) -> list[tuple[str, str]]:
        """[(key_id, secret)] — ids are key_1, key_2, ... in configured order."""
        return [(f"key_{i}", k) for i, k in enumerate(self.api_keys, start=1)]

    @property
    def database_path(self) -> str:
        url = self.database_url
        if url.startswith("sqlite:///"):
            return url[len("sqlite:///"):]  # sqlite:////data/app.db -> /data/app.db
        if url.startswith("sqlite://"):
            return url[len("sqlite://"):]
        return url


def get_settings() -> Settings:
    return Settings(
        api_keys=_list("LLM_API_KEYS"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///./app.db"),
        allowed_origins=_list("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173"),
        enable_failure_simulation=_bool("ENABLE_FAILURE_SIMULATION"),
        default_model=os.getenv("DEFAULT_MODEL", "gemini/gemini-3.5-flash-lite"),
        default_system_prompt=os.getenv("DEFAULT_SYSTEM_PROMPT", "You are a helpful, concise assistant."),
        request_timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        cache_ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "86400")),
    )
