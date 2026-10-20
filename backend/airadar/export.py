"""Builds the static JSON API the iPhone app reads (published to GitHub Pages).

Layout (all under /api/v1/):
  health.json, meta.json, briefing.json, search.json
  feed/{pulse|research|lab|industry}/{top|latest|trending}/{page}.json
  github/{emerging|growing|stars|new|releases}/{page}.json
  items/{id}.json      full detail incl. verified source text + AI explanation
  repos/{owner__name}.json
"""
from __future__ import annotations

import json
import math
import shutil
import sqlite3
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

from .config import Config
from .db import jload
from .llm.enrich import explanation_for
from .topics import topics_payload
from .util import first_sentences, iso, now, parse_time

API_VERSION = 1
SECTIONS = ("pulse", "research", "lab", "industry")
SORTS = ("top", "latest", "trending")
SECTION_INFO = {
    "pulse": "Home / AI Pulse: the most important AI developments across all sources.",
    "research": "Models & Research: model releases, papers, benchmarks and research announcements.",
    "lab": "Engineering Lab: agents, MCP, RAG, memory, evals, inference, infrastructure, framework releases.",
    "industry": "AI Industry: startups, funding, launches, products and industry changes.",
}
GROUP_LABEL = {
    "rss_official": "Official announcements", "rss_engineering": "Engineering writing", "rss_industry": "Industry news",
    "hackernews": "Developer community", "arxiv": "Research papers", "hf_papers": "Research papers",
    "hf_models": "Model releases", "github_discovery": "GitHub", "github_snapshots": "GitHub",
    "github_releases": "Framework releases", "trending_pages": "Discovery hints",
}


def repo_file_id(rid: str) -> str:
    return rid.replace("/", "__")


