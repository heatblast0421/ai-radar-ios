"""Source adapter registry. Add a new adapter class here and reference its `kind` in config/sources.toml."""
from .github import GitHubDiscoveryAdapter, GitHubReleasesAdapter, GitHubSnapshotsAdapter
from .hackernews import HackerNewsAdapter
from .papers import ArxivAdapter, HFModelsAdapter, HFPapersAdapter
from .rss import RssAdapter
from .trending import TrendingPageAdapter

ADAPTERS = {
    cls.kind: cls
    for cls in (RssAdapter, HackerNewsAdapter, ArxivAdapter, HFPapersAdapter, HFModelsAdapter,
                GitHubDiscoveryAdapter, GitHubSnapshotsAdapter, GitHubReleasesAdapter, TrendingPageAdapter)
}
