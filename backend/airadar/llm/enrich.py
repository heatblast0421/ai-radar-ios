"""AI explanations (three levels) with strict grounding, caching and budget limits.

- Explanations are generated ONLY from the verified source text we stored.
- Cached per item and regenerated only when the source content hash or prompt version changes.
- Numbers in AI text that do not appear in the source are flagged as warnings for the app.
- Rate limits / outages stop AI work for this run; the feed still publishes with source text.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import timedelta

from ..db import jdump, jload
from ..util import iso, now, sha
from .provider import LLM, LLMUnavailable

log = logging.getLogger("airadar.enrich")

PROMPT_VERSION = "v1"

GROUNDING_RULES = """You explain AI news for a smart reader who is NOT a programmer, then add technical depth for engineers.
Rules you must follow:
- Use ONLY the source material provided. Do not add facts, numbers, benchmark results, dates, prices, features or names that are not in it.
- If the source does not say something, write "Not stated in the source." rather than guessing.
- Plain language first; when you use a technical term, explain it briefly.
- Never claim something is important just because it is new; describe what the source actually supports.
- Output must be a single valid JSON object matching the requested shape. No markdown fences."""

QUICK_SHAPE = """Return JSON: {"items": [{"id": "<id as given>", "summary": "<= 2 plain sentences, max 55 words, what it is and what happened>",
"why_it_matters": "<1 sentence for an AI engineer; 'Not stated in the source.' if unclear>",
"key_terms": [{"term": "<jargon used>", "meaning": "<short plain explanation>"}],
"source_is_thin": <true if the source text is too short to say much>}]}
key_terms: at most 3, only terms that appear in the source."""

DEEP_SHAPE = """Return JSON with exactly these keys:
{"plain_explanation": "<3-5 sentences in simple language>",
 "how_it_works": "<how the technology/approach works, based on the source>",
 "what_changed": "<what is new compared with before, per the source>",
 "why_it_matters": "<why an AI engineer should care>",
 "comparison": "<how it relates to existing approaches. If the source gives no comparison, start with 'General context:' and keep it high-level without numbers>",
 "strengths": ["..."], "limitations": ["... include limitations the source admits and obvious open questions"],
 "use_cases": ["..."],
 "evidence": {"claims": ["<key claims the source makes>"], "evidence_given": "<what evidence the source provides: code, paper, benchmark tables, demos, or 'None stated'>",
              "unverified": ["<claims the reader should verify independently>"]},
 "explore": {"experiments": ["<small hands-on experiments to try>"], "implementation_ideas": ["<practical project ideas>"],
             "questions": ["<questions worth investigating next>"], "search_terms": ["<search phrases to learn more>"]},
 "glossary": [{"term": "...", "meaning": "..."}]}
