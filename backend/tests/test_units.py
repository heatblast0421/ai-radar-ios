from datetime import timedelta

from airadar import db as dbmod
from airadar.adapters.base import RawItem
from airadar.adapters.github import markdown_to_text, release_significance
from airadar.adapters.hackernews import is_ai_story
from airadar.adapters.trending import extract_repo_names
from airadar.llm.enrich import unsupported_numbers
from airadar.llm.provider import detect_provider, parse_json
from airadar.rank import group_stories, repo_growth
from airadar.store import Store
from airadar.topics import classify
from airadar.util import canonical_url, clean_text, iso, now


def test_canonical_url_variants():
    assert canonical_url("http://www.openai.com/index/x/?utm_source=rss&ref=hn") == "https://openai.com/index/x"
    assert canonical_url("https://arxiv.org/pdf/2610.01234v2.pdf") == "https://arxiv.org/abs/2610.01234"
    assert canonical_url("https://huggingface.co/papers/2610.01234") == "https://arxiv.org/abs/2610.01234"
    assert canonical_url("https://github.com/Acme/Agent-Harness/") == "https://github.com/acme/agent-harness"
    assert canonical_url("https://github.com/acme/x/tree/main") == "https://github.com/acme/x"
    assert canonical_url("https://github.com/acme/x/releases/tag/v1") == "https://github.com/acme/x/releases/tag/v1"
    assert canonical_url("https://youtu.be/abc") == "https://youtube.com/watch?v=abc"


def test_clean_text_strips_html():
    assert clean_text("<p>Hello&nbsp;<b>world</b></p><script>x()</script>") == "Hello world"
    assert clean_text("a " * 200, 50).endswith("…")


def test_classifier_topics_and_relevance():
    c = classify("Building an MCP server for coding agents", "tool calling and agent harness")
    assert "mcp" in c.topics and "agents" in c.topics and c.ai_relevance > 0.3
    assert classify("My weekend woodworking project").ai_relevance == 0
    assert classify("Startup raises $40M Series A for AI agents").topics.count("industry") == 1


def test_hn_filter():
    assert is_ai_story("Introducing GPT-7 Mini")
    assert is_ai_story("Show HN: An MCP server for Postgres")
    assert not is_ai_story("My weekend woodworking project")
    assert not is_ai_story("Real estate agent fees explained")


def test_release_significance():
    assert release_significance("v2.0.0") == "major"
    assert release_significance("v0.11.0") == "minor"
    assert release_significance("0.11.2") == "patch"
    assert release_significance("nightly") == "other"


def test_markdown_to_text():
    t = markdown_to_text("# Title\n![img](x.png) See [docs](http://x).\n```py\ncode\n```")
    assert "Title" in t and "docs" in t and "\ncode\n" not in t and "x.png" not in t


def test_trending_extraction():
    html = '<a href="https://github.com/acme/agent-harness">x</a><span> foo/memory-layer </span><a href="https://github.com/features/x">'
    assert extract_repo_names(html) == ["acme/agent-harness", "foo/memory-layer"]
    gh = '<h2 class="h3 lh-condensed"><a href="/acme/agent-harness" data-x="1">acme /</a></h2>'
    assert extract_repo_names(gh, "github") == ["acme/agent-harness"]


def test_unsupported_numbers_flags_invented_figures():
    src = "The model scores 81% on SWE-bench and costs $2 per million tokens."
    assert unsupported_numbers("It scores 81% and runs 3x faster with 95% accuracy", src) == ["3x", "95%"]
    assert unsupported_numbers("Released in 2026 with 3 variants", src) == []


def test_provider_detection_and_json_parsing():
    assert detect_provider("gsk_abc") == "groq"
    assert detect_provider("xai-abc") == "xai"
    assert detect_provider("AIzaabc") == "gemini"
    assert detect_provider("sk-ant-x") == "anthropic"
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Sure! {"a": 2} hope that helps') == {"a": 2}


def _conn(tmp_path):
    return dbmod.connect(tmp_path / "t.db")


def test_migrations_idempotent(tmp_path):
    conn = _conn(tmp_path)
    assert dbmod.migrate(conn) == []
    names = [r[0] for r in conn.execute("SELECT name FROM schema_migrations")]
    assert names == ["001_init.sql", "002_repo_hints.sql"]