class Exporter:
    def __init__(self, conn: sqlite3.Connection, config: Config, out_dir: str | Path):
        self.conn = conn
        self.config = config
        self.root = Path(out_dir)
        self.api = self.root / "api" / "v1"
        self.sources = {r["id"]: r for r in conn.execute("SELECT * FROM sources")}
        self.src_cfg = {s.id: s for s in config.sources}
        self.page_size = int(config.limits.get("feed_page_size", 30))
        self.max_items = int(config.limits.get("feed_max_items", 360))
        self._expl_cache: dict[str, dict | None] = {}

    # ------------------------------------------------------------------ helpers
    def write(self, rel: str, data) -> None:
        path = self.api / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))

    def explanation(self, subject: str) -> dict | None:
        if subject not in self._expl_cache:
            self._expl_cache[subject] = explanation_for(self.conn, subject)
        return self._expl_cache[subject]

    def source_ref(self, sid: str) -> dict:
        s = self.sources.get(sid)
        cfg = self.src_cfg.get(sid)
        return {"id": sid, "name": s["name"] if s else sid, "credibility": s["credibility"] if s else 0.5,
                "official": bool(s["official"]) if s else False, "group": GROUP_LABEL.get(cfg.group, "") if cfg else ""}

    # ------------------------------------------------------------------ cards
    def card(self, it: sqlite3.Row, members: list[sqlite3.Row] | None = None) -> dict:
        expl = self.explanation(it["id"]) or {}
        quick = expl.get("quick")
        content = it["content"] or ""
        if quick and quick.get("summary"):
            summary, summary_kind = quick["summary"], "ai"
        elif content:
            summary, summary_kind = first_sentences(content, 260), "source"
        else:
            summary, summary_kind = "", "none"
        extra = jload(it["extra"], {})
        metrics = {k: v for k, v in jload(it["metrics"], {}).items() if k != "repo_momentum"}
        supporting = []
        for m in members or []:
            if m["id"] == it["id"]:
                continue
            supporting.append({"title": m["title"], "url": m["url"], "source": self.source_ref(m["source_id"])["name"],
                               "item_id": m["id"], "published_at": m["published_at"]})
        for mn in self.conn.execute("SELECT * FROM item_mentions WHERE item_id=?", (it["id"],)):
            supporting.append({"title": mn["title"], "url": mn["url"], "source": self.source_ref(mn["source_id"])["name"],
                               "item_id": None, "published_at": None})
        bd = jload(it["score_breakdown"], {})
        story_score = it["score"] + min(8, 3 * len(supporting))
        return {
            "id": it["id"],
            "kind": it["kind"],
            "title": it["title"],
            "summary": summary,
            "summary_kind": summary_kind,
            "why_it_matters": (quick or {}).get("why_it_matters"),
            "url": it["url"],
            "discussion_url": it["discussion_url"],
            "source": self.source_ref(it["source_id"]),
            "author": it["author"],
            "published_at": it["published_at"],
            "discovered_at": it["discovered_at"],
            "updated_at": it["updated_at"],
            "topics": jload(it["topics"], []),
            "sections": jload(it["sections"], []),
            "score": round(story_score, 1),
            "trending_score": it["trending_score"],
            "importance": it["importance"],
            "importance_reason": it["importance_reason"],
            "score_parts": {k: bd.get(k) for k in ("relevance", "freshness", "credibility", "engagement", "significance")},
            "metrics": metrics,
            "supporting": supporting[:8],
            "has_deep": bool(expl.get("deep")),
            "repo": extra.get("repo"),
            "release_kind": extra.get("release_kind"),
        }

    # ------------------------------------------------------------------ feeds
    def build(self) -> dict:
        if self.api.exists():
            shutil.rmtree(self.api)
        self.api.mkdir(parents=True)
        cutoff = iso(now() - timedelta(days=int(self.config.limits.get("max_item_age_days", 45))))
        rows = self.conn.execute(
            "SELECT * FROM items WHERE sections != '[]' AND COALESCE(published_at, discovered_at) >= ?", (cutoff,)).fetchall()
        by_story = defaultdict(list)
        for r in rows:
            by_story[r["story_id"] or r["id"]].append(r)
        primaries = [r for r in rows if (r["story_id"] or r["id"]) == r["id"]]
        cards = {r["id"]: self.card(r, by_story.get(r["id"])) for r in primaries}
        counts = {}
        for section in SECTIONS:
            sec_cards = [c for c in cards.values() if section in c["sections"]]
            counts[section] = len(sec_cards)
            orders = {
                "top": diversify(sorted(sec_cards, key=lambda c: (-c["score"], c["title"]))),
                "latest": sorted(sec_cards, key=lambda c: c["published_at"] or c["discovered_at"], reverse=True),
                "trending": sorted([c for c in sec_cards if (c["trending_score"] or 0) > 0.5],
                                   key=lambda c: -(c["trending_score"] or 0)),
            }
            for sort, lst in orders.items():
                self._paged(f"feed/{section}/{sort}", lst[: self.max_items], {"section": section, "sort": sort,
                                                                              "description": SECTION_INFO[section]})
        for r in primaries:
            self.write(f"items/{r['id']}.json", self.item_detail(r, cards[r["id"]], by_story.get(r["id"], [])))
        # Non-primary story members get detail files too (linked from "supporting").
        for r in rows:
            if r["id"] not in cards:
                self.write(f"items/{r['id']}.json", self.item_detail(r, self.card(r), []))
        repo_counts = self.build_github()
        self.build_search(list(cards.values()))
        briefing = self.build_briefing(cards)
        meta = self.build_meta(counts | repo_counts, briefing)
        self.write("health.json", {"status": meta["status"], "generated_at": meta["generated_at"], "api_version": API_VERSION})
        (self.root / "index.html").write_text(
            "<!doctype html><meta charset=utf-8><title>AI Radar API</title><body style='font-family:system-ui;padding:2rem'>"
            "<h1>AI Radar</h1><p>Static data API for the AI Radar iPhone app. Start at "
            "<a href='api/v1/meta.json'>api/v1/meta.json</a>.</p>")
        (self.root / ".nojekyll").write_text("")
        return {"items": len(cards), **counts, **repo_counts}

    def _paged(self, prefix: str, items: list, header: dict) -> None:
        total = len(items)
        pages = max(1, math.ceil(total / self.page_size))
        for p in range(pages):
            chunk = items[p * self.page_size:(p + 1) * self.page_size]
            self.write(f"{prefix}/{p + 1}.json", header | {"page": p + 1, "total_pages": pages, "total": total,
                                                            "generated_at": iso(now()), "items": chunk})

    # ------------------------------------------------------------------ item detail
    def item_detail(self, it: sqlite3.Row, card: dict, members: list[sqlite3.Row]) -> dict:
        extra = jload(it["extra"], {})
        links = []
        if extra.get("pdf_url"):
            links.append({"title": "Paper PDF (arXiv)", "url": extra["pdf_url"], "kind": "paper"})
        if it["discussion_url"] and it["discussion_url"] != it["url"]:
            links.append({"title": "Discussion", "url": it["discussion_url"], "kind": "discussion"})
        if extra.get("github_repo"):
            links.append({"title": "Code on GitHub", "url": extra["github_repo"], "kind": "repo"})
        if extra.get("repo_url"):
            links.append({"title": "Repository", "url": extra["repo_url"], "kind": "repo"})
        expl = self.explanation(it["id"])
        return card | {
            "source_text": (it["content"] or "")[:4000],
            "source_text_note": "Excerpt from the original source, shown for verification. Read the full original via the link.",
            "links": links,
            "explanation": expl,
            "score_breakdown": jload(it["score_breakdown"], {}),
            "related": self.related(it),
            "related_repos": self.related_repos(it),
        }

    def related(self, it: sqlite3.Row, limit: int = 5) -> list[dict]:
        topics = jload(it["topics"], [])
        if not topics:
            return []
        rows = self.conn.execute(
            """SELECT id, title, url, source_id, kind, published_at, topics FROM items
               WHERE id != ? AND (story_id IS NULL OR story_id = id) AND sections != '[]'
               AND discovered_at >= ? ORDER BY score DESC LIMIT 400""",
            (it["id"], iso(now() - timedelta(days=21)))).fetchall()
        scored = []
        tset = set(topics)
        for r in rows:
            overlap = len(tset & set(jload(r["topics"], [])))
            if overlap >= min(2, len(tset)):
                scored.append((overlap, r))
        scored.sort(key=lambda x: -x[0])
        return [{"id": r["id"], "title": r["title"], "url": r["url"], "kind": r["kind"],
                 "source": self.source_ref(r["source_id"])["name"], "published_at": r["published_at"]}
                for _, r in scored[:limit]]

    def related_repos(self, it: sqlite3.Row, limit: int = 4) -> list[dict]:
        topics = set(jload(it["topics"], []))
        if not topics:
            return []
        rows = self.conn.execute(
            "SELECT id, full_name, description, stars, url, categories FROM repos WHERE tracked=1 AND archived=0 "
            "AND last_checked_at IS NOT NULL ORDER BY score DESC LIMIT 300").fetchall()
        out = []
        for r in rows:
            if len(topics & set(jload(r["categories"], []))) >= min(2, len(topics)) and r["id"] != jload(it["extra"], {}).get("repo_id"):
                out.append({"id": r["id"], "full_name": r["full_name"], "description": r["description"],
                            "stars": r["stars"], "url": r["url"]})
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------ github
    def repo_card(self, r: sqlite3.Row) -> dict:
        bd = jload(r["score_breakdown"], {})
        growth = bd.get("growth") or {}
        item = self.conn.execute("SELECT id FROM items WHERE provider_key=? OR canonical_url=?",
                                 (f"gh:{r['id']}", f"https://github.com/{r['id']}")).fetchone()
        expl = self.explanation(item["id"]) if item else None
        quick = (expl or {}).get("quick") or {}
        return {
            "id": r["id"], "file_id": repo_file_id(r["id"]), "full_name": r["full_name"], "owner": r["owner"], "name": r["name"],
            "description": r["description"], "ai_summary": quick.get("summary"), "language": r["language"],
            "stars": r["stars"], "forks": r["forks"], "open_issues": r["open_issues"],
            "created_at": r["created_at"], "pushed_at": r["pushed_at"], "first_seen_at": r["first_seen_at"],
            "last_checked_at": r["last_checked_at"],
            "latest_release": jload(r["latest_release"]), "topics": jload(r["topics"], []),
            "categories": jload(r["categories"], []), "url": r["url"], "homepage": r["homepage"], "license": r["license"],
            "score": r["score"], "emerging_score": r["emerging_score"], "curated": bool(r["curated"]),
            "growth": {
                "trend_available": bool(growth.get("trend_available")),
                "stars_day": growth.get("stars_24h"), "stars_week": growth.get("stars_7d"),
                "stars_per_day_measured": growth.get("stars_per_day_measured"),
                "measured_window_hours": growth.get("measured_window_hours"),
                "avg_stars_per_day_since_creation": growth.get("avg_stars_per_day_since_creation"),
                "tracking_since": growth.get("tracking_since"), "snapshots_count": growth.get("snapshots_count", 0),
            },
            "spotted_on": [{"label": h.get("label"), "link": h.get("link"), "at": h.get("at")} for h in jload(r["spotted_on"], [])],
            "item_id": item["id"] if item else None,
        }

    def build_github(self) -> dict:
        rows = self.conn.execute(
            """SELECT * FROM repos WHERE tracked=1 AND archived=0 AND last_checked_at IS NOT NULL
               AND (ai_relevance >= 0.1 OR categories != '[]' OR curated=1)""").fetchall()
        cards = [self.repo_card(r) for r in rows]
        recent = iso(now() - timedelta(days=90))

        def rel_date(c):
            lr = c.get("latest_release") or {}
            return lr.get("published_at") or ""

        orders = {
            "emerging": sorted([c for c in cards if (c["created_at"] or "") >= recent], key=lambda c: -c["emerging_score"]),
            "growing": sorted([c for c in cards if c["growth"]["trend_available"]],
                              key=lambda c: -(c["growth"]["stars_week"] if c["growth"]["stars_week"] is not None
                                              else (c["growth"]["stars_per_day_measured"] or 0) * 7)),
            "stars": sorted(cards, key=lambda c: -c["stars"]),
            "new": sorted([c for c in cards if (c["created_at"] or "") >= recent], key=lambda c: c["created_at"] or "", reverse=True),
            "releases": sorted([c for c in cards if rel_date(c)], key=rel_date, reverse=True),
        }
        info = {
            "emerging": "Repositories created in the last 90 days, ranked by measured momentum (stars per day), activity and AI relevance.",
            "growing": "Largest measured star gains from our own snapshots. Repos appear here once we have at least two measurements.",
            "stars": "Most-starred tracked AI repositories.",
            "new": "Newest AI repositories we are tracking.",
            "releases": "Tracked repositories ordered by their latest GitHub release.",
        }
        for sort, lst in orders.items():
            self._paged(f"github/{sort}", lst[:300], {"sort": sort, "description": info[sort]})
        for r, c in zip(rows, cards):
            snaps = self.conn.execute("SELECT taken_at, stars, forks FROM repo_snapshots WHERE repo_id=? ORDER BY taken_at",
                                      (r["id"],)).fetchall()
            rels = self.conn.execute(
                "SELECT tag, name, url, published_at, prerelease, body_excerpt FROM repo_releases WHERE repo_id=? ORDER BY published_at DESC LIMIT 6",
                (r["id"],)).fetchall()
            expl = self.explanation(c["item_id"]) if c["item_id"] else None
            self.write(f"repos/{c['file_id']}.json", c | {
                "readme_excerpt": (r["readme_excerpt"] or "")[:2500],
                "snapshots": [{"t": s["taken_at"], "stars": s["stars"], "forks": s["forks"]} for s in snaps][-400:],
                "releases": [dict(x) for x in rels],
                "explanation": expl,
                "score_breakdown": jload(r["score_breakdown"], {}),
            })
        return {"repos": len(cards)}

    # ------------------------------------------------------------------ search, briefing, meta
    def build_search(self, cards: list[dict]) -> None:
        entries = [{"id": c["id"], "t": "item", "kind": c["kind"], "title": c["title"], "summary": (c["summary"] or "")[:220],
                    "topics": c["topics"], "sections": c["sections"], "source": c["source"]["name"], "url": c["url"],
                    "published_at": c["published_at"], "score": c["score"]} for c in cards]
        for r in self.conn.execute(
                "SELECT id, full_name, description, categories, url, created_at, score, stars FROM repos WHERE tracked=1 "
                "AND last_checked_at IS NOT NULL AND (ai_relevance >= 0.1 OR categories != '[]' OR curated=1)"):
            entries.append({"id": r["id"], "t": "repo", "kind": "repo", "title": r["full_name"],
                            "summary": (r["description"] or "")[:220], "topics": jload(r["categories"], []),
                            "sections": ["github"], "source": "GitHub", "url": r["url"], "published_at": r["created_at"],
                            "score": r["score"], "stars": r["stars"]})
        entries.sort(key=lambda e: -(e["score"] or 0))
        self.write("search.json", {"generated_at": iso(now()), "count": len(entries), "entries": entries[:5000]})

    def build_briefing(self, cards: dict) -> dict | None:
        row = self.conn.execute("SELECT * FROM briefings ORDER BY day DESC LIMIT 1").fetchone()
        if not row:
            data = {"available": False, "message": "The first daily briefing is generated after the first full day of data."}
            self.write("briefing.json", data)
            return None
        payload = jload(row["payload"], {})
        items = [cards[i] for i in payload.get("item_ids", []) if i in cards]
        data = {"available": True, "day": row["day"], "generated_at": row["generated_at"], "kind": row["kind"],
                "label": ("AI-written summary of the linked items. Check the sources for details." if row["kind"] == "ai"
                          else "Automatically assembled from today's top-ranked items (no AI)."),
                **{k: v for k, v in payload.items() if k != "item_ids"}, "items": items}
        self.write("briefing.json", data)
        return data

    def build_meta(self, counts: dict, briefing: dict | None) -> dict:
        srcs = []
        failing = 0
        item_counts = dict(self.conn.execute("SELECT source_id, COUNT(*) FROM items GROUP BY source_id").fetchall())
        for s in self.config.sources:
            row = self.sources.get(s.id)
            status = "disabled" if not s.enabled else "pending"
            if row is not None and s.enabled:
                if row["last_error"] and (not row["last_success_at"] or row["consecutive_failures"] > 0):
                    status = "error"
                    failing += 1
                elif row["last_success_at"]:
                    status = "ok"
            srcs.append({"id": s.id, "name": s.name, "kind": s.kind, "group": GROUP_LABEL.get(s.group, s.group),
                         "url": s.url, "status": status, "credibility": s.credibility, "official": s.official,
                         "last_success_at": row["last_success_at"] if row else None,
                         "last_attempt_at": row["last_attempt_at"] if row else None,
                         "last_error": (row["last_error"] if row and status == "error" else None),
                         "items": item_counts.get(s.id, 0), "refresh_minutes": self.config.schedule.get(s.group)})
        day = iso(now() - timedelta(hours=24))
        usage = self.conn.execute(
            "SELECT COUNT(*) AS calls, SUM(ok) AS ok, MAX(at) AS last, MAX(model) AS model, MAX(provider) AS provider FROM llm_usage WHERE at>=?",
            (day,)).fetchone()
        last_err = self.conn.execute("SELECT error, at FROM llm_usage WHERE ok=0 ORDER BY at DESC LIMIT 1").fetchone()
        expl_count = self.conn.execute("SELECT COUNT(*) FROM explanations").fetchone()[0]
        llm = {"configured": bool(self.config.llm_api_key), "provider": usage["provider"], "model": usage["model"],
               "calls_day": usage["calls"] or 0, "successful_day": usage["ok"] or 0, "last_call_at": usage["last"],
               "last_error": (last_err["error"] if last_err else None), "last_error_at": (last_err["at"] if last_err else None),
               "explanations_cached": expl_count}
        enabled = sum(1 for s in srcs if s["status"] != "disabled")
        status = "ok" if failing == 0 else ("degraded" if failing < enabled else "down")
        meta = {"api_version": API_VERSION, "generated_at": iso(now()), "status": status, "counts": counts,
                "sources": srcs, "failing_sources": failing, "topics": topics_payload(), "schedule": self.config.schedule,
                "llm": llm, "briefing_day": briefing.get("day") if briefing else None,
                "sections": [{"id": k, "description": v} for k, v in SECTION_INFO.items()],
                "notes": ["Growth numbers are computed only from snapshots AI Radar recorded itself.",
                          "Rankings are rule-based and explained in each item's score breakdown; AI never decides importance.",
                          "Trendshift and GitHub Trending are used only to discover repositories; their rankings are not republished."]}
        self.write("meta.json", meta)
        return meta


def diversify(cards: list[dict], penalty: float = 2.5) -> list[dict]:
    """Keep the ranked order but stop one kind (e.g. repos or papers) from filling the top of a feed:
    each further item of the same kind is ranked as if its score were `penalty` points lower per predecessor."""
    remaining = list(cards)
    out: list[dict] = []
    seen: dict[str, int] = {}
    while remaining:
        best_i = max(range(min(len(remaining), 40)),
                     key=lambda i: remaining[i]["score"] - penalty * seen.get(remaining[i]["kind"], 0))
        card = remaining.pop(best_i)
        seen[card["kind"]] = seen.get(card["kind"], 0) + 1
        out.append(card)
    return out


def latest_briefing_day(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT day FROM briefings ORDER BY day DESC LIMIT 1").fetchone()
    return row["day"] if row else None


__all__ = ["Exporter", "repo_file_id", "latest_briefing_day", "parse_time"]
