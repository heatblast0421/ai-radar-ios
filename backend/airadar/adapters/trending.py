"""Discovery hints from trending pages (Trendshift, GitHub Trending).

We only read which repositories are listed there, then measure those repositories ourselves through
GitHub's official API. Their rankings/scores are never stored or republished (Trendshift's terms treat
rankings as its intellectual property); the app just shows "Spotted on <site>" with a link.
"""
from __future__ import annotations

import re

from .base import AdapterResult
from .github import GitHubBase, build_repo_query, repo_from_graphql

# owner/repo as GitHub allows it
_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9\-]{0,38})/[A-Za-z0-9_.\-]{1,100}"
_GH_LINK = re.compile(r"github\.com/(" + _NAME + r")(?=[\"'/?#\s<)])")
_GH_TRENDING_H2 = re.compile(r'<h2[^>]*>\s*<a[^>]*href="/(' + _NAME + r')"', re.S)
_TEXT_NAME = re.compile(r">\s*(" + _NAME + r")\s*<")
_RESERVED_OWNERS = {"features", "topics", "trending", "orgs", "sponsors", "marketplace", "about", "pricing", "login",
                    "collections", "settings", "site", "apps", "explore", "enterprise", "github", "readme", "events"}
_BAD_SUFFIX = (".png", ".jpg", ".svg", ".css", ".js", ".git")


def extract_repo_names(html: str, mode: str = "generic") -> list[str]:
    found: list[str] = []
    patterns = [_GH_TRENDING_H2] if mode == "github" else [_GH_LINK, _TEXT_NAME]
    for rx in patterns:
        for m in rx.finditer(html):
            name = m.group(1).strip().rstrip(".")
            owner, _, repo = name.partition("/")
            if owner.lower() in _RESERVED_OWNERS or not repo or repo.lower().endswith(_BAD_SUFFIX):
                continue
            if name.lower() not in {f.lower() for f in found}:
                found.append(name)
    return found[:80]


class TrendingPageAdapter(GitHubBase):
    """Reads a trending page and queues its repositories for tracking (discovery hint only)."""
    kind = "trending_page"

    def fetch(self) -> AdapterResult:
        result = AdapterResult()
        mode = self.source.options.get("parse", "generic")
        urls = [self.source.url] + list(self.source.options.get("extra_urls", []))
        names: list[str] = []
        for url in urls:
            resp = self.http.get(url, headers={"Accept": "text/html"})
            for n in extract_repo_names(resp.text, mode):
                if n.lower() not in {x.lower() for x in names}:
                    names.append(n)
        result.fetched = len(names)
        queued = self.store.queue_repo_candidates(names, via=self.source.id, label=self.source.name,
                                                  link=self.source.url)
        if not names:
            raise ValueError("no repositories found on page (layout may have changed)")
        measured = 0
        if self.config.github_token:
            # Measure everything listed right away through the official GitHub API.
            for i in range(0, len(names), 40):
                batch = names[i:i + 40]
                data = self.graphql(build_repo_query(batch))
                for j, full in enumerate(batch):
                    node = data.get(f"r{j}")
                    if node:
                        self.store.upsert_repo(repo_from_graphql(node), discovered_via=self.source.id, observed=True)
                        measured += 1
        result.notes.append(f"{len(names)} repos listed, {queued} new, {measured} measured via GitHub API")
        return result
