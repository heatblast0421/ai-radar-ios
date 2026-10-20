"""Regenerates the iOS unit-test fixtures from the backend's fake-internet pipeline run,
so the app's decoders are always tested against the exact JSON the backend produces.

    cd backend && python tests/export_ios_fixtures.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import conftest  # noqa: E402
from airadar import config as cfgmod, util  # noqa: E402
from airadar.http import Http  # noqa: E402
from airadar.llm.provider import LLM  # noqa: E402
from airadar.pipeline import run  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "ios" / "AIRadarTests" / "Fixtures"


def main():
    util.set_now(conftest.NOW)
    tmp = Path(tempfile.mkdtemp())
    web = conftest.FakeWeb()
    http = Http(transport=httpx.MockTransport(web), retries=1)
    http.sleep = lambda s: None
    cfg = cfgmod.load(env={"AIRADAR_DB": str(tmp / "r.db"), "AIRADAR_SITE_DIR": str(tmp / "site"), "GITHUB_TOKEN": "x"})
    cfg.github["discovery_topics"] = ["ai-agents"]
    cfg.github["discovery_keywords"] = []
    cfg.github["curated_repos"] = ["vllm-project/vllm"]
    keep = {"openai-news", "simonwillison", "techcrunch-ai", "hackernews", "arxiv", "hf-papers", "hf-models",
            "github-discovery", "github-snapshots", "github-releases", "trendshift", "github-trending"}
    for s in cfg.sources:
        s.enabled = s.id in keep
    cfg.llm_api_key = "gsk_fixture"
    run(cfg, force={"all"}, http=http, llm=LLM("gsk_fixture", http))
    api = tmp / "site" / "api" / "v1"
    OUT.mkdir(parents=True, exist_ok=True)
    pulse = json.loads((api / "feed/pulse/top/1.json").read_text())
    gpt = next(c for c in pulse["items"] if "GPT-7" in c["title"])
    copies = {
        "feed_pulse_top_1.json": api / "feed/pulse/top/1.json",
        "item_detail.json": api / f"items/{gpt['id']}.json",
        "repo_detail.json": api / "repos/acme__agent-harness.json",
        "github_emerging_1.json": api / "github/emerging/1.json",
        "meta.json": api / "meta.json",
        "briefing.json": api / "briefing.json",
        "search.json": api / "search.json",
    }
    for name, src in copies.items():
        shutil.copy(src, OUT / name)
    print("wrote", len(copies), "fixtures to", OUT)


if __name__ == "__main__":
    main()
