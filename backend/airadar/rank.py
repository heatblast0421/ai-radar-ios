"""Transparent ranking, section assignment, repo growth metrics and story grouping.

Every score is a weighted sum of named signals stored in `score_breakdown`, so the app can show
*why* something ranks where it does. An LLM never decides importance.
"""
from __future__ import annotations

import math
import re
import sqlite3
from collections import defaultdict
from datetime import timedelta

from .config import Config
from .db import jdump, jload
from .topics import classify
from .util import hours_since, iso, now, parse_time, title_tokens

WEIGHTS = {"relevance": 0.28, "freshness": 0.22, "credibility": 0.15, "engagement": 0.22, "significance": 0.13}
PRIORITY_TOPICS = {"agents", "mcp", "rag", "memory", "evals", "inference", "infra", "models", "training", "safety", "devtools"}
ENGINEERING_SECTION_TOPICS = {"agents", "mcp", "rag", "memory", "evals", "inference", "infra", "devtools", "training"}

LAUNCH_RE = re.compile(
    r"(?i)\b(introduc(ing|es)|launch(es|ed|ing)?|releas(e|es|ed|ing)|now available|announc(ing|es|ed)|"
    r"general availability|generally available|open[- ]sourc(e|es|ed|ing)|new model|unveil\w*|debut\w*)\b")
SECURITY_RE = re.compile(
    r"(?i)\b(vulnerabilit(y|ies)|cve-\d{4}-\d+|security (advisory|flaw|issue|incident|update)|prompt injection|"
    r"exploit(ed|s)?|data (leak|breach)|malicious|backdoor|supply[- ]chain attack|ghsa-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4})\b")
BENCH_RE = re.compile(r"(?i)\b(benchmark|leaderboard|state[- ]of[- ]the[- ]art|sota|swe-bench|evaluation)\b")


def _log_norm(value: float, top: float) -> float:
    if value <= 0:
        return 0.0
    return min(1.0, math.log10(value + 1) / math.log10(top + 1))


def freshness(age_hours: float | None, half_life: float) -> float:
    if age_hours is None:
        return 0.3
    return 0.5 ** (age_hours / half_life)


def engagement(metrics: dict, mention_count: int, kind: str) -> tuple[float, dict]:
    signals = {
        "hn_points": _log_norm(metrics.get("hn_points", 0), 800),
        "hn_comments": 0.6 * _log_norm(metrics.get("hn_comments", 0), 500),
        "hf_upvotes": 0.85 * _log_norm(metrics.get("hf_upvotes", 0), 300),
        "hf_likes": 0.8 * _log_norm(metrics.get("hf_likes", 0), 1500),
        "repo_momentum": 0.75 * metrics.get("repo_momentum", 0.0),
    }
    if kind == "release":
        signals["repo_popularity"] = 0.6 * _log_norm(metrics.get("stars", 0), 100000)
    best = max(signals.values()) if signals else 0.0
    multi = min(0.3, 0.12 * mention_count)
    return min(1.0, best + multi), {k: round(v, 3) for k, v in signals.items() if v} | ({"multi_source": round(multi, 3)} if multi else {})


def significance(item: sqlite3.Row, official: bool, metrics: dict, extra: dict) -> tuple[float, str | None]:
    """Rule-based significance. Returns (0..1, safeguard reason or None)."""
    title = item["title"]
    kind = item["kind"]
    if kind == "release":
        rk = extra.get("release_kind")
        if SECURITY_RE.search((item["content"] or "")[:3000]):
            return 0.85, "Security fix in release"
        return {"major": 0.95, "minor": 0.35, "patch": 0.1}.get(rk, 0.25), ("Major framework release" if rk == "major" else None)
    if SECURITY_RE.search(title):
        return 0.85, "Security-related"
    if official and LAUNCH_RE.search(title):
        return 0.8, "Official announcement"
    if kind == "paper" and metrics.get("hf_upvotes", 0) >= 60:
        return 0.55, None
    if kind == "model" and metrics.get("hf_likes", 0) >= 200:
        return 0.6, None
    if official:
        return 0.45, None
    if BENCH_RE.search(title):
        return 0.4, None
    return 0.2, None


