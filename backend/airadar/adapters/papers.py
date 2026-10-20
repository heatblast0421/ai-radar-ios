"""Research sources: arXiv API and Hugging Face Daily Papers; Hugging Face trending models."""
from __future__ import annotations

import re

import feedparser

from ..topics import classify
from ..util import ago, clean_text, iso, parse_time
from .base import Adapter, AdapterResult, RawItem

ENGINEERING_TOPICS = {"agents", "mcp", "rag", "memory", "evals", "inference", "infra", "safety", "training"}


class ArxivAdapter(Adapter):
    """arXiv API (https://info.arxiv.org/help/api). Metadata only; abstracts are shown with attribution."""
    kind = "arxiv"

    def fetch(self) -> AdapterResult:
        cats = self.source.options.get("categories") or ["cs.AI", "cs.CL", "cs.LG"]
        query = " OR ".join(f"cat:{c}" for c in cats)
        resp = self.http.get(self.source.url, params={
            "search_query": query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "max_results": int(self.config.limits.get("arxiv_max_results", 150)),
        })
        return parse_arxiv(resp.content)


def parse_arxiv(content: bytes, min_topic_hits: int = 3) -> AdapterResult:
    parsed = feedparser.parse(content)
    result = AdapterResult(fetched=len(parsed.entries))
    for e in parsed.entries:
        title = clean_text(e.get("title")).replace("\n", " ")
        abstract = clean_text(e.get("summary")).replace("\n", " ")
        abs_url = e.get("id") or e.get("link")
        if not title or not abs_url:
            continue
        m = re.search(r"(\d{4}\.\d{4,5})", abs_url)
        if not m:
            continue
        # arXiv publishes hundreds of papers a day; keep the ones about practical AI engineering topics.
        c = classify(title, abstract)
        eng_hits = sum(c.topic_hits.get(t, 0) for t in ENGINEERING_TOPICS)
        if eng_hits < min_topic_hits:
            continue
        authors = [a.get("name") for a in e.get("authors", []) if a.get("name")]
        cats = [t.get("term") for t in e.get("tags", []) if t.get("term")]
        result.items.append(RawItem(
            kind="paper",
            title=title,
            url=f"https://arxiv.org/abs/{m.group(1)}",
            provider_key=f"arxiv:{m.group(1)}",
            author=", ".join(authors[:4]) + (" et al." if len(authors) > 4 else ""),
            published_at=iso(parse_time(e.get("published_parsed") or e.get("published"))),
            content=abstract[:4000],
            tags=cats[:6],
            extra={"arxiv_id": m.group(1), "pdf_url": f"https://arxiv.org/pdf/{m.group(1)}"},
        ))
    return result


class HFPapersAdapter(Adapter):
    """Hugging Face Daily Papers: community-curated trending papers with upvotes."""
    kind = "hf_papers"

    def fetch(self) -> AdapterResult:
        data = self.http.get_json(self.source.url, params={"limit": 100})
        return parse_hf_papers(data)


def parse_hf_papers(data: list[dict]) -> AdapterResult:
    result = AdapterResult(fetched=len(data))
    for entry in data:
        paper = entry.get("paper") or {}
        pid = paper.get("id") or entry.get("id")
        title = clean_text(paper.get("title") or entry.get("title")).replace("\n", " ")
        if not pid or not title:
            continue
        authors = [a.get("name") for a in paper.get("authors", []) if isinstance(a, dict) and a.get("name")]
        summary = clean_text(paper.get("summary") or entry.get("summary"))
        result.items.append(RawItem(
            kind="paper",
            title=title,
            url=f"https://arxiv.org/abs/{pid}",
            provider_key=f"arxiv:{pid}",
            author=", ".join(authors[:4]) + (" et al." if len(authors) > 4 else ""),
            published_at=iso(parse_time(paper.get("publishedAt") or entry.get("publishedAt"))),
            content=summary[:4000],
            metrics={"hf_upvotes": int(paper.get("upvotes") or 0), "hf_comments": int(entry.get("numComments") or 0)},
            discussion_url=f"https://huggingface.co/papers/{pid}",
            tags=list(paper.get("ai_keywords") or [])[:8],
            extra={"arxiv_id": pid, "pdf_url": f"https://arxiv.org/pdf/{pid}",
                   "github_repo": paper.get("githubRepo"), "hf_featured_at": entry.get("publishedAt")},
        ))
    return result


class HFModelsAdapter(Adapter):
    """Hugging Face Hub trending models; only recently created models are reported as releases."""
    kind = "hf_models"

    def fetch(self) -> AdapterResult:
        data = self.http.get_json(self.source.url, params={"sort": "trendingScore", "limit": 60})
        return parse_hf_models(data)


def parse_hf_models(data: list[dict], max_age_days: int = 60) -> AdapterResult:
    result = AdapterResult(fetched=len(data))
    cutoff = ago(days=max_age_days)
    for m in data:
        mid = m.get("id") or m.get("modelId")
        if not mid:
            continue
        created = parse_time(m.get("createdAt"))
        if created and created < cutoff:
            continue  # long-established models trend often; we only want new releases
        org = mid.split("/")[0]
        pipeline = m.get("pipeline_tag") or ""
        tags = [t for t in (m.get("tags") or []) if ":" not in t][:10]
        desc_bits = [f"New model on Hugging Face from {org}."]
        if pipeline:
            desc_bits.append(f"Task: {pipeline.replace('-', ' ')}.")
        if m.get("library_name"):
            desc_bits.append(f"Library: {m['library_name']}.")
        if tags:
            desc_bits.append("Tags: " + ", ".join(tags[:8]) + ".")
        result.items.append(RawItem(
            kind="model",
            title=f"{mid}",
            url=f"https://huggingface.co/{mid}",
            provider_key=f"hf-model:{mid.lower()}",
            author=org,
            published_at=iso(created),
            content=" ".join(desc_bits),
            metrics={"hf_likes": int(m.get("likes") or 0), "hf_downloads": int(m.get("downloads") or 0),
                     "hf_trending": float(m.get("trendingScore") or 0)},
            tags=tags + ([pipeline] if pipeline else []) + ["model", "llm" if "text-generation" in pipeline else pipeline],
            extra={"pipeline_tag": pipeline, "library": m.get("library_name")},
        ))
    return result
