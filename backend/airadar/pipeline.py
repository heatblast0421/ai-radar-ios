"""One pipeline run: fetch due sources -> store/dedupe -> score -> group -> AI explanations -> briefing -> export."""
from __future__ import annotations

import json
import logging
import time
from datetime import timedelta
from pathlib import Path

from . import db as dbmod
from .adapters import ADAPTERS
from .config import Config
from .db import jdump, jload
from .export import Exporter
from .http import Http
from .llm.enrich import Enricher
from .llm.provider import LLM
from .rank import group_stories, score_items, score_repos, sync_repo_items
from .store import Store
from .util import first_sentences, iso, now

log = logging.getLogger("airadar.pipeline")


def run_source(store: Store, source, adapter_cls, http: Http, config: Config) -> dict:
    run_id = store.start_run(source.id)
    t0 = time.monotonic()
    try:
        adapter = adapter_cls(source, http, store, config)
        result = adapter.fetch()
        new = updated = 0
        for raw in result.items:
            status, _ = store.upsert_item(raw, source)
            new += status == "new"
            updated += status == "updated"
        store.conn.commit()
        store.finish_run(run_id, source.id, True, result.fetched, new, updated)
        return {"source": source.id, "ok": True, "fetched": result.fetched, "new": new, "updated": updated,
                "not_modified": result.not_modified, "notes": result.notes[:5], "seconds": round(time.monotonic() - t0, 1)}
    except Exception as exc:  # one broken source must never stop the others
        store.conn.rollback()
        log.warning("source %s failed: %s", source.id, exc)
        store.finish_run(run_id, source.id, False, error=f"{type(exc).__name__}: {exc}")
        return {"source": source.id, "ok": False, "error": f"{type(exc).__name__}: {str(exc)[:300]}",
                "seconds": round(time.monotonic() - t0, 1)}


def due_groups(store: Store, config: Config, force: set[str] | None) -> list[str]:
    groups = []
    for group, minutes in config.schedule.items():
        if group == "briefing":
            continue
        if force and ("all" in force or group in force):
            groups.append(group)
        elif not force and store.job_due(group, int(minutes)):
            groups.append(group)
    return groups


def make_briefing(conn, enricher: Enricher | None, exporter_cards_fn) -> dict | None:
    day = now().strftime("%Y-%m-%d")
    if conn.execute("SELECT 1 FROM briefings WHERE day=?", (day,)).fetchone():
        return None
    if now().hour == 0 and now().minute < 30:
        return None
    rows = conn.execute(
        """SELECT * FROM items WHERE sections LIKE '%"pulse"%' AND (story_id IS NULL OR story_id = id)
           AND COALESCE(published_at, discovered_at) >= ? ORDER BY score DESC LIMIT 12""",
        (iso(now() - timedelta(hours=36)),)).fetchall()
    if len(rows) < 3:
        return None
    stories = []
    for r in rows:
        q = conn.execute("SELECT payload FROM explanations WHERE subject_id=? AND level='quick'", (r["id"],)).fetchone()
        summary = (jload(q["payload"], {}) or {}).get("summary") if q else first_sentences(r["content"] or "", 260)
        src = conn.execute("SELECT name FROM sources WHERE id=?", (r["source_id"],)).fetchone()
        stories.append({"id": r["id"], "title": r["title"], "source": src["name"] if src else r["source_id"], "summary": summary or ""})
    payload, kind = None, "auto"
    if enricher is not None and enricher.llm is not None:
        payload = enricher.briefing(stories)
        kind = "ai" if payload else "auto"
    if payload is None:
        payload = {"headline": "Today's top AI developments",
                   "overview": "Assembled automatically from the highest-ranked items of the last 36 hours.",
                   "bullets": [{"text": s["title"], "item_ids": [s["id"]]} for s in stories[:6]], "watch_next": []}
    payload["item_ids"] = [s["id"] for s in stories]
    conn.execute("INSERT OR REPLACE INTO briefings(day, generated_at, kind, payload) VALUES (?,?,?,?)",
                 (day, iso(now()), kind, jdump(payload)))
    conn.commit()
    return {"day": day, "kind": kind}


def run(config: Config, force: set[str] | None = None, skip_fetch: bool = False, skip_llm: bool = False,
        export: bool = True, http: Http | None = None, llm: LLM | None = None) -> dict:
    t0 = time.monotonic()
    Path(config.db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = dbmod.connect(config.db_path)
    store = Store(conn)
    store.sync_sources(config.sources)
    http = http or Http()
    summary: dict = {"started_at": iso(now()), "sources": [], "groups": []}

    if not skip_fetch:
        groups = due_groups(store, config, force)
        summary["groups"] = groups
        for group in groups:
            ok = True
            for source in [s for s in config.sources if s.group == group and s.enabled]:
                adapter_cls = ADAPTERS.get(source.kind)
                if not adapter_cls:
                    summary["sources"].append({"source": source.id, "ok": False, "error": f"no adapter for kind {source.kind}"})
                    continue
                res = run_source(store, source, adapter_cls, http, config)
                ok = ok and res["ok"]
                summary["sources"].append(res)
            store.mark_job(group, ok)

    summary["repos_scored"] = score_repos(conn, config)
    summary["repo_items"] = sync_repo_items(conn, store, config)
    summary["items_scored"] = score_items(conn, config)
    summary["stories_grouped"] = group_stories(conn)

    enricher = None
    if not skip_llm and config.llm_api_key:
        if llm is None:
            try:
                llm = LLM(config.llm_api_key, http, provider=config.llm_provider, model=config.llm_model,
                          base_url=config.llm_base_url)
            except Exception as exc:
                summary["llm_error"] = str(exc)
        if llm is not None:
            enricher = Enricher(conn, llm, config.llm_max_calls_per_run, config.llm_max_calls_per_day,
                                max_tokens_day=int(__import__("os").environ.get("LLM_MAX_TOKENS_PER_DAY", 180000)),
                                sleep=http.sleep)
            summary["llm"] = enricher.run()
            summary["llm"]["provider"] = llm.provider
            summary["llm"]["model"] = llm._model
    elif not config.llm_api_key:
        summary["llm"] = {"stopped": "no LLM key configured (feed uses source text only)"}

    summary["briefing"] = make_briefing(conn, enricher, None)
    if store.job_due("prune", 1440):
        summary["pruned"] = store.prune(int(config.limits.get("max_item_age_days", 45)))
        store.mark_job("prune", True)

    if export:
        summary["export"] = Exporter(conn, config, config.site_dir).build()
        (Path(config.site_dir) / "api" / "v1" / "last_run.json").write_text(json.dumps(summary | {
            "finished_at": iso(now()), "seconds": round(time.monotonic() - t0, 1)}, indent=1))
    summary["seconds"] = round(time.monotonic() - t0, 1)
    conn.close()
    return summary
