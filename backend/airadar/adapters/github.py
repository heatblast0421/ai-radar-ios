"""GitHub official API: repository discovery (REST search), metric snapshots and releases (GraphQL).

Growth numbers are computed only from snapshots we actually recorded; nothing is estimated.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import timedelta

from ..topics import classify
from ..util import clean_text, iso, now, parse_time
from .base import Adapter, AdapterResult, RawItem

log = logging.getLogger("airadar.github")

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"


def _headers(token: str | None, accept: str = "application/vnd.github+json") -> dict:
    h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def repo_from_rest(r: dict) -> dict:
    return {
        "full_name": r["full_name"],
        "owner": r["owner"]["login"] if isinstance(r.get("owner"), dict) else r["full_name"].split("/")[0],
        "name": r["name"],
        "description": clean_text(r.get("description"), 500) or None,
        "language": r.get("language"),
        "topics": r.get("topics") or [],
        "url": r.get("html_url") or f"https://github.com/{r['full_name']}",
        "homepage": r.get("homepage") or None,
        "license": (r.get("license") or {}).get("spdx_id") if r.get("license") else None,
        "created_at": r.get("created_at"),
        "pushed_at": r.get("pushed_at"),
        "stars": int(r.get("stargazers_count") or 0),
        "forks": int(r.get("forks_count") or 0),
        "open_issues": r.get("open_issues_count"),
        "archived": bool(r.get("archived")),
    }


def repo_from_graphql(node: dict) -> dict:
    owner, name = node["nameWithOwner"].split("/", 1)
    lr = node.get("latestRelease")
    return {
        "full_name": node["nameWithOwner"],
        "owner": owner,
        "name": name,
        "description": clean_text(node.get("description"), 500) or None,
        "language": (node.get("primaryLanguage") or {}).get("name"),
        "topics": [n["topic"]["name"] for n in ((node.get("repositoryTopics") or {}).get("nodes") or [])],
        "url": node.get("url") or f"https://github.com/{node['nameWithOwner']}",
        "homepage": node.get("homepageUrl") or None,
        "license": (node.get("licenseInfo") or {}).get("spdxId"),
        "created_at": node.get("createdAt"),
        "pushed_at": node.get("pushedAt"),
        "stars": int(node.get("stargazerCount") or 0),
        "forks": int(node.get("forkCount") or 0),
        "open_issues": ((node.get("issues") or {}).get("totalCount")),
        "archived": bool(node.get("isArchived")),
        "latest_release": ({"tag": lr.get("tagName"), "name": lr.get("name"), "published_at": lr.get("publishedAt"),
                            "url": lr.get("url")} if lr else None),
    }


REPO_FIELDS = """
  nameWithOwner description url homepageUrl createdAt pushedAt isArchived stargazerCount forkCount
  primaryLanguage { name } licenseInfo { spdxId } issues(states: OPEN) { totalCount }
  repositoryTopics(first: 12) { nodes { topic { name } } }
  latestRelease { tagName name publishedAt url }
