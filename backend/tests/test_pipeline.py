"""End-to-end: fake internet -> pipeline -> static JSON API, including failures and LLM caching."""
import json
from datetime import timedelta
from pathlib import Path

from airadar import db as dbmod
from airadar import util
from airadar.llm.provider import LLM
from airadar.pipeline import run


def load(site: Path, rel: str):
    return json.loads((site / "api" / "v1" / rel).read_text())


def test_full_run_without_llm(config, http, web):
    summary = run(config, force={"all"}, http=http)
    site = Path(config.site_dir)
    bad = [s for s in summary["sources"] if not s["ok"]]
    assert bad == [], bad
    health = load(site, "health.json")
    assert health["status"] == "ok"
    meta = load(site, "meta.json")
    assert meta["llm"]["configured"] is False
    assert {s["id"]: s["status"] for s in meta["sources"]}["openai-news"] == "ok"
    assert {s["id"]: s["status"] for s in meta["sources"]}["aws-ml"] == "disabled"

    pulse = load(site, "feed/pulse/top/1.json")
    titles = [c["title"] for c in pulse["items"]]
    # Official launch, corroborated by HN + TechCrunch, is one story with supporting sources
    gpt = [c for c in pulse["items"] if "GPT-7 Mini" in c["title"]]
    assert len(gpt) == 1, titles
    gpt = gpt[0]
    assert gpt["source"]["id"] == "openai-news" and gpt["importance"] == "high"
    assert gpt["metrics"]["hn_points"] == 150
    assert {s["source"] for s in gpt["supporting"]} >= {"Hacker News", "TechCrunch AI"}
    assert gpt["summary_kind"] == "source"
    # Non-AI and promo content is excluded
    assert not any("woodworking" in t for t in titles)
    assert not any("deals" in t.lower() for t in titles)
    # Ordered by score
    scores = [c["score"] for c in pulse["items"]]
    assert scores == sorted(scores, reverse=True)
    latest = load(site, "feed/pulse/latest/1.json")["items"]
    times = [c["published_at"] for c in latest]
    assert times == sorted(times, reverse=True)

    research = load(site, "feed/research/top/1.json")["items"]
    mem = [c for c in research if c["title"].startswith("MemAgent")]
    assert len(mem) == 1 and mem[0]["metrics"]["hf_upvotes"] == 42  # arXiv + HF papers deduped
    assert not any("Quantum" in c["title"] for c in research)
    assert any(c["kind"] == "model" and "Acme-LLM" in c["title"] for c in research)
    assert not any("OldModel" in c["title"] for c in research)

    lab = load(site, "feed/lab/top/1.json")["items"]
    assert any(c["kind"] == "release" and "vllm" in c["title"] for c in lab)
    assert any("RAG" in c["title"] for c in lab)
    industry = load(site, "feed/industry/top/1.json")["items"]
    assert any("AgentCo" in c["title"] for c in industry)

    detail = load(site, f"items/{gpt['id']}.json")
    assert detail["source_text"].startswith("Today we are releasing")
    assert detail["explanation"] is None
    assert detail["score_breakdown"]["safeguard"] == "Official announcement"

    # GitHub radar
    emerging = load(site, "github/emerging/1.json")["items"]
    names = [r["full_name"] for r in emerging]
    assert "acme/agent-harness" in names
    assert "someone/cooking-recipes" not in names  # trending hint but not AI -> not shown
    harness = next(r for r in emerging if r["full_name"] == "acme/agent-harness")
    assert harness["growth"]["trend_available"] is False and harness["growth"]["stars_7d"] is None
    assert harness["growth"]["avg_stars_per_day_since_creation"] == 120.0
    assert {h["label"] for h in harness["spotted_on"]} == {"Trendshift", "GitHub Trending"}
    repo = load(site, f"repos/{harness['file_id']}.json")
    assert len(repo["snapshots"]) == 1 and repo["snapshots"][0]["stars"] == 1200
    assert "MCP" in repo["readme_excerpt"]
    assert load(site, "github/growing/1.json")["items"] == []  # no fabricated trends after one measurement
    # missing curated repo is reported, not fatal
    snap = next(s for s in summary["sources"] if s["source"] == "github-snapshots")
    assert any("gone/renamed-repo" in n for n in snap["notes"])

    search = load(site, "search.json")
    assert any(e["t"] == "repo" and e["title"] == "acme/agent-harness" for e in search["entries"])
    briefing = load(site, "briefing.json")
    assert briefing["available"] and briefing["kind"] == "auto" and briefing["items"]