def assign_sections(kind: str, topics: list[str], hits: dict, group: str | None, official: bool,
                    metrics: dict, extra: dict, ai_rel: float, significance_hint: str | None = None) -> list[str]:
    s = set()
    eng_strength = sum(hits.get(t, 0) for t in ENGINEERING_SECTION_TOPICS)
    if kind in ("paper", "model"):
        s.add("research")
    elif kind in ("release", "repo"):
        pass  # code and changelogs belong to the Engineering Lab / GitHub Radar
    elif "research" in topics or ("models" in topics and (official or hits.get("models", 0) >= 4)) or (
            "evals" in topics and hits.get("evals", 0) >= 3):
        s.add("research")
    if kind in ("release", "repo"):
        s.add("lab")
    elif kind in ("paper", "model"):
        pass  # Lab favours practical engineering; papers live in Models & Research
    elif eng_strength >= 3 and (group != "rss_industry" or eng_strength >= 6):
        s.add("lab")
    if kind not in ("paper", "model", "release") and (group == "rss_industry" or "industry" in topics):
        s.add("industry")
    # Pulse: everything noteworthy, but not the long tail of papers/patches/minor models.
    pulse_ok = ai_rel >= 0.2 or kind in ("release", "repo")
    if kind == "repo":
        pulse_ok = metrics.get("repo_momentum", 0) >= 0.55
    if kind == "paper":
        eng_paper = sum(hits.get(t, 0) for t in ENGINEERING_SECTION_TOPICS) >= 3
        pulse_ok = (metrics.get("hf_upvotes", 0) >= 15 and eng_paper) or metrics.get("hn_points", 0) >= 40
    if kind == "model":
        pulse_ok = metrics.get("hf_likes", 0) >= 40
    if kind == "release":
        pulse_ok = extra.get("release_kind") == "major" or significance_hint == "security"
    if pulse_ok:
        s.add("pulse")
    return sorted(s)


def score_items(conn: sqlite3.Connection, config: Config) -> int:
    """Re-classify and re-score all recent items. Cheap: pure Python over a few thousand rows."""
    src = {s.id: s for s in config.sources}
    cutoff = iso(now() - timedelta(days=int(config.limits.get("max_item_age_days", 45))))
    mention_counts = dict(conn.execute("SELECT item_id, COUNT(*) FROM item_mentions GROUP BY item_id").fetchall())
    mention_sources = defaultdict(set)
    for r in conn.execute("SELECT item_id, source_id FROM item_mentions"):
        mention_sources[r[0]].add(r[1])
    rows = conn.execute("SELECT * FROM items WHERE COALESCE(published_at, discovered_at) >= ?", (cutoff,)).fetchall()
    newest_release: dict[str, str] = {}
    for it in rows:
        if it["kind"] == "release":
            repo = jload(it["extra"], {}).get("repo", "")
            if (it["published_at"] or "") > newest_release.get(repo, ""):
                newest_release[repo] = it["published_at"] or ""
    n = 0
    for it in rows:
        sc = src.get(it["source_id"])
        official = bool(sc and sc.official)
        group = sc.group if sc else None
        metrics = jload(it["metrics"], {})
        extra = jload(it["extra"], {})
        tags = list(extra.get("source_tags", []))
        cls = classify(it["title"], it["content"] or "", tags)
        ai_rel = cls.ai_relevance
        if it["kind"] in ("paper", "model", "release", "repo") or (sc and sc.options.get("ai_native")):
            ai_rel = max(ai_rel, 0.6)
        topic_strength = min(1.0, sum(v for k, v in cls.topic_hits.items() if k in PRIORITY_TOPICS) / 8)
        relevance = 0.6 * ai_rel + 0.4 * topic_strength
        age = hours_since(it["published_at"] or it["discovered_at"])
        # A published date far in the past but newly discovered (e.g. a feed backfill) still decays by publish time.
        half_life = {"paper": 60, "release": 40, "model": 48, "repo": 72}.get(it["kind"], 30)
        fresh = freshness(age, half_life)
        cred = sc.credibility if sc else 0.5
        # Corroboration by a more credible mention raises credibility.
        for ms in mention_sources.get(it["id"], ()):
            if ms in src:
                cred = max(cred, src[ms].credibility * 0.95)
        eng, eng_detail = engagement(metrics, mention_counts.get(it["id"], 0), it["kind"])
        sig, safeguard = significance(it, official, metrics, extra)
        parts = {"relevance": relevance, "freshness": fresh, "credibility": cred, "engagement": eng, "significance": sig}
        score = 100 * sum(WEIGHTS[k] * v for k, v in parts.items())
        if ai_rel < 0.15:
            score *= 0.4  # probably not about AI
        importance, reason = None, None
        if safeguard and age is not None and age <= 96 and ai_rel >= 0.3:
            # Safeguard: important official launches / security news surface even without community buzz.
            score = max(score, 64.0)
            importance, reason = "high", safeguard
        elif score >= 76 and it["kind"] not in ("release", "repo"):
            importance, reason = "high", "High combined score"
        elif score >= 62:
            importance, reason = "notable", "Above-average combined score"
        trending = 100 * (0.75 * eng + 0.25 * min(1.0, mention_counts.get(it["id"], 0) / 3)) * (0.5 ** ((age or 48) / 20))
        sections = assign_sections(it["kind"], cls.topics, cls.topic_hits, group, official, metrics, extra, ai_rel,
                                   "security" if safeguard in ("Security-related", "Security fix in release") else None)
        if ai_rel < 0.15:
            sections = [s for s in sections if s not in ("pulse", "lab", "industry")]
        if it["kind"] == "release" and (it["published_at"] or "") < newest_release.get(extra.get("repo", ""), ""):
            sections = []  # older releases stay on the repository page, not in feeds
        if it["kind"] == "release" and extra.get("release_kind") == "patch" and safeguard is None:
            sections = []  # routine patch releases stay on the repo page; security fixes still surface
        breakdown = {k: round(v, 3) for k, v in parts.items()} | {
            "weights": WEIGHTS, "engagement_signals": eng_detail, "safeguard": safeguard,
            "ai_relevance": round(ai_rel, 3), "topic_hits": cls.topic_hits,
        }
        conn.execute(
            """UPDATE items SET topics=?, sections=?, ai_relevance=?, score=?, trending_score=?, score_breakdown=?,
                 importance=?, importance_reason=? WHERE id=?""",
            (jdump(cls.topics), jdump(sections), ai_rel, round(score, 2), round(trending, 2), jdump(breakdown),
             importance, reason, it["id"]))
        n += 1
    conn.commit()
    return n


