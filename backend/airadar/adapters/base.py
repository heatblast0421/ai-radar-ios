"""Source adapter interface.

An adapter fetches one kind of source and returns RawItems. Adapters never touch ranking or AI;
they only report what the source said, with its URL and timestamps.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config, SourceConfig
    from ..http import Http
    from ..store import Store


@dataclass
class RawItem:
    kind: str                      # article | paper | discussion | release | model | repo
    title: str
    url: str
    provider_key: str | None = None
    author: str | None = None
    published_at: str | None = None
    content: str = ""
    metrics: dict = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    discussion_url: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class AdapterResult:
    items: list[RawItem] = field(default_factory=list)
    fetched: int = 0
    notes: list[str] = field(default_factory=list)
    not_modified: bool = False


class Adapter:
    kind = "base"

    def __init__(self, source: "SourceConfig", http: "Http", store: "Store", config: "Config"):
        self.source = source
        self.http = http
        self.store = store
        self.config = config

    def fetch(self) -> AdapterResult:  # pragma: no cover - interface
        raise NotImplementedError
