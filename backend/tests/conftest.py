"""Test fixtures: a fake internet (httpx.MockTransport) that mimics every source's real response format."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from airadar import config as cfgmod  # noqa: E402
from airadar import util  # noqa: E402
from airadar.http import Http  # noqa: E402

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def rfc822(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


def isoz(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def rss(items: list[dict]) -> str:
    body = "".join(
        f"<item><title>{i['title']}</title><link>{i['link']}</link><pubDate>{rfc822(i['date'])}</pubDate>"
        f"<description><![CDATA[{i.get('desc', '')}]]></description></item>" for i in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><link>https://x</link>{body}</channel></rss>'


def atom(entries: list[dict]) -> str:
    body = "".join(
        f"<entry><title>{e['title']}</title><link href=\"{e['link']}\"/><id>{e['link']}</id>"
        f"<updated>{isoz(e['date'])}</updated><published>{isoz(e['date'])}</published>"
        f"<summary>{e.get('desc', '')}</summary>"
        + "".join(f"<author><name>{a}</name></author>" for a in e.get("authors", []))
        + "".join(f'<category term="{c}"/>' for c in e.get("cats", []))
        + "</entry>" for e in entries)
    return f'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>{body}</feed>'


class FakeWeb:
    """Routes requests to canned responses. `fail` makes chosen hosts return errors."""

    def __init__(self):
        self.fail: dict[str, int] = {}
        self.calls: list[str] = []
        self.llm_calls = 0
        self.llm_status = 200
        self.hn_points = 150
        self.repos = {
            "acme/agent-harness": dict(stars=1200, forks=80, created=NOW - timedelta(days=10),
                                       desc="A lightweight agent harness for coding agents with MCP tool calling",
                                       topics=["ai-agents", "mcp", "llm"]),
            "vllm-project/vllm": dict(stars=60000, forks=9000, created=NOW - timedelta(days=1100),
                                      desc="A high-throughput and memory-efficient inference and serving engine for LLMs",
                                      topics=["llm", "inference"]),
            "foo/memory-layer": dict(stars=300, forks=10, created=NOW - timedelta(days=20),
                                     desc="Long-term agent memory layer for LLM apps", topics=["ai-memory", "rag"]),
            "someone/cooking-recipes": dict(stars=900, forks=5, created=NOW - timedelta(days=5),
                                            desc="My favourite recipes", topics=["food"]),
        }

    # ---------------------------------------------------------------- handlers
    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        host = request.url.host
        self.calls.append(url)
        if host in self.fail:
            return httpx.Response(self.fail[host], text="boom")
        if host == "openai.com":
            return httpx.Response(200, text=rss([
                {"title": "Introducing GPT-7 Mini", "link": "https://openai.com/index/introducing-gpt-7-mini/?utm_source=rss",
                 "date": NOW - timedelta(hours=5),
                 "desc": "<p>Today we are releasing GPT-7 Mini, a small reasoning model for developers. It scores 81% on SWE-bench Verified "
                         "and supports tool calling and structured outputs in the API. Developers can use it through the Responses API "
                         "with a 400K token context window. We trained it with reinforcement learning on agentic coding tasks, and it is "
                         "available today to all paid tiers.</p>"},
                {"title": "Our approach to AI safety research", "link": "https://openai.com/index/safety-approach/",
                 "date": NOW - timedelta(days=3), "desc": "We describe how we evaluate frontier models for safety risks."},
            ]), headers={"etag": '"v1"'})
        if host == "simonwillison.net":
            return httpx.Response(200, text=atom([
                {"title": "Notes on building a coding agent harness with MCP", "link": "https://simonwillison.net/2026/Oct/20/agent-harness/",
                 "date": NOW - timedelta(hours=3),
                 "desc": "I tried a new agent harness that wires tool calling through MCP servers. Here are notes on context management and evals."},
            ]))
        if host == "techcrunch.com":
            return httpx.Response(200, text=rss([
                {"title": "AgentCo raises $40M Series A to build AI agents for finance", "link": "https://techcrunch.com/2026/10/20/agentco-raises/",
                 "date": NOW - timedelta(hours=8), "desc": "AgentCo, an AI startup, raised $40 million in funding."},
                {"title": "Best deals on AI laptops this week", "link": "https://techcrunch.com/deals/", "date": NOW - timedelta(hours=2)},
                {"title": "OpenAI launches GPT-7 Mini for developers", "link": "https://techcrunch.com/2026/10/20/openai-gpt-7-mini/",
                 "date": NOW - timedelta(hours=4), "desc": "OpenAI released GPT-7 Mini, a small reasoning model."},
            ]))
        if host == "hn.algolia.com":
            return httpx.Response(200, json={"nbPages": 1, "hits": [
                {"objectID": "4001", "title": "Introducing GPT-7 Mini", "url": "https://openai.com/index/introducing-gpt-7-mini/",
                 "author": "pg", "points": self.hn_points, "num_comments": 90, "created_at_i": int((NOW - timedelta(hours=4)).timestamp())},
                {"objectID": "4002", "title": "Show HN: Agent-harness – a tiny harness for coding agents", "url": "https://github.com/acme/agent-harness",
                 "author": "dev", "points": 220, "num_comments": 40, "created_at_i": int((NOW - timedelta(hours=10)).timestamp())},
                {"objectID": "4003", "title": "My weekend woodworking project", "url": "https://example.com/wood",
                 "author": "x", "points": 300, "num_comments": 10, "created_at_i": int((NOW - timedelta(hours=6)).timestamp())},
                {"objectID": "4004", "title": "Ask HN: How do you evaluate RAG pipelines in production?", "url": None,
                 "story_text": "We run retrieval augmented generation over docs; how do you measure retrieval quality?",
                 "author": "y", "points": 45, "num_comments": 30, "created_at_i": int((NOW - timedelta(hours=7)).timestamp())},
            ]})
        if host == "export.arxiv.org":
            return httpx.Response(200, text=atom([
                {"title": "MemAgent: Long-Term Memory for LLM Agents via Retrieval", "link": "http://arxiv.org/abs/2610.01234v1",
                 "date": NOW - timedelta(days=1), "authors": ["A. Researcher", "B. Scientist"], "cats": ["cs.CL", "cs.AI"],
                 "desc": "We propose MemAgent, an agent memory architecture combining retrieval and summarization for long-horizon "
                         "LLM agents. On our benchmark it improves task success by 12 points."},
                {"title": "Quantum Effects in Superconducting Materials", "link": "http://arxiv.org/abs/2610.09999v1",
                 "date": NOW - timedelta(days=1), "authors": ["C"], "cats": ["cs.LG"], "desc": "Physics without AI engineering topics."},
            ]))
        if host == "huggingface.co" and request.url.path == "/api/daily_papers":
            return httpx.Response(200, json=[{"paper": {"id": "2610.01234", "title": "MemAgent: Long-Term Memory for LLM Agents via Retrieval",
                                                        "summary": "We propose MemAgent, an agent memory architecture.", "upvotes": 42,
                                                        "authors": [{"name": "A. Researcher"}], "publishedAt": isoz(NOW - timedelta(days=1)),
                                                        "githubRepo": "https://github.com/foo/memory-layer"},
                                              "publishedAt": isoz(NOW - timedelta(hours=20)), "numComments": 3}])
        if host == "huggingface.co" and request.url.path == "/api/models":
            return httpx.Response(200, json=[
                {"id": "acme-ai/Acme-LLM-8B-Instruct", "likes": 250, "downloads": 5000, "trendingScore": 90,
                 "pipeline_tag": "text-generation", "library_name": "transformers", "createdAt": isoz(NOW - timedelta(days=4)),
                 "tags": ["transformers", "text-generation", "license:apache-2.0"]},
                {"id": "old/OldModel", "likes": 9000, "createdAt": isoz(NOW - timedelta(days=700)), "pipeline_tag": "text-generation"},
            ])
        if host == "trendshift.io":
            return httpx.Response(200, text='<div><a href="https://github.com/acme/agent-harness">x</a>'
                                            '<span>someone/cooking-recipes</span><a href="/repositories/1">foo/memory-layer</a></div>')
        if host == "github.com" and request.url.path.startswith("/trending"):
            return httpx.Response(200, text='<article><h2 class="h3"><a href="/acme/agent-harness" class="Link">acme / agent-harness</a></h2></article>')
        if host == "api.github.com":
            return self.github(request)
        if host == "api.groq.com":
            return self.groq(request)
        return httpx.Response(404, text="not found")

    def _node(self, full: str) -> dict | None:
        r = self.repos.get(full.lower())
        if not r:
            return None
        return {"nameWithOwner": full, "description": r["desc"], "url": f"https://github.com/{full}", "homepageUrl": None,
                "createdAt": isoz(r["created"]), "pushedAt": isoz(NOW - timedelta(hours=6)), "isArchived": False,
                "stargazerCount": r["stars"], "forkCount": r["forks"], "primaryLanguage": {"name": "Python"},
                "licenseInfo": {"spdxId": "MIT"}, "issues": {"totalCount": 12},
                "repositoryTopics": {"nodes": [{"topic": {"name": t}} for t in r["topics"]]},
                "latestRelease": {"tagName": "v0.9.0", "name": "v0.9.0", "publishedAt": isoz(NOW - timedelta(days=2)),
                                  "url": f"https://github.com/{full}/releases/tag/v0.9.0"},
                "releases": {"nodes": [
                    {"tagName": "v0.9.0", "name": "v0.9.0", "url": f"https://github.com/{full}/releases/tag/v0.9.0",
                     "publishedAt": isoz(NOW - timedelta(days=2)), "isPrerelease": False, "isDraft": False,
                     "description": "## Highlights\n- Faster **inference** with speculative decoding\n- New MCP integration"},
                    {"tagName": "v0.8.3", "name": "v0.8.3", "url": f"https://github.com/{full}/releases/tag/v0.8.3",
                     "publishedAt": isoz(NOW - timedelta(days=9)), "isPrerelease": False, "isDraft": False, "description": "Bug fixes"}]}}

    def github(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/search/repositories":
            items = []
            for full, r in self.repos.items():
                if r["created"] > NOW - timedelta(days=60):
                    owner, name = full.split("/")
                    items.append({"full_name": full, "name": name, "owner": {"login": owner}, "description": r["desc"],
                                  "language": "Python", "stargazers_count": r["stars"], "forks_count": r["forks"],
                                  "created_at": isoz(r["created"]), "pushed_at": isoz(NOW - timedelta(hours=6)), "topics": r["topics"],
                                  "html_url": f"https://github.com/{full}", "archived": False, "fork": False, "open_issues_count": 3})
            return httpx.Response(200, json={"total_count": len(items), "items": items})
        if path.endswith("/readme"):
            return httpx.Response(200, text="# Agent Harness\n\nA harness that runs **coding agents** with MCP tools.\n\n```bash\npip install x\n```")
        if path == "/graphql":
            q = json.loads(request.content)["query"]
            data, errors = {}, []
            for alias, owner, name in re.findall(r'(r\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\)', q):
                node = self._node(f"{owner}/{name}")
                data[alias] = node
                if node is None:
                    errors.append({"type": "NOT_FOUND", "message": f"Could not resolve {owner}/{name}"})
            data["rateLimit"] = {"remaining": 4999, "cost": 1}
            return httpx.Response(200, json={"data": data, "errors": errors})
        return httpx.Response(404, json={"message": "Not Found"})

    def groq(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "whisper-large-v3"}, {"id": "llama-3.3-70b-versatile"}]})
        self.llm_calls += 1
        if self.llm_status != 200:
            return httpx.Response(self.llm_status, json={"error": {"message": "rate limited"}}, headers={"retry-after": "120"})
        body = json.loads(request.content)
        prompt = body["messages"][1]["content"]
        if "Explain this item in depth" in prompt:
            out = {"plain_explanation": "A new small model for developers.", "how_it_works": "Not stated in the source.",
                   "what_changed": "A new model release.", "why_it_matters": "Cheaper tool calling.",
                   "comparison": "General context: small models trade quality for cost.", "strengths": ["Tool calling"],
                   "limitations": ["Only vendor claims"], "use_cases": ["Agents"],
                   "evidence": {"claims": ["81% on SWE-bench Verified"], "evidence_given": "None stated", "unverified": ["benchmark score"]},
                   "explore": {"experiments": ["Try it on a small agent task"], "implementation_ideas": ["Swap into an agent"],
                               "questions": ["How does it compare on cost?"], "search_terms": ["GPT-7 Mini tool calling"]},
                   "glossary": [{"term": "tool calling", "meaning": "letting the model use functions"}]}
        elif "briefing" in prompt:
            ids = re.findall(r"- id: (\w+)", prompt)
            out = {"headline": "Small models and agent harnesses", "overview": "Busy day.",
                   "bullets": [{"text": "A new model.", "item_ids": ids[:1]}, {"text": "Fake id.", "item_ids": ["nope"]}],
                   "watch_next": ["Pricing"]}
        else:
            ids = re.findall(r"### id: (\w+)", prompt)
            out = {"items": [{"id": i, "summary": f"Summary of {i}. It scores 99% on everything.",
                              "why_it_matters": "Matters.", "key_terms": [], "source_is_thin": False} for i in ids]}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(out)}}],
                                         "usage": {"prompt_tokens": 500, "completion_tokens": 200}})


@pytest.fixture(autouse=True)
def frozen_now():
    util.set_now(NOW)
    yield NOW
    util.set_now(None)


@pytest.fixture
def web():
    return FakeWeb()


@pytest.fixture
def http(web):
    h = Http(transport=httpx.MockTransport(web), retries=1)
    h.sleep = lambda s: None
    return h


@pytest.fixture
def config(tmp_path):
    env = {"AIRADAR_DB": str(tmp_path / "radar.db"), "AIRADAR_SITE_DIR": str(tmp_path / "site"), "GITHUB_TOKEN": "test-token"}
    cfg = cfgmod.load(env=env)
    cfg.github["discovery_topics"] = ["ai-agents"]
    cfg.github["discovery_keywords"] = []
    cfg.github["curated_repos"] = ["vllm-project/vllm", "gone/renamed-repo"]
    # Keep only sources the fake web serves (others would just be recorded as failures).
    keep = {"openai-news", "simonwillison", "techcrunch-ai", "hackernews", "arxiv", "hf-papers", "hf-models",
            "github-discovery", "github-snapshots", "github-releases", "trendshift", "github-trending"}
    for s in cfg.sources:
        s.enabled = s.id in keep
    return cfg