def test_second_run_tracks_growth_and_respects_schedule(config, http, web):
    run(config, force={"all"}, http=http)
    web.repos["acme/agent-harness"]["stars"] = 1500
    util.set_now(util.now() + timedelta(hours=3))
    summary = run(config, http=http)  # scheduled run: only due groups
    assert "hackernews" in summary["groups"] and "rss_official" in summary["groups"]
    assert "arxiv" not in summary["groups"] and "github_snapshots" not in summary["groups"]
    util.set_now(util.now() + timedelta(hours=4))
    summary = run(config, http=http)
    assert "github_snapshots" in summary["groups"] and "arxiv" in summary["groups"]
    site = Path(config.site_dir)
    growing = load(site, "github/growing/1.json")["items"]
    h = next(r for r in growing if r["full_name"] == "acme/agent-harness")
    assert h["growth"]["trend_available"] and h["growth"]["stars_per_day_measured"] > 0


def test_source_failures_are_isolated(config, http, web):
    web.fail["openai.com"] = 503
    web.fail["export.arxiv.org"] = 500
    summary = run(config, force={"all"}, http=http)
    failed = {s["source"] for s in summary["sources"] if not s["ok"]}
    assert failed == {"openai-news", "arxiv"}
    site = Path(config.site_dir)
    meta = load(site, "meta.json")
    st = {s["id"]: s for s in meta["sources"]}
    assert st["openai-news"]["status"] == "error" and "503" in st["openai-news"]["last_error"]
    assert meta["status"] == "degraded"
    pulse = load(site, "feed/pulse/top/1.json")["items"]
    assert pulse, "feed still published from healthy sources"
    # HN still reports the launch even though the official blog is down
    assert any("GPT-7 Mini" in c["title"] for c in pulse)


def test_llm_explanations_cached_and_grounded(config, http, web):
    config.llm_api_key = "gsk_test"
    llm = LLM("gsk_test", http)
    s1 = run(config, force={"all"}, http=http, llm=llm)
    assert s1["llm"]["quick"] > 0 and s1["llm"]["deep"] >= 1, s1["llm"]
    assert s1["llm"]["model"] == "llama-3.3-70b-versatile"
    site = Path(config.site_dir)
    pulse = load(site, "feed/pulse/top/1.json")["items"]
    gpt = next(c for c in pulse if "GPT-7 Mini" in c["title"])
    assert gpt["summary_kind"] == "ai" and gpt["has_deep"]
    detail = load(site, f"items/{gpt['id']}.json")
    expl = detail["explanation"]
    assert expl["deep"]["evidence"]["evidence_given"] == "None stated"
    assert "99%" in expl["quick_meta"]["warnings"]  # invented number flagged
    assert "AI-generated" in expl["label"]
    briefing = load(site, "briefing.json")
    assert briefing["kind"] == "ai" and all(b["item_ids"] for b in briefing["bullets"])
    assert len(briefing["bullets"]) == 1  # bullet citing a non-existent item was dropped

    calls_before = web.llm_calls
    s2 = run(config, force={"hackernews"}, http=http, llm=LLM("gsk_test", http))
    # Unchanged items are not re-processed (HN points change does not alter content hash of primaries)
    assert web.llm_calls - calls_before <= 2, s2["llm"]


def test_llm_rate_limit_is_graceful(config, http, web):
    config.llm_api_key = "gsk_test"
    web.llm_status = 429
    s = run(config, force={"all"}, http=http, llm=LLM("gsk_test", http))
    assert s["llm"]["quick"] == 0 and "rate limited" in (s["llm"]["stopped"] or "")
    assert web.llm_calls == 1  # stops after the first rate-limit instead of hammering
    site = Path(config.site_dir)
    assert load(site, "feed/pulse/top/1.json")["items"]
    meta = load(site, "meta.json")
    assert meta["llm"]["last_error"]


def test_pagination(config, http, web, tmp_path):
    config.limits["feed_page_size"] = 2
    run(config, force={"all"}, http=http)
    site = Path(config.site_dir)
    p1 = load(site, "feed/pulse/top/1.json")
    assert p1["total_pages"] >= 2 and len(p1["items"]) == 2
    p2 = load(site, "feed/pulse/top/2.json")
    assert not {c["id"] for c in p1["items"]} & {c["id"] for c in p2["items"]}
    assert p1["items"][-1]["score"] >= p2["items"][0]["score"]
    conn = dbmod.connect(config.db_path)
    assert conn.execute("SELECT COUNT(*) FROM repo_snapshots").fetchone()[0] >= 3
    assert all(r[0] for r in conn.execute("SELECT taken_at FROM repo_snapshots"))
