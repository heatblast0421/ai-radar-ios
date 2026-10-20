"""Loads config/sources.toml and environment settings."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config" / "sources.toml"


@dataclass
class SourceConfig:
    id: str
    name: str
    kind: str
    group: str
    url: str
    credibility: float = 0.5
    official: bool = False
    discussion: bool = False
    enabled: bool = True
    options: dict = field(default_factory=dict)


@dataclass
class Config:
    schedule: dict[str, int]
    limits: dict[str, int]
    sources: list[SourceConfig]
    github: dict
    # environment
    github_token: str | None = None
    llm_api_key: str | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_base_url: str | None = None
    llm_max_calls_per_run: int | None = None   # None = provider default (see llm.provider.DEFAULT_BUDGETS)
    llm_max_calls_per_day: int | None = None
    db_path: str = "data/radar.db"
    site_dir: str = "site"
    public_base_url: str = ""
    disabled_sources: set[str] = field(default_factory=set)

    def source(self, sid: str) -> SourceConfig | None:
        return next((s for s in self.sources if s.id == sid), None)


def load(path: str | Path | None = None, env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    data = tomllib.loads(Path(path or env.get("AIRADAR_CONFIG") or DEFAULT_CONFIG).read_text())
    disabled = {s.strip() for s in env.get("AIRADAR_DISABLED_SOURCES", "").split(",") if s.strip()}
    sources = []
    known = {"id", "name", "kind", "group", "url", "credibility", "official", "discussion", "enabled"}
    for raw in data["catalog"]["sources"]:
        sc = SourceConfig(
            id=raw["id"], name=raw["name"], kind=raw["kind"], group=raw["group"], url=raw["url"],
            credibility=float(raw.get("credibility", 0.5)), official=bool(raw.get("official", False)),
            discussion=bool(raw.get("discussion", False)),
            enabled=bool(raw.get("enabled", True)) and raw["id"] not in disabled,
            options={k: v for k, v in raw.items() if k not in known},
        )
        sources.append(sc)

    def _int(name, default):
        try:
            value = env.get(name)
            return int(value) if value not in (None, "") else default
        except (TypeError, ValueError):
            return default

    return Config(
        schedule=data.get("schedule", {}),
        limits=data.get("limits", {}),
        sources=sources,
        github=data.get("github", {}),
        github_token=env.get("GITHUB_TOKEN") or env.get("GH_TOKEN") or None,
        llm_api_key=(env.get("LLM_API_KEY") or env.get("GROQ_API_KEY") or env.get("XAI_API_KEY")
                     or env.get("GEMINI_API_KEY") or env.get("ANTHROPIC_API_KEY") or env.get("OPENAI_API_KEY") or None),
        llm_provider=env.get("LLM_PROVIDER") or None,
        llm_model=env.get("LLM_MODEL") or None,
        llm_base_url=env.get("LLM_BASE_URL") or None,
        llm_max_calls_per_run=_int("LLM_MAX_CALLS_PER_RUN", None),
        llm_max_calls_per_day=_int("LLM_MAX_CALLS_PER_DAY", None),
        db_path=env.get("AIRADAR_DB", "data/radar.db"),
        site_dir=env.get("AIRADAR_SITE_DIR", "site"),
        public_base_url=env.get("AIRADAR_PUBLIC_BASE_URL", ""),
        disabled_sources=disabled,
    )
