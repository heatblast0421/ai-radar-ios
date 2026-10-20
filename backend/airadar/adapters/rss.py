"""RSS / Atom feeds from official blogs and publications (conditional GET with ETag)."""
from __future__ import annotations

import re

import feedparser

from ..util import ago, clean_text, iso, parse_time
from .base import Adapter, AdapterResult, RawItem

# Industry feeds carry deals, sponsored posts and gadget reviews; drop obvious low-value promo.
PROMO_RE = re.compile(
    r"(?i)\b(sponsored|webinar|deal of the day|best deals?|% off|discount|coupon|giveaway|"
    r"black friday|prime day|buying guide|gift guide|review:|hands-on:|promo code)\b"
)


class RssAdapter(Adapter):
    kind = "rss"

    def fetch(self) -> AdapterResult:
        headers = {"Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5"}
        etag, modified = self.store.source_cache_headers(self.source.id)
        if etag:
            headers["If-None-Match"] = etag
        if modified:
            headers["If-Modified-Since"] = modified
        resp = self.http.get(self.source.url, headers=headers)
        if resp.status_code == 304:
            return AdapterResult(not_modified=True, notes=["not modified"])
        self.store.set_source_cache_headers(self.source.id, resp.headers.get("etag"), resp.headers.get("last-modified"))
        return parse_feed(resp.content, self.source.discussion, self.source.group == "rss_industry")


def parse_feed(content: bytes, discussion: bool = False, industry: bool = False, max_age_days: int = 30) -> AdapterResult:
    parsed = feedparser.parse(content)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"unparseable feed: {parsed.bozo_exception}")
    result = AdapterResult(fetched=len(parsed.entries))
    for e in parsed.entries[:60]:
        link = e.get("link") or ""
        title = clean_text(e.get("title"))
        if not link or not title:
            continue
        if industry and PROMO_RE.search(title):
            result.notes.append(f"skipped promo: {title[:60]}")
            continue
        body = ""
        if e.get("content"):
            body = max((c.get("value", "") for c in e["content"]), key=len)
        body = body or e.get("summary") or e.get("description") or ""
        published = parse_time(e.get("published_parsed") or e.get("updated_parsed") or e.get("published"))
        if published and published < ago(days=max_age_days):
            continue  # first fetch of a big feed: skip the archive
        tags = [t.get("term", "") for t in e.get("tags", []) if t.get("term")]
        item = RawItem(
            kind="discussion" if discussion else "article",
            title=title,
            url=link,
            provider_key=None,
            author=clean_text(e.get("author")) or None,
            published_at=iso(published),
            content=clean_text(body, 6000),
            tags=tags[:10],
        )
        if discussion and e.get("comments"):
            item.discussion_url = e.get("comments")
        result.items.append(item)
    return result