# ---------------------------------------------------------------------------- repositories

def repo_growth(snapshots: list[sqlite3.Row], stars_now: int, created_at: str | None) -> dict:
    """Growth figures computed strictly from recorded snapshots (plus GitHub's own creation date)."""
    out: dict = {"snapshots_count": len(snapshots), "trend_available": False,
                 "tracking_since": snapshots[0]["taken_at"] if snapshots else None,
                 "stars_24h": None, "stars_7d": None, "stars_per_day_measured": None, "measured_window_hours": None}
    if created_at:
        age_days = max(1.0, (hours_since(created_at) or 24) / 24)
        out["avg_stars_per_day_since_creation"] = round(stars_now / age_days, 1)
        out["age_days"] = round(age_days, 1)
    if len(snapshots) >= 2:
        last = snapshots[-1]
        t_last = parse_time(last["taken_at"])
        first = snapshots[0]
        span_h = (t_last - parse_time(first["taken_at"])).total_seconds() / 3600
        if span_h >= 5:
            out["trend_available"] = True
            out["measured_window_hours"] = round(span_h, 1)
            out["stars_per_day_measured"] = round((last["stars"] - first["stars"]) / (span_h / 24), 1)

        def delta(hours: float, tolerance: float):
            target = t_last - timedelta(hours=hours)
            best = None
            for s in snapshots[:-1]:
                t = parse_time(s["taken_at"])
                if t <= target + timedelta(hours=tolerance):
                    best = s
            if best is None:
                return None
            if (t_last - parse_time(best["taken_at"])).total_seconds() / 3600 < hours - tolerance:
                return None
            return last["stars"] - best["stars"]

        out["stars_24h"] = delta(24, 4)
        out["stars_7d"] = delta(24 * 7, 12)
    return out


def score_repos(conn: sqlite3.Connection, config: Config) -> int:
    rows = conn.execute("SELECT * FROM repos WHERE tracked=1").fetchall()
    for r in rows:
        if r["last_checked_at"] is None:
            continue
        snaps = conn.execute("SELECT * FROM repo_snapshots WHERE repo_id=? ORDER BY taken_at", (r["id"],)).fetchall()
        g = repo_growth(snaps, r["stars"], r["created_at"])
        cats = jload(r["categories"], [])
        weak = r["ai_relevance"] < 0.1 and not cats
        hint_only = r["discovered_via"] not in ("search", "curated") and r["ai_relevance"] < 0.3
        if not r["curated"] and (weak or hint_only):
            conn.execute("UPDATE repos SET tracked=0 WHERE id=?", (r["id"],))  # not AI; stop measuring
            continue
        rel = min(1.0, 0.5 + 0.5 * min(1.0, r["ai_relevance"] + 0.2 * len(cats)))
        age_days = g.get("age_days") or 9999
        pushed_age_d = (hours_since(r["pushed_at"]) or 9999) / 24
        activity = 1.0 if pushed_age_d <= 3 else 0.8 if pushed_age_d <= 14 else 0.5 if pushed_age_d <= 60 else 0.2
        measured = g["stars_per_day_measured"] or 0
        since_creation = g.get("avg_stars_per_day_since_creation") or 0
        velocity = max(measured, since_creation * (0.8 if age_days <= 120 else 0.0))
        momentum = _log_norm(velocity, 400)
        newness = 1.0 if age_days <= 30 else 0.75 if age_days <= 90 else 0.45 if age_days <= 365 else 0.2
        emerging = 100 * momentum * (0.55 + 0.45 * newness) * activity * rel
        popularity = _log_norm(r["stars"], 150000)
        score = 100 * (0.35 * momentum + 0.25 * popularity + 0.2 * activity + 0.2 * rel)
        breakdown = {"momentum": round(momentum, 3), "velocity_stars_per_day": velocity, "newness": newness,
                     "activity": activity, "relevance": round(rel, 3), "popularity": round(popularity, 3), "growth": g}
        conn.execute("UPDATE repos SET score=?, emerging_score=?, score_breakdown=? WHERE id=?",
                     (round(score, 2), round(emerging, 2), jdump(breakdown), r["id"]))
    conn.commit()
    return len(rows)


