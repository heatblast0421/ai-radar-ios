"""Persistence layer: items (with cross-source dedup), repos + snapshots, releases, source health."""
from __future__ import annotations

import sqlite3
from datetime import timedelta

from .adapters.base import RawItem
from .config import SourceConfig
from .db import jdump, jload
from .topics import classify
from .util import canonical_url, iso, now, parse_time, sha


class Store:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # ------------------------------------------------------------------ sources
    def sync_sources(self, sources: list[SourceConfig]) -> None:
        for s in sources:
            self.conn.execute(
                """INSERT INTO sources(id, name, kind, url, credibility, official, enabled)
                   VALUES (?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET name=excluded.name, kind=excluded.kind, url=excluded.url,
                     credibility=excluded.credibility, official=excluded.official, enabled=excluded.enabled""",
                (s.id, s.name, s.kind, s.url, s.credibility, int(s.official), int(s.enabled)),
            )
        configured = {s.id for s in sources}
        for row in self.conn.execute("SELECT id FROM sources").fetchall():
            if row["id"] not in configured:
                self.conn.execute("UPDATE sources SET enabled=0 WHERE id=?", (row["id"],))
        self.conn.commit()

    def source_cache_headers(self, sid: str) -> tuple[str | None, str | None]:
        row = self.conn.execute("SELECT etag, last_modified FROM sources WHERE id=?", (sid,)).fetchone()
        return (row["etag"], row["last_modified"]) if row else (None, None)

    def set_source_cache_headers(self, sid: str, etag: str | None, modified: str | None) -> None:
        self.conn.execute("UPDATE sources SET etag=?, last_modified=? WHERE id=?", (etag, modified, sid))

    def clear_source_cache_headers(self, sid: str) -> None:
        self.set_source_cache_headers(sid, None, None)

    def start_run(self, sid: str) -> int:
        ts = iso(now())
        self.conn.execute("UPDATE sources SET last_attempt_at=? WHERE id=?", (ts, sid))
        cur = self.conn.execute("INSERT INTO source_runs(source_id, started_at) VALUES (?,?)", (sid, ts))
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, sid: str, ok: bool, fetched: int = 0, new: int = 0, updated: int = 0,
                   error: str | None = None) -> None:
        ts = iso(now())
        self.conn.execute(
            "UPDATE source_runs SET finished_at=?, ok=?, fetched=?, new_items=?, updated_items=?, error=? WHERE id=?",
            (ts, int(ok), fetched, new, updated, (error or "")[:500] or None, run_id),
        )
        if ok:
            self.conn.execute(
                "UPDATE sources SET last_success_at=?, last_error=NULL, consecutive_failures=0, items_last_run=? WHERE id=?",
                (ts, new + updated, sid))
        else:
            self.conn.execute(
                "UPDATE sources SET last_error=?, consecutive_failures=consecutive_failures+1 WHERE id=?",
                ((error or "unknown error")[:500], sid))
        self.conn.commit()

    def credibility(self, sid: str) -> float:
        row = self.conn.execute("SELECT credibility FROM sources WHERE id=?", (sid,)).fetchone()
        return float(row["credibility"]) if row else 0.5

    # ------------------------------------------------------------------ job scheduling
    def job_due(self, job: str, minutes: int) -> bool:
        row = self.conn.execute("SELECT last_run_at FROM job_state WHERE job=?", (job,)).fetchone()
        if not row or not row["last_run_at"]:
            return True
        last = parse_time(row["last_run_at"])
        # small tolerance so a 15-minute cron reliably triggers 15-minute jobs
        return now() - last >= timedelta(minutes=minutes) - timedelta(minutes=2)

    def mark_job(self, job: str, ok: bool, error: str | None = None) -> None:
        ts = iso(now())
        self.conn.execute(
            """INSERT INTO job_state(job, last_run_at, last_ok_at, last_error) VALUES (?,?,?,?)
               ON CONFLICT(job) DO UPDATE SET last_run_at=excluded.last_run_at,
                 last_ok_at=COALESCE(excluded.last_ok_at, job_state.last_ok_at), last_error=excluded.last_error""",
            (job, ts, ts if ok else None, error),
        )
        self.conn.commit()

    # ------------------------------------------------------------------ items
    def find_item(self, provider_key: str | None, canon: str) -> sqlite3.Row | None:
        if provider_key:
            row = self.conn.execute("SELECT * FROM items WHERE provider_key=?", (provider_key,)).fetchone()
            if row:
                return row
            row = self.conn.execute(
                "SELECT i.* FROM item_mentions m JOIN items i ON i.id=m.item_id WHERE json_extract(m.metrics,'$.provider_key')=?",
                (provider_key,)).fetchone()
            if row:
                return row
        if canon:
            return self.conn.execute("SELECT * FROM items WHERE canonical_url=?", (canon,)).fetchone()
        return None

    def upsert_item(self, raw: RawItem, source: SourceConfig) -> tuple[str, str]:
        """Insert or merge an item. Returns (status, item_id) where status is new | updated | unchanged."""
        canon = canonical_url(raw.url)
        ts = iso(now())
        content = raw.content or ""
        chash = sha(raw.title + "\n" + content)
        row = self.find_item(raw.provider_key, canon)
        extra = dict(raw.extra)
        if raw.tags:
            extra["source_tags"] = raw.tags
        if row is None:
            item_id = sha(canon or raw.provider_key or raw.title)
            self.conn.execute(
                """INSERT INTO items(id, kind, title, url, canonical_url, source_id, provider_key, author, published_at,
                     discovered_at, updated_at, content, content_hash, metrics, discussion_url, extra)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item_id, raw.kind, raw.title, raw.url, canon, source.id, raw.provider_key, raw.author,
                 raw.published_at or ts, ts, ts, content, chash, jdump(raw.metrics), raw.discussion_url, jdump(extra)),
            )
            return "new", item_id

        item_id = row["id"]
        metrics = jload(row["metrics"], {}) | raw.metrics
        same_source = row["source_id"] == source.id and (not raw.provider_key or row["provider_key"] in (None, raw.provider_key))
        if same_source:
            changed = (row["content_hash"] != chash) or (jload(row["metrics"], {}) != metrics)
            if not changed:
                return "unchanged", item_id
            self.conn.execute(
                """UPDATE items SET title=?, content=?, content_hash=?, metrics=?, updated_at=?,
                     discussion_url=COALESCE(discussion_url, ?), extra=? WHERE id=?""",
                (raw.title, content or row["content"], chash if content else row["content_hash"], jdump(metrics), ts,
                 raw.discussion_url, jdump(jload(row["extra"], {}) | extra), item_id),
            )
            return "updated", item_id

        # Same story reported by a different source.
        existing_cred = self.credibility(row["source_id"])
        promote = source.credibility > existing_cred and raw.kind != "discussion"
        if promote:
            # The more authoritative source becomes the primary; the previous one becomes a mention.
            self._add_mention(item_id, row["source_id"], row["discussion_url"] or row["url"], row["title"],
                              {"provider_key": row["provider_key"]})
            self.conn.execute(
                """UPDATE items SET kind=?, title=?, url=?, source_id=?, provider_key=?, author=?, published_at=?,
                     content=?, content_hash=?, metrics=?, updated_at=?, extra=? WHERE id=?""",
                (raw.kind, raw.title, raw.url, source.id, raw.provider_key, raw.author or row["author"],
                 raw.published_at or row["published_at"],
                 content if len(content) >= len(row["content"] or "") * 0.5 else row["content"], chash, jdump(metrics), ts,
                 jdump(jload(row["extra"], {}) | extra), item_id),
            )
            return "updated", item_id
        mention_key = raw.discussion_url or raw.url
        before = self.conn.execute("SELECT metrics FROM item_mentions WHERE item_id=? AND url=?", (item_id, mention_key)).fetchone()
        self._add_mention(item_id, source.id, mention_key, raw.title, raw.metrics | {"provider_key": raw.provider_key})
        new_content = row["content"] if (row["content"] or "") else content
        self.conn.execute(
            "UPDATE items SET metrics=?, discussion_url=COALESCE(discussion_url, ?), content=?, updated_at=? WHERE id=?",
            (jdump(metrics), raw.discussion_url, new_content, ts, item_id),
        )
        return ("updated" if before is None or jload(before["metrics"], {}) != raw.metrics | {"provider_key": raw.provider_key}
                else "unchanged"), item_id

    def _add_mention(self, item_id: str, sid: str, url: str, title: str, metrics: dict) -> None:
        self.conn.execute(
            """INSERT INTO item_mentions(item_id, source_id, url, title, metrics, seen_at) VALUES (?,?,?,?,?,?)
               ON CONFLICT(item_id, url) DO UPDATE SET metrics=excluded.metrics, title=excluded.title, seen_at=excluded.seen_at""",
            (item_id, sid, url, title, jdump(metrics), iso(now())),
        )

    def mentions(self, item_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT m.*, s.name AS source_name FROM item_mentions m LEFT JOIN sources s ON s.id=m.source_id WHERE item_id=?",
            (item_id,)).fetchall()

    # ------------------------------------------------------------------ repos
    def upsert_repo(self, repo: dict, discovered_via: str | None, observed: bool) -> str:
        rid = repo["full_name"].lower()
        ts = iso(now())
        row = self.conn.execute("SELECT * FROM repos WHERE id=?", (rid,)).fetchone()
        cls = classify(repo["name"].replace("-", " ").replace("_", " ") + " " + (repo.get("description") or ""),
                       (row["readme_excerpt"] if row else "") or "", repo.get("topics") or [])
        latest = repo.get("latest_release")
        if row is None:
            self.conn.execute(
                """INSERT INTO repos(id, full_name, owner, name, description, language, topics, categories, url, homepage, license,
                     created_at, pushed_at, stars, forks, open_issues, archived, latest_release, first_seen_at, last_checked_at,
                     discovered_via, tracked, ai_relevance)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)""",
                (rid, repo["full_name"], repo["owner"], repo["name"], repo.get("description"), repo.get("language"),
                 jdump(repo.get("topics") or []), jdump(cls.topics), repo["url"], repo.get("homepage"), repo.get("license"),
                 repo.get("created_at"), repo.get("pushed_at"), repo["stars"], repo["forks"], repo.get("open_issues"),
                 int(repo.get("archived", False)), jdump(latest) if latest else None, ts, ts, discovered_via, cls.ai_relevance),
            )
        else:
            self.conn.execute(
                """UPDATE repos SET full_name=?, description=?, language=?, topics=?, categories=?, url=?, homepage=?, license=?,
                     created_at=COALESCE(?, created_at), pushed_at=COALESCE(?, pushed_at), stars=?, forks=?,
                     open_issues=COALESCE(?, open_issues), archived=?, latest_release=COALESCE(?, latest_release),
                     last_checked_at=?, tracked=1, ai_relevance=? WHERE id=?""",
                (repo["full_name"], repo.get("description"), repo.get("language"), jdump(repo.get("topics") or []),
                 jdump(cls.topics), repo["url"], repo.get("homepage"), repo.get("license"), repo.get("created_at"),
                 repo.get("pushed_at"), repo["stars"], repo["forks"], repo.get("open_issues"),
                 int(repo.get("archived", False)), jdump(latest) if latest else None, ts, cls.ai_relevance, rid),
            )
        if observed:
            self.add_snapshot(rid, repo["stars"], repo["forks"], repo.get("open_issues"), repo.get("pushed_at"))
        return rid

    def add_snapshot(self, rid: str, stars: int, forks: int, open_issues, pushed_at, at=None) -> bool:
        at = at or now()
        last = self.conn.execute("SELECT taken_at FROM repo_snapshots WHERE repo_id=? ORDER BY taken_at DESC LIMIT 1",
                                 (rid,)).fetchone()
        if last and at - parse_time(last["taken_at"]) < timedelta(minutes=50):
            return False
        self.conn.execute(
            "INSERT OR IGNORE INTO repo_snapshots(repo_id, taken_at, stars, forks, open_issues, pushed_at) VALUES (?,?,?,?,?,?)",
            (rid, iso(at), stars, forks, open_issues, pushed_at))
        return True

    def queue_repo_candidates(self, names: list[str], via: str, label: str, link: str) -> int:
        """Remember that a site listed these repos (hint only). Returns how many were new to us."""
        ts = iso(now())
        new = 0
        for n in names:
            rid = n.lower()
            row = self.conn.execute("SELECT spotted_on FROM repos WHERE id=?", (rid,)).fetchone()
            hint = {"id": via, "label": label, "link": link, "at": ts}
            if row is None:
                owner, _, name = n.partition("/")
                self.conn.execute(
                    """INSERT INTO repos(id, full_name, owner, name, url, first_seen_at, tracked, discovered_via, spotted_on)
                       VALUES (?,?,?,?,?,?,1,?,?)""", (rid, n, owner, name, f"https://github.com/{n}", ts, via, jdump([hint])))
                new += 1
            else:
                hints = [h for h in jload(row["spotted_on"], []) if h.get("id") != via] + [hint]
                self.conn.execute("UPDATE repos SET spotted_on=? WHERE id=?", (jdump(hints), rid))
        self.conn.commit()
        return new

    def snapshots(self, rid: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM repo_snapshots WHERE repo_id=? ORDER BY taken_at", (rid,)).fetchall()

    def ensure_curated(self, names: list[str]) -> None:
        for n in names:
            self.conn.execute("UPDATE repos SET curated=1 WHERE id=?", (n.lower(),))

    def tracked_repo_names(self, limit: int) -> list[str]:
        curated = [n for n in self.conn.execute("SELECT full_name FROM repos WHERE curated=1 AND tracked=1")]
        rows = self.conn.execute(
            "SELECT full_name FROM repos WHERE tracked=1 AND archived=0 AND curated=0 ORDER BY (last_checked_at IS NULL) DESC, MAX(score, emerging_score) DESC, stars DESC LIMIT ?",
            (max(0, limit - len(curated)),)).fetchall()
        return [r[0] for r in curated] + [r[0] for r in rows]

    def is_untracked(self, full_name: str) -> bool:
        row = self.conn.execute("SELECT tracked FROM repos WHERE id=?", (full_name.lower(),)).fetchone()
        return bool(row) and not row["tracked"]

    def mark_missing_repos(self, names: list[str]) -> None:
        ts = iso(now())
        for n in names:
            rid = n.lower()
            if self.conn.execute("SELECT 1 FROM repos WHERE id=?", (rid,)).fetchone():
                self.conn.execute("UPDATE repos SET tracked=0 WHERE id=?", (rid,))
            else:  # remember the miss so we don't query it every run
                owner, _, name = n.partition("/")
                self.conn.execute(
                    "INSERT INTO repos(id, full_name, owner, name, url, first_seen_at, tracked, discovered_via) VALUES (?,?,?,?,?,?,0,'missing')",
                    (rid, n, owner, name, f"https://github.com/{n}", ts))

    def repos_needing_readme(self, limit: int) -> list[tuple[str, str]]:
        rows = self.conn.execute(
            "SELECT id, full_name FROM repos WHERE readme_hash IS NULL AND tracked=1 ORDER BY emerging_score DESC, stars DESC LIMIT ?",
            (limit,)).fetchall()
        return [(r["id"], r["full_name"]) for r in rows]

    def set_readme(self, rid: str, text: str) -> None:
        self.conn.execute("UPDATE repos SET readme_excerpt=?, readme_hash=? WHERE id=?",
                          (text or None, sha(text) if text else "none", rid))

    def upsert_release(self, rid: str, rel: dict, body: str) -> None:
        self.conn.execute(
            """INSERT INTO repo_releases(repo_id, tag, name, url, published_at, prerelease, body_excerpt) VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(repo_id, tag) DO UPDATE SET name=excluded.name, url=excluded.url, published_at=excluded.published_at,
                 prerelease=excluded.prerelease, body_excerpt=excluded.body_excerpt""",
            (rid, rel.get("tagName"), rel.get("name"), rel.get("url"), rel.get("publishedAt"), int(bool(rel.get("isPrerelease"))),
             body[:3000]))

    def releases(self, rid: str, limit: int = 8) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM repo_releases WHERE repo_id=? ORDER BY published_at DESC LIMIT ?",
                                 (rid, limit)).fetchall()

    # ------------------------------------------------------------------ maintenance
    def prune(self, max_age_days: int) -> int:
        cutoff = iso(now() - timedelta(days=max_age_days))
        rows = self.conn.execute(
            "SELECT id FROM items WHERE COALESCE(published_at, discovered_at) < ? AND discovered_at < ?", (cutoff, cutoff)).fetchall()
        ids = [r["id"] for r in rows]
        for i in ids:
            self.conn.execute("DELETE FROM item_mentions WHERE item_id=?", (i,))
            self.conn.execute("DELETE FROM explanations WHERE subject_id=?", (i,))
            self.conn.execute("DELETE FROM items WHERE id=?", (i,))
        # keep snapshot history, but thin very old snapshots to one per day (still real measurements)
        old = iso(now() - timedelta(days=30))
        self.conn.execute(
            """DELETE FROM repo_snapshots WHERE taken_at < ? AND rowid NOT IN (
                 SELECT MIN(rowid) FROM repo_snapshots WHERE taken_at < ? GROUP BY repo_id, substr(taken_at,1,10))""",
            (old, old))
        self.conn.commit()
        return len(ids)
