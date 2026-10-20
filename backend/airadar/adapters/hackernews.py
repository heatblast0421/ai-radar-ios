"""Hacker News via the official HN Search API (hn.algolia.com, provided by Algolia for Y Combinator).

Fetches stories from the last 48 hours above a points threshold, refreshing points/comments
on every run, and keeps only AI-related stories (deterministic classifier on the title).
"""
from __future__ import annotations

from ..topics import classify
from ..util import ago, clean_text, iso, parse_time
from .base import Adapter, AdapterResult, RawItem

AI_TITLE_TOPICS = {"agents", "mcp", "rag", "inference", "models", "evals", "memory"}


def is_ai_story(title: str, text: str = "") -> bool:
    c = classify(title, "")
    if c.ai_relevance >= 0.4:
        return True
    strong_topics = [t for t in c.topics if t in AI_TITLE_TOPICS and c.topic_hits.get(t, 0) >= 3]
    if strong_topics and classify(title, text).ai_relevance >= 0.07:
        return True
    return bool(strong_topics) and any(t in ("mcp", "rag", "inference", "models") for t in strong_topics)


class HackerNewsAdapter(Adapter):
    kind = "hackernews"

    def fetch(self) -> AdapterResult:
        since = int(ago(hours=48).timestamp())
        min_points = int(self.config.limits.get("hn_min_points", 12))
        result = AdapterResult()
        page = 0
        while page < 4:
            data = self.http.get_json(self.source.url, params={
                "tags": "story",
                "numericFilters": f"created_at_i>{since},points>={min_points}",
                "hitsPerPage": 500,
                "page": page,
            })
            hits = data.get("hits", [])
            result.fetched += len(hits)
            result.items.extend(parse_hits(hits))
            page += 1
            if page >= int(data.get("nbPages", 1)):
                break
        return result


def parse_hits(hits: list[dict]) -> list[RawItem]:
    items = []
    for h in hits:
        title = clean_text(h.get("title") or h.get("story_title"))
        if not title:
            continue
        text = clean_text(h.get("story_text"), 3000)
        if not is_ai_story(title, text):
            continue
        oid = h.get("objectID") or h.get("story_id")
        hn_url = f"https://news.ycombinator.com/item?id={oid}"
        items.append(RawItem(
            kind="discussion",
            title=title,
            url=h.get("url") or hn_url,
            provider_key=f"hn:{oid}",
            author=h.get("author"),
            published_at=iso(parse_time(h.get("created_at_i") or h.get("created_at"))),
            content=text,
            metrics={"hn_points": int(h.get("points") or 0), "hn_comments": int(h.get("num_comments") or 0)},
            discussion_url=hn_url,
        ))
    return items
