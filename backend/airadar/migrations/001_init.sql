-- AI Radar database schema, version 1.
-- SQLite. Applied by airadar.db.migrate(); each file runs once and is recorded in schema_migrations.

CREATE TABLE IF NOT EXISTS sources (
    id              TEXT PRIMARY KEY,          -- e.g. "hackernews", "rss:openai-news"
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL,             -- rss | hackernews | arxiv | hf_papers | hf_models | github_*
    url             TEXT,
    credibility     REAL NOT NULL DEFAULT 0.5, -- 0..1, configured, transparent
    official        INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    last_attempt_at TEXT,
    last_success_at TEXT,
    last_error      TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    items_last_run  INTEGER NOT NULL DEFAULT 0,
    etag            TEXT,
    last_modified   TEXT
);

CREATE TABLE IF NOT EXISTS source_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL REFERENCES sources(id),
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    ok          INTEGER NOT NULL DEFAULT 0,
    fetched     INTEGER NOT NULL DEFAULT 0,
    new_items   INTEGER NOT NULL DEFAULT 0,
    updated_items INTEGER NOT NULL DEFAULT 0,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_runs_source ON source_runs(source_id, started_at);

-- Every discovered thing (article, paper, discussion, release, model, repo card) is an item.
CREATE TABLE IF NOT EXISTS items (
    id              TEXT PRIMARY KEY,          -- stable hash of canonical_url (or provider key)
    kind            TEXT NOT NULL,             -- article | paper | discussion | release | model | repo
    title           TEXT NOT NULL,
    url             TEXT NOT NULL,             -- original link
    canonical_url   TEXT NOT NULL,
    source_id       TEXT NOT NULL REFERENCES sources(id),
    provider_key    TEXT,                      -- e.g. "hn:123", "arxiv:2410.12345", "gh:owner/name"
    author          TEXT,
    published_at    TEXT,                      -- as stated by the source (UTC ISO8601)
    discovered_at   TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    content         TEXT,                      -- verified source text (excerpt), never AI output
    content_hash    TEXT,
    metrics         TEXT NOT NULL DEFAULT '{}',-- JSON: points, comments, upvotes, stars...
    topics          TEXT NOT NULL DEFAULT '[]',-- JSON list of topic ids (deterministic classifier)
    sections        TEXT NOT NULL DEFAULT '[]',-- JSON list: pulse, research, lab, industry, github
    ai_relevance    REAL NOT NULL DEFAULT 0,
    score           REAL NOT NULL DEFAULT 0,
    trending_score  REAL NOT NULL DEFAULT 0,
    score_breakdown TEXT NOT NULL DEFAULT '{}',
    importance      TEXT,                      -- high | notable | NULL (rule-based, never LLM-only)
    importance_reason TEXT,
    story_id        TEXT,                      -- grouping of items about the same news
    discussion_url  TEXT,
    extra           TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_canonical ON items(canonical_url);
CREATE INDEX IF NOT EXISTS idx_items_provider ON items(provider_key);
CREATE INDEX IF NOT EXISTS idx_items_published ON items(published_at);
CREATE INDEX IF NOT EXISTS idx_items_story ON items(story_id);
CREATE INDEX IF NOT EXISTS idx_items_score ON items(score);

-- Additional sources that reported the same item (e.g. an HN thread linking to an official blog post).
CREATE TABLE IF NOT EXISTS item_mentions (
    item_id     TEXT NOT NULL REFERENCES items(id),
    source_id   TEXT NOT NULL REFERENCES sources(id),
    url         TEXT NOT NULL,
    title       TEXT,
    metrics     TEXT NOT NULL DEFAULT '{}',
    seen_at     TEXT NOT NULL,
    PRIMARY KEY (item_id, url)
);

CREATE TABLE IF NOT EXISTS repos (
    id              TEXT PRIMARY KEY,          -- "owner/name" lowercased
    full_name       TEXT NOT NULL,
    owner           TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    language        TEXT,
    topics          TEXT NOT NULL DEFAULT '[]',-- GitHub topics
    categories      TEXT NOT NULL DEFAULT '[]',-- our topic ids
    url             TEXT NOT NULL,
    homepage        TEXT,
    license         TEXT,
    created_at      TEXT,
    pushed_at       TEXT,
    stars           INTEGER NOT NULL DEFAULT 0,
    forks           INTEGER NOT NULL DEFAULT 0,
    open_issues     INTEGER,
    archived        INTEGER NOT NULL DEFAULT 0,
    latest_release  TEXT,                      -- JSON {tag, name, published_at, url}
    readme_excerpt  TEXT,
    readme_hash     TEXT,
    tracked         INTEGER NOT NULL DEFAULT 1,
    curated         INTEGER NOT NULL DEFAULT 0,
    first_seen_at   TEXT NOT NULL,
    last_checked_at TEXT,
    score           REAL NOT NULL DEFAULT 0,
    emerging_score  REAL NOT NULL DEFAULT 0,
    score_breakdown TEXT NOT NULL DEFAULT '{}',
    discovered_via  TEXT
);
CREATE INDEX IF NOT EXISTS idx_repos_score ON repos(score);

-- Historical measurements; never edited, only appended. Basis for all growth numbers.
CREATE TABLE IF NOT EXISTS repo_snapshots (
    repo_id     TEXT NOT NULL REFERENCES repos(id),
    taken_at    TEXT NOT NULL,
    stars       INTEGER NOT NULL,
    forks       INTEGER NOT NULL,
    open_issues INTEGER,
    pushed_at   TEXT,
    PRIMARY KEY (repo_id, taken_at)
);

CREATE TABLE IF NOT EXISTS repo_releases (
    repo_id      TEXT NOT NULL REFERENCES repos(id),
    tag          TEXT NOT NULL,
    name         TEXT,
    url          TEXT NOT NULL,
    published_at TEXT,
    prerelease   INTEGER NOT NULL DEFAULT 0,
    body_excerpt TEXT,
    PRIMARY KEY (repo_id, tag)
);

-- Cached AI explanations. Regenerated only when content_hash or prompt_version changes.
CREATE TABLE IF NOT EXISTS explanations (
    subject_id     TEXT NOT NULL,              -- item id or "repo:owner/name"
    level          TEXT NOT NULL,              -- quick | deep
    content_hash   TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL,
    payload        TEXT NOT NULL,              -- JSON
    warnings       TEXT NOT NULL DEFAULT '[]',
    created_at     TEXT NOT NULL,
    PRIMARY KEY (subject_id, level)
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT NOT NULL,
    provider    TEXT NOT NULL,
    model       TEXT NOT NULL,
    purpose     TEXT NOT NULL,
    ok          INTEGER NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_usage_at ON llm_usage(at);

CREATE TABLE IF NOT EXISTS briefings (
    day          TEXT PRIMARY KEY,             -- YYYY-MM-DD (UTC)
    generated_at TEXT NOT NULL,
    kind         TEXT NOT NULL,                -- ai | auto
    payload      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_state (
    job         TEXT PRIMARY KEY,              -- scheduler groups
    last_run_at TEXT,
    last_ok_at  TEXT,
    last_error  TEXT
);