def test_repo_growth_never_fabricated(tmp_path):
    conn = _conn(tmp_path)
    store = Store(conn)
    repo = {"full_name": "a/b", "owner": "a", "name": "b", "url": "https://github.com/a/b", "stars": 100, "forks": 1,
            "created_at": iso(now() - timedelta(days=10)), "topics": ["llm"]}
    store.upsert_repo(repo, "search", observed=True)
    g = repo_growth(store.snapshots("a/b"), 100, repo["created_at"])
    assert g["trend_available"] is False and g["stars_24h"] is None and g["stars_7d"] is None
    assert g["avg_stars_per_day_since_creation"] == 10.0  # from GitHub's own creation date, labelled as such
    # Two real measurements 25h apart -> measured growth
    store.add_snapshot("a/b", 160, 2, None, None, at=now() + timedelta(hours=25))
    g = repo_growth(store.snapshots("a/b"), 160, repo["created_at"])
    assert g["trend_available"] and g["stars_24h"] == 60 and g["stars_7d"] is None
    # snapshots closer than 50 minutes are not duplicated
    assert store.add_snapshot("a/b", 161, 2, None, None, at=now() + timedelta(hours=25, minutes=10)) is False


def test_dedup_promotes_official_source(tmp_path, config):
    conn = _conn(tmp_path)
    store = Store(conn)
    store.sync_sources(config.sources)
    hn, openai = config.source("hackernews"), config.source("openai-news")
    raw_hn = RawItem(kind="discussion", title="Introducing GPT-7 Mini", url="https://openai.com/index/gpt-7-mini/",
                     provider_key="hn:1", metrics={"hn_points": 100}, discussion_url="https://news.ycombinator.com/item?id=1")
    s1, id1 = store.upsert_item(raw_hn, hn)
    assert s1 == "new"
    raw_off = RawItem(kind="article", title="Introducing GPT-7 Mini", url="https://openai.com/index/gpt-7-mini?utm_source=x",
                      content="Official text")
    s2, id2 = store.upsert_item(raw_off, openai)
    assert id1 == id2 and s2 == "updated"
    row = conn.execute("SELECT * FROM items WHERE id=?", (id1,)).fetchone()
    assert row["source_id"] == "openai-news" and row["kind"] == "article"
    assert dbmod.jload(row["metrics"])["hn_points"] == 100
    # HN refresh with more points merges into the same item as a mention
    raw_hn.metrics = {"hn_points": 180}
    s3, id3 = store.upsert_item(raw_hn, hn)
    assert id3 == id1
    assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    # unchanged official re-fetch is a no-op
    assert store.upsert_item(raw_off, openai)[0] == "unchanged"


def test_story_grouping(tmp_path, config):
    conn = _conn(tmp_path)
    store = Store(conn)
    store.sync_sources(config.sources)
    store.upsert_item(RawItem(kind="article", title="OpenAI launches GPT-7 Mini for developers", url="https://tc.com/a",
                              published_at=iso(now())), config.source("techcrunch-ai"))
    store.upsert_item(RawItem(kind="article", title="Introducing GPT-7 Mini for developers", url="https://openai.com/b",
                              published_at=iso(now())), config.source("openai-news"))
    store.upsert_item(RawItem(kind="article", title="Unrelated news about databases", url="https://x.com/c",
                              published_at=iso(now())), config.source("techcrunch-ai"))
    conn.commit()
    assert group_stories(conn) == 1
    rows = {r["url"]: r["story_id"] for r in conn.execute("SELECT url, story_id FROM items")}
    primary = conn.execute("SELECT id FROM items WHERE url='https://openai.com/b'").fetchone()[0]
    assert rows["https://tc.com/a"] == primary == rows["https://openai.com/b"]
    assert rows["https://x.com/c"] != primary


def test_security_release_safeguard():
    from airadar.rank import SECURITY_RE
    assert SECURITY_RE.search("Medium — MCP request telemetry: GHSA-xv4x-g8mx-ch56. Provider-native config")
    assert SECURITY_RE.search("Fixes CVE-2026-12345 in the parser")
    assert not SECURITY_RE.search("Faster streaming and new docs")