def sync_repo_items(conn: sqlite3.Connection, store, config: Config, max_items: int = 40) -> int:
    """Promising emerging repos also appear in the main feeds as 'repo' items."""
    from .adapters.base import RawItem

    sc = config.source("github-discovery")
    if sc is None:
        return 0
    rows = conn.execute(
        """SELECT * FROM repos WHERE tracked=1 AND archived=0 AND emerging_score >= 35 AND created_at >= ?
           ORDER BY emerging_score DESC LIMIT ?""", (iso(now() - timedelta(days=90)), max_items)).fetchall()
    for r in rows:
        bd = jload(r["score_breakdown"], {})
        desc = r["description"] or ""
        readme = (r["readme_excerpt"] or "")[:3000]
        store.upsert_item(RawItem(
            kind="repo", title=f"{r['full_name']}" + (f": {desc[:120]}" if desc else ""), url=r["url"],
            provider_key=f"gh:{r['id']}", author=r["owner"], published_at=r["created_at"],
            content=(desc + "\n\n" + readme).strip(),
            metrics={"stars": r["stars"], "forks": r["forks"], "repo_momentum": round(bd.get("momentum", 0), 3)},
            tags=jload(r["topics"], []), extra={"repo": r["full_name"], "repo_id": r["id"]},
        ), sc)
    conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------- story grouping

_MODEL_TOKEN = re.compile(r"[a-z]+-?\d[\w\.\-]*|\d+[a-z][\w\.\-]*")


def group_stories(conn: sqlite3.Connection, window_days: int = 5) -> int:
    """Cluster items describing the same news (similar titles, shared model/version names) into stories."""
    cutoff = iso(now() - timedelta(days=window_days))
    rows = conn.execute(
        """SELECT i.id, i.title, i.kind, i.score, i.published_at, i.discovered_at, s.credibility
           FROM items i LEFT JOIN sources s ON s.id=i.source_id
           WHERE COALESCE(i.published_at, i.discovered_at) >= ? AND i.kind NOT IN ('repo','model')""", (cutoff,)).fetchall()
    toks = {r["id"]: title_tokens(r["title"]) for r in rows}
    parent = {r["id"]: r["id"] for r in rows}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    index = defaultdict(list)
    for r in rows:
        for t in toks[r["id"]]:
            index[t].append(r["id"])
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        a = r["id"]
        cand = defaultdict(int)
        for t in toks[a]:
            if len(index[t]) > 60:  # very common token, not informative
                continue
            for b in index[t]:
                if b != a:
                    cand[b] += 1
        ta = toks[a]
        for b, shared in cand.items():
            if shared < 2:
                continue
            tb = toks[b]
            jac = shared / max(1, len(ta | tb))
            models_a = {t for t in ta if _MODEL_TOKEN.fullmatch(t)}
            shared_model = models_a & tb
            ra, rb = r, by_id[b]
            ta_t = parse_time(ra["published_at"] or ra["discovered_at"])
            tb_t = parse_time(rb["published_at"] or rb["discovered_at"])
            close = ta_t and tb_t and abs((ta_t - tb_t).total_seconds()) <= 72 * 3600
            if ra["kind"] == "paper" or rb["kind"] == "paper":
                ok = jac >= 0.75
            else:
                ok = (jac >= 0.5 and shared >= 3) or (bool(shared_model) and shared >= 2 and close and jac >= 0.3)
            if ok:
                parent[find(a)] = find(b)
    groups = defaultdict(list)
    for r in rows:
        groups[find(r["id"])].append(r)
    grouped = 0
    for members in groups.values():
        primary = max(members, key=lambda m: ((m["credibility"] or 0.5), m["score"] or 0))
        for m in members:
            conn.execute("UPDATE items SET story_id=? WHERE id=?", (primary["id"], m["id"]))
        if len(members) > 1:
            grouped += 1
    # Items outside the window keep/obtain their own story id.
    conn.execute("UPDATE items SET story_id=id WHERE story_id IS NULL")
    conn.commit()
    return grouped