"""


def build_repo_query(full_names: list[str], with_releases: bool = False) -> str:
    parts = []
    for i, full in enumerate(full_names):
        owner, name = full.split("/", 1)
        rel = ""
        if with_releases:
            rel = ("releases(first: 5, orderBy: {field: CREATED_AT, direction: DESC}) "
                   "{ nodes { tagName name url publishedAt isPrerelease isDraft description } }")
        parts.append(f"r{i}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ {REPO_FIELDS} {rel} }}")
    return "query {\n" + "\n".join(parts) + "\n rateLimit { remaining cost } }"


class GitHubBase(Adapter):
    def graphql(self, query: str) -> dict:
        if not self.config.github_token:
            raise RuntimeError("GITHUB_TOKEN not configured (GraphQL requires authentication)")
        resp = self.http.request("POST", GRAPHQL, headers=_headers(self.config.github_token), json={"query": query})
        payload = resp.json()
        errors = payload.get("errors") or []
        for err in errors:
            if err.get("type") not in ("NOT_FOUND",):
                log.warning("graphql error: %s", err.get("message"))
        return payload.get("data") or {}


class GitHubDiscoveryAdapter(GitHubBase):
    """Finds emerging AI repositories: recently created, already attracting stars."""
    kind = "github_discovery"

    def fetch(self) -> AdapterResult:
        cfg = self.config.github
        days = int(cfg.get("created_within_days", 60))
        min_stars = int(cfg.get("min_stars_new", 40))
        since = (now() - timedelta(days=days)).strftime("%Y-%m-%d")
        queries = [f"topic:{t} created:>={since} stars:>={min_stars}" for t in cfg.get("discovery_topics", [])]
        queries += [f"\"{kw}\" in:name,description created:>={since} stars:>={min_stars}" for kw in cfg.get("discovery_keywords", [])]
        result = AdapterResult()
        seen: dict[str, dict] = {}
        token = self.config.github_token
        gap = 2.2 if token else 6.5  # search API: 30/min authenticated, 10/min anonymous
        for q in queries:
            try:
                data = self.http.get_json(f"{API}/search/repositories", headers=_headers(token),
                                          params={"q": q, "sort": "stars", "order": "desc", "per_page": 30})
            except Exception as exc:  # one failed query should not sink the whole run
                result.notes.append(f"query failed: {q[:40]}: {exc}")
                continue
            finally:
                self.http.sleep(gap)
            for r in data.get("items", []):
                result.fetched += 1
                seen.setdefault(r["full_name"].lower(), r)
        kept = 0
        for full, r in seen.items():
            repo = repo_from_rest(r)
            if repo["archived"] or r.get("fork"):
                continue
            c = classify(repo["name"].replace("-", " ") + " " + (repo["description"] or ""), "", repo["topics"])
            if c.ai_relevance < 0.15 and not c.topics:
                continue
            self.store.upsert_repo(repo, discovered_via="search", observed=True)
            kept += 1
        result.notes.append(f"{kept} AI repos kept from {len(seen)} candidates")
        self._fetch_readmes(limit=20)
        return result

    def _fetch_readmes(self, limit: int) -> None:
        for repo_id, full in self.store.repos_needing_readme(limit):
            try:
                resp = self.http.get(f"{API}/repos/{full}/readme",
                                     headers=_headers(self.config.github_token, "application/vnd.github.raw"),
                                     ok_statuses=(200,))
                self.store.set_readme(repo_id, markdown_to_text(resp.text)[:6000])
            except Exception as exc:
                log.info("readme unavailable for %s: %s", full, exc)
                self.store.set_readme(repo_id, "")


def markdown_to_text(md: str) -> str:
    md = re.sub(r"(?s)<!--.*?-->", " ", md)
    md = re.sub(r"(?s)```.*?```", " [code example] ", md)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", md)                  # images
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)               # links -> text
    md = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", md)                  # headings
    md = re.sub(r"(?m)^\s*\|.*\|\s*$", " ", md)                    # tables
    md = re.sub(r"[*_`>]{1,3}", "", md)
    return clean_text(md)


class GitHubSnapshotsAdapter(GitHubBase):
    """Records a timestamped stars/forks snapshot for every tracked repository (GraphQL, 40 per query)."""
    kind = "github_snapshots"

    def fetch(self) -> AdapterResult:
        curated = [c for c in self.config.github.get("curated_repos", [])]
        self.store.ensure_curated(curated)
        tracked = self.store.tracked_repo_names(int(self.config.limits.get("max_tracked_repos", 450)))
        names, seen = [], set()
        for n in curated + tracked:
            if n.lower() not in seen and not self.store.is_untracked(n):
                seen.add(n.lower())
                names.append(n)
        result = AdapterResult()
        missing = []
        for i in range(0, len(names), 40):
            batch = names[i:i + 40]
            data = self.graphql(build_repo_query(batch))
            for j, full in enumerate(batch):
                node = data.get(f"r{j}")
                if not node:
                    missing.append(full)
                    continue
                result.fetched += 1
                self.store.upsert_repo(repo_from_graphql(node), discovered_via=None, observed=True)
        self.store.ensure_curated(curated)
        if missing:
            self.store.mark_missing_repos(missing)
            result.notes.append(f"{len(missing)} repos not found (renamed or deleted): {', '.join(missing[:8])}")
        return result


SEMVER_RE = re.compile(r"v?(\d+)\.(\d+)(?:\.(\d+))?")


def release_significance(tag: str) -> str:
    """major | minor | patch | other — from the version tag only."""
    m = SEMVER_RE.search(tag or "")
    if not m:
        return "other"
    patch = int(m.group(3) or 0)
    if int(m.group(2)) == 0 and patch == 0:
        return "major"
    return "minor" if patch == 0 else "patch"


class GitHubReleasesAdapter(GitHubBase):
    """Release notes of important frameworks (official changelogs published on GitHub)."""
    kind = "github_releases"

    def fetch(self) -> AdapterResult:
        curated = list(self.config.github.get("curated_repos", []))
        self.store.ensure_curated(curated)
        result = AdapterResult()
        cutoff = now() - timedelta(days=30)
        curated = [c for c in curated if not self.store.is_untracked(c)]
        for i in range(0, len(curated), 20):
            batch = curated[i:i + 20]
            data = self.graphql(build_repo_query(batch, with_releases=True))
            for j, full in enumerate(batch):
                node = data.get(f"r{j}")
                if not node:
                    self.store.mark_missing_repos([full])
                    result.notes.append(f"curated repo not found: {full}")
                    continue
                repo = repo_from_graphql(node)
                repo_id = self.store.upsert_repo(repo, discovered_via="curated", observed=True)
                for rel in ((node.get("releases") or {}).get("nodes") or []):
                    if rel.get("isDraft"):
                        continue
                    result.fetched += 1
                    body = clean_text(markdown_to_text(rel.get("description") or ""), 5000)
                    self.store.upsert_release(repo_id, rel, body)
                    published = parse_time(rel.get("publishedAt"))
                    if rel.get("isPrerelease") or not published or published < cutoff:
                        continue
                    tag = rel.get("tagName") or ""
                    sig = release_significance(tag)
                    name = clean_text(rel.get("name")) or tag
                    title = f"{repo['full_name']} {tag}" if name in (tag, f"v{tag}", tag.lstrip("v")) else f"{repo['full_name']} {tag}: {name}"
                    result.items.append(RawItem(
                        kind="release",
                        title=title[:200],
                        url=rel.get("url") or f"{repo['url']}/releases/tag/{tag}",
                        provider_key=f"gh-release:{repo['full_name'].lower()}@{tag}",
                        author=repo["owner"],
                        published_at=iso(published),
                        content=body,
                        metrics={"stars": repo["stars"]},
                        tags=repo["topics"][:8],
                        extra={"repo": repo["full_name"], "tag": tag, "release_kind": sig, "repo_url": repo["url"]},
                    ))
            self.http.sleep(0.5)
        self.store.ensure_curated(curated)
        return result
