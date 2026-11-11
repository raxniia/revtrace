from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    api_key: str
    base_url: str
    embeddings: str
    datasets_dir: Path
    var_dir: Path
    default_dataset: str
    sla_response_minutes: int
    min_followups: int
    max_agent_steps: int

    @property
    def agentic(self) -> bool:
        return self.provider in {"anthropic", "openai"} and bool(self.api_key or self.base_url)

    @property
    def engine_label(self) -> str:
        return f"{self.provider}:{self.model}" if self.agentic else "baseline"


@lru_cache
def get_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    env = os.environ.get
    provider = env("REVTRACE_PROVIDER", "").lower()
    if not provider:
        provider = (
            "anthropic" if env("ANTHROPIC_API_KEY") else "openai" if env("OPENAI_API_KEY") else "baseline"
        )
    key = env("REVTRACE_API_KEY") or env(
        "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY", ""
    )
    default_model = {"anthropic": "claude-sonnet-5-5"}.get(provider, "")
    return Settings(
        provider=provider,
        model=env("REVTRACE_MODEL", default_model),
        api_key=key,
        base_url=env("REVTRACE_BASE_URL", ""),
        embeddings=env("REVTRACE_EMBEDDINGS", "").lower(),
        datasets_dir=Path(env("REVTRACE_DATASETS", str(ROOT / "datasets"))),
        var_dir=Path(env("REVTRACE_VAR", str(ROOT / "var"))),
        default_dataset=env("REVTRACE_DATASET", "dar-confort"),
        sla_response_minutes=int(env("REVTRACE_SLA_MINUTES", "30")),
        min_followups=int(env("REVTRACE_MIN_FOLLOWUPS", "2")),
        max_agent_steps=int(env("REVTRACE_MAX_AGENT_STEPS", "6")),
    )