Lists: 2-5 short items each."""

_NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(%|x|×|k|K|M|B|billion|million)?(?![\w])")


def unsupported_numbers(ai_text: str, source_text: str) -> list[str]:
    """Numbers in the AI text (>=11 or with a unit) that never appear in the source."""
    src_nums = {m.group(1).replace(",", "") for m in _NUM_RE.finditer(source_text)}
    flagged = []
    for m in _NUM_RE.finditer(ai_text):
        num, unit = m.group(1).replace(",", ""), m.group(2)
        try:
            val = float(num)
        except ValueError:
            continue
        if not unit and val <= 10:
            continue
        if 1900 <= val <= 2100 and not unit:
            continue  # years are usually fine context; still listed only if absent and unit-less? skip
        if num not in src_nums:
            flagged.append(m.group(0).strip())
    return sorted(set(flagged))[:8]


def _flatten(obj) -> str:
    if isinstance(obj, dict):
        return " ".join(_flatten(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(_flatten(v) for v in obj)
    return str(obj)


class Enricher:
    def __init__(self, conn: sqlite3.Connection, llm: LLM | None, max_calls: int, max_calls_day: int,
                 max_tokens_day: int = 180_000, pace_seconds: float = 6.0, sleep=None):
        self.conn = conn
        self.llm = llm
        self.max_calls = max_calls
        self.max_calls_day = max_calls_day
        self.max_tokens_day = max_tokens_day
        self.pace = pace_seconds
        self.calls = 0
        self.stopped_reason: str | None = None
        import time
        self.sleep = sleep or time.sleep

    # ---------------------------------------------------------------- budget
    def _budget_ok(self) -> bool:
        if self.llm is None or self.stopped_reason:
            return False
        if self.calls >= self.max_calls:
            self.stopped_reason = "per-run budget reached"
            return False
        day = iso(now() - timedelta(hours=24))
        calls, tokens = self.conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(COALESCE(input_tokens,0)+COALESCE(output_tokens,0)),0) FROM llm_usage WHERE at>=?",
            (day,)).fetchone()
        if calls >= self.max_calls_day or tokens >= self.max_tokens_day:
            self.stopped_reason = "daily budget reached"
            return False
        return True

    def _call(self, purpose: str, system: str, user: str, max_tokens: int) -> dict | None:
        if not self._budget_ok():
            return None
        if self.calls:
            self.sleep(self.pace)
        self.calls += 1
        try:
            resp = self.llm.json_call(system, user, max_tokens=max_tokens)
            self._log(purpose, True, resp.input_tokens, resp.output_tokens, None)
            return resp.data
        except LLMUnavailable as exc:
            self._log(purpose, False, None, None, str(exc))
            self.stopped_reason = str(exc)[:200]
            log.warning("LLM unavailable, continuing without AI text: %s", exc)
            return None
        except Exception as exc:  # malformed output etc. — skip this unit of work only
            self._log(purpose, False, None, None, str(exc))
            log.warning("LLM call failed (%s): %s", purpose, exc)
            return None

    def _log(self, purpose, ok, tin, tout, err):
        self.conn.execute(
            "INSERT INTO llm_usage(at, provider, model, purpose, ok, input_tokens, output_tokens, error) VALUES (?,?,?,?,?,?,?,?)",
            (iso(now()), self.llm.provider, self.llm.model if self.llm._model else "?", purpose, int(ok), tin, tout,
             (err or "")[:300] or None))
        self.conn.commit()

    # ---------------------------------------------------------------- cache
    def _cached(self, subject: str, level: str, chash: str) -> bool:
        row = self.conn.execute("SELECT content_hash, prompt_version FROM explanations WHERE subject_id=? AND level=?",
                                (subject, level)).fetchone()
        return bool(row) and row["content_hash"] == chash and row["prompt_version"] == PROMPT_VERSION

    def _save(self, subject, level, chash, payload, warnings):
        self.conn.execute(
            """INSERT INTO explanations(subject_id, level, content_hash, prompt_version, provider, model, payload, warnings, created_at)
               VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(subject_id, level) DO UPDATE SET content_hash=excluded.content_hash,
               prompt_version=excluded.prompt_version, provider=excluded.provider, model=excluded.model, payload=excluded.payload,
               warnings=excluded.warnings, created_at=excluded.created_at""",
            (subject, level, chash, PROMPT_VERSION, self.llm.provider, self.llm.model, jdump(payload), jdump(warnings), iso(now())))
        self.conn.commit()

    # ---------------------------------------------------------------- work selection
    @staticmethod
    def _source_block(it: sqlite3.Row, limit: int) -> str:
        meta = jload(it["metrics"], {})
        lines = [f"Title: {it['title']}", f"Type: {it['kind']}", f"URL: {it['url']}"]
        if it["published_at"]:
            lines.append(f"Published: {it['published_at'][:10]}")
        if meta:
            lines.append("Metrics: " + ", ".join(f"{k}={v}" for k, v in meta.items() if k != "repo_momentum"))
        body = (it["content"] or "").strip()
        lines.append("Source text:\n" + (body[:limit] if body else "(no text provided beyond the title)"))
        return "\n".join(lines)

    def quick_candidates(self, limit: int) -> list[sqlite3.Row]:
        rows = self.conn.execute(
            """SELECT * FROM items WHERE sections != '[]' AND score >= 38 AND (story_id IS NULL OR story_id = id)
               AND discovered_at >= ? ORDER BY score DESC LIMIT 300""", (iso(now() - timedelta(days=7)),)).fetchall()
        out = []
        for r in rows:
            if not self._cached(r["id"], "quick", r["content_hash"] or ""):
                out.append(r)
            if len(out) >= limit:
                break
        return out

    def deep_candidates(self, limit: int) -> list[sqlite3.Row]:
        rows = self.conn.execute(
            """SELECT * FROM items WHERE sections != '[]' AND (importance IS NOT NULL OR score >= 52)
               AND (story_id IS NULL OR story_id = id) AND LENGTH(COALESCE(content,'')) >= 280 AND discovered_at >= ?
               ORDER BY (importance='high') DESC, score DESC LIMIT 120""", (iso(now() - timedelta(days=4)),)).fetchall()
        out = []
        for r in rows:
            if not self._cached(r["id"], "deep", r["content_hash"] or ""):
                out.append(r)
            if len(out) >= limit:
                break
        return out

    # ---------------------------------------------------------------- generation
    def run(self, quick_batches: int = 6, batch_size: int = 6, deep_items: int = 4) -> dict:
        stats = {"quick": 0, "deep": 0, "calls": 0, "stopped": None}
        if self.llm is None:
            stats["stopped"] = "no LLM key configured"
            return stats
        # Deep explanations first for the most important items, interleaved with quick batches.
        deep = self.deep_candidates(deep_items)
        quick = self.quick_candidates(quick_batches * batch_size)
        batches = [quick[i:i + batch_size] for i in range(0, len(quick), batch_size)]
        work = []
        for i in range(max(len(deep), len(batches))):
            if i < len(batches):
                work.append(("quick", batches[i]))
            if i < len(deep):
                work.append(("deep", deep[i]))
        for kind, payload in work:
            if not self._budget_ok():
                break
            if kind == "quick":
                stats["quick"] += self.quick_batch(payload)
            else:
                stats["deep"] += self.deep_one(payload)
        stats["calls"] = self.calls
        stats["stopped"] = self.stopped_reason
        return stats

    def quick_batch(self, rows: list[sqlite3.Row]) -> int:
        blocks = "\n\n".join(f"### id: {r['id']}\n{self._source_block(r, 2200)}" for r in rows)
        user = f"Summarize each item below.\n{QUICK_SHAPE}\n\n{blocks}"
        data = self._call("quick", GROUNDING_RULES, user, max_tokens=220 * len(rows) + 300)
        if not data:
            return 0
        by_id = {r["id"]: r for r in rows}
        n = 0
        for entry in data.get("items", []) if isinstance(data, dict) else []:
            r = by_id.get(str(entry.get("id")))
            if not r or not entry.get("summary"):
                continue
            payload = {
                "summary": str(entry.get("summary", "")).strip()[:600],
                "why_it_matters": str(entry.get("why_it_matters", "")).strip()[:400],
                "key_terms": [kt for kt in (entry.get("key_terms") or []) if isinstance(kt, dict)][:3],
                "source_is_thin": bool(entry.get("source_is_thin")),
            }
            warnings = unsupported_numbers(_flatten(payload), r["title"] + " " + (r["content"] or "") + " " + r["metrics"])
            self._save(r["id"], "quick", r["content_hash"] or "", payload, warnings)
            n += 1
        return n

    def deep_one(self, r: sqlite3.Row) -> int:
        user = f"Explain this item in depth.\n{DEEP_SHAPE}\n\n{self._source_block(r, 6000)}"
        data = self._call("deep", GROUNDING_RULES, user, max_tokens=1800)
        if not isinstance(data, dict) or not data.get("plain_explanation"):
            return 0
        keys = ["plain_explanation", "how_it_works", "what_changed", "why_it_matters", "comparison", "strengths",
                "limitations", "use_cases", "evidence", "explore", "glossary"]
        payload = {k: data.get(k) for k in keys if data.get(k) is not None}
        warnings = unsupported_numbers(_flatten(payload), r["title"] + " " + (r["content"] or "") + " " + r["metrics"])
        self._save(r["id"], "deep", r["content_hash"] or "", payload, warnings)
        # A deep explanation also implies a quick summary if missing.
        if not self._cached(r["id"], "quick", r["content_hash"] or ""):
            quick = {"summary": str(payload.get("plain_explanation", ""))[:400],
                     "why_it_matters": str(payload.get("why_it_matters", ""))[:300], "key_terms": (payload.get("glossary") or [])[:3],
                     "source_is_thin": False}
            self._save(r["id"], "quick", r["content_hash"] or "", quick, warnings)
        return 1

    # ---------------------------------------------------------------- briefing
    def briefing(self, stories: list[dict]) -> dict | None:
        if not stories:
            return None
        lines = []
        for s in stories:
            lines.append(f"- id: {s['id']} | {s['title']} | source: {s['source']} | {s.get('summary','')[:300]}")
        user = ("Write today's AI briefing from ONLY these items. Return JSON: {\"headline\": \"<max 12 words>\", "
                "\"overview\": \"<2-3 plain sentences>\", \"bullets\": [{\"text\": \"<1-2 sentences>\", \"item_ids\": [\"<ids from the list>\"]}], "
                "\"watch_next\": [\"<1-3 things worth watching, grounded in the items>\"]}. 4-7 bullets, most important first.\n\n"
                + "\n".join(lines))
        data = self._call("briefing", GROUNDING_RULES, user, max_tokens=1200)
        if not isinstance(data, dict) or not data.get("bullets"):
            return None
        valid = {s["id"] for s in stories}
        bullets = []
        for b in data.get("bullets", []):
            if not isinstance(b, dict) or not b.get("text"):
                continue
            ids = [i for i in (b.get("item_ids") or []) if i in valid]
            if ids:  # every bullet must cite at least one real item
                bullets.append({"text": str(b["text"])[:500], "item_ids": ids})
        if not bullets:
            return None
        return {"headline": str(data.get("headline", "Today in AI"))[:120], "overview": str(data.get("overview", ""))[:700],
                "bullets": bullets[:7], "watch_next": [str(w)[:200] for w in (data.get("watch_next") or [])][:3]}


def explanation_for(conn: sqlite3.Connection, subject: str) -> dict | None:
    rows = conn.execute("SELECT * FROM explanations WHERE subject_id=?", (subject,)).fetchall()
    if not rows:
        return None
    out: dict = {"label": "AI-generated interpretation of the source above. May contain mistakes; verify important details."}
    for r in rows:
        out[r["level"]] = jload(r["payload"], {})
        out[f"{r['level']}_meta"] = {"provider": r["provider"], "model": r["model"], "generated_at": r["created_at"],
                                     "warnings": jload(r["warnings"], [])}
    return out


def content_signature(text: str) -> str:
    return sha(text or "")


__all__ = ["Enricher", "explanation_for", "unsupported_numbers", "PROMPT_VERSION", "json"]
