# How AI Radar works

## 1. Collecting (the "backend")

A GitHub Actions workflow (`.github/workflows/ingest.yml`) wakes up every 15 minutes. It only runs the sources that are due, according to `backend/config/sources.toml`:

| Job | Default interval | Sources |
|---|---|---|
| Developer community | 15 min | Hacker News (official HN Search API by Algolia) |
| Official announcements | 30 min | OpenAI, Google DeepMind, Google AI, Google Research, Hugging Face, Microsoft Research, NVIDIA, GitHub Blog, AWS ML, Cloudflare, Meta Engineering |
| Engineering writing | 60 min | Simon Willison, Latent Space, Interconnects, Sebastian Raschka, Lilian Weng, Chip Huyen, Eugene Yan, Lobsters |
| Industry | 60 min | TechCrunch AI, VentureBeat AI, The Verge AI, Ars Technica AI, MIT Technology Review |
| Framework releases | 60 min | GitHub releases of about 40 key projects (vLLM, LangGraph, MCP SDKs, Claude Code, Ollama…) |
| GitHub discovery | 2 h | GitHub Search: recently created repos with AI topics, already gaining stars |
| Trending hints | 3 h | Trendshift, GitHub Trending (used only to *discover* repos; see below) |
| Papers | 2–6 h | Hugging Face Daily Papers, arXiv API (cs.AI/CL/LG/MA/IR/SE, filtered to engineering topics) |
| Models | 3 h | Hugging Face trending models (only models created in the last 60 days) |
| Repo metrics | 6 h | Star/fork snapshots of every tracked repo (GitHub GraphQL) |
| Daily briefing | daily | Generated after 06:00 IST |

Each source is an *adapter* (`backend/airadar/adapters/`). To add one, add a line to `sources.toml`; a new kind of source needs a small adapter class. Retries, rate limits (`Retry-After`, GitHub rate-limit headers), arXiv's 3-second politeness gap and conditional GET (ETag) are handled in `airadar/http.py`. A failing source is recorded and shown in the app; everything else keeps working.

**Trendshift and GitHub Trending.** Trendshift's terms treat its rankings as its intellectual property and restrict republishing its raw data. AI Radar therefore only reads *which* repositories are listed, then measures them itself through GitHub's official API. The app shows "Spotted on Trendshift" with a link and never displays Trendshift's ranks or scores.

## 2. Storing and de-duplicating

SQLite database (`migrations/001_init.sql`, `002_repo_hints.sql`), saved between runs on the repository's `data` branch.

- Every URL is canonicalised (tracking parameters removed; arXiv abs/pdf/versions and HF paper pages unified; GitHub repo URLs normalised).
- Same URL from another source = the same item. The more credible source becomes the primary (an official blog post replaces the HN link to it), and the other becomes a *mention*, keeping its points and comments.
- Similar headlines within a few days (shared words, shared model names such as "gpt-7") are grouped into one **story** with "Also reported by" sources.
- Every item keeps `published_at` (from the source), `discovered_at` and `updated_at`.
- Repository snapshots are append-only (thinned to one per day after 30 days). **All growth numbers come from these snapshots.** With fewer than two measurements the app says "collecting data". The only other figure shown is "average stars per day since creation", computed from GitHub's own numbers and labelled as such.

## 3. Ranking (transparent, rule-based)

`backend/airadar/rank.py`. Score 0–100 is a weighted sum shown in the app under "Why it's ranked here":

| Signal | Weight | Meaning |
|---|---|---|
| Relevance | 28% | AI relevance and strength of engineering topics (keyword rules, not an LLM) |
| Freshness | 22% | Half-life about 30 h (papers 60 h, repos 72 h) |
| Credibility | 15% | Per-source weight in `sources.toml`, raised when a more credible source corroborates |
| Engagement | 22% | HN points/comments, HF upvotes/likes, measured repo momentum, number of sources |
| Significance | 13% | Rules: official launch wording, security advisories (CVE/GHSA), major releases |

Safeguards:
- Official launches and security news within 4 days get a guaranteed minimum score and an "Important" badge, even without community buzz.
- Patch releases and older releases stay on the repo page.
- A diversity pass stops one type (for example, papers) from filling the top of a feed.

**For You** is computed on the phone: it boosts your followed topics and the topics you save.

## 4. AI explanations

`backend/airadar/llm/`. The provider is detected from the key (Gemini `AIza…`, Groq `gsk_…`, xAI `xai-…`, Anthropic `sk-ant-…`, OpenAI `sk-…`), and the newest suitable small model is picked automatically.

- **Level 1 (Quick):** 2-sentence summary, why it matters, jargon explained. Written in batches of 6 items per call for the highest-ranked items.
- **Level 2 (Technical):** how it works, what changed, comparison, strengths, limitations, use cases, plus an evidence check (claims vs. evidence given vs. what to verify). Written for the most important items.
- **Level 3 (Explore):** experiments, project ideas, questions, search terms, plus related repositories and items from AI Radar's own index (real links, not AI-generated).

Grounding rules: the model sees only the stored source text and is told to answer "Not stated in the source" instead of guessing. Any number in the AI text that does not appear in the source is flagged in the app. Explanations are cached per item and regenerated only if the source text changes. Budgets per run and per day protect the free tier, and after a rate limit the pipeline pauses AI work for 45 minutes. Briefing bullets must cite real item ids, and uncited bullets are dropped.

## 5. The JSON API (what the app reads)

Published to GitHub Pages: `https://heatblast0421.github.io/ai-radar-ios/api/v1/`

`health.json`, `meta.json` (source health, AI status, topics), `briefing.json`, `search.json`, `feed/{pulse|research|lab|industry}/{top|latest|trending}/{n}.json`, `github/{emerging|growing|stars|new|releases}/{n}.json`, `items/{id}.json`, `repos/{owner__name}.json`, `last_run.json`.

## 6. The iPhone app

SwiftUI, iOS 17+, no third-party dependencies.

- Tabs: Pulse, GitHub, Research, Lab, Industry. Search, Saved and Settings are in the top bar of every tab.
- Every response is cached on the device, so the app works offline and shows an "Offline" banner with the copy's age.
- Bookmarks are a JSON file in Application Support. Preferences are stored in UserDefaults. Neither leaves the phone.
- Notifications are local: a daily briefing reminder, plus best-effort "Important" alerts during iOS background refresh.
- Research (v1) is fast keyword search over everything indexed, with preset research questions. Every result links to its source.
