# AI Radar

Your personal AI intelligence app for iPhone. AI Radar continuously collects what matters in AI (GitHub repositories, model releases, research papers, engineering news, framework releases and industry moves), ranks it with transparent rules, explains it at three levels of depth, and keeps it in a fast native iPhone app.

```
┌────────────────────────── GitHub (free) ──────────────────────────┐
│  Every 15 min: "Ingest & publish" workflow                        │
│   sources ──► dedupe ──► rank ──► AI explanations ──► JSON API    │
│   (GitHub, HN, arXiv, HF, blogs, releases, Trendshift…)           │
│   database: SQLite saved on the `data` branch                     │
│   API: https://heatblast0421.github.io/ai-radar-ios/api/v1/       │
└───────────────────────────────┬───────────────────────────────────┘
                                │ HTTPS (read-only JSON)
                     ┌──────────▼──────────┐
                     │   AI Radar iPhone   │  SwiftUI · offline cache ·
                     │        app          │  bookmarks & prefs on device
                     └─────────────────────┘
```

## What's in this folder

| Folder | What it is |
|---|---|
| `ios/` | The SwiftUI iPhone app (open `ios/AIRadar.xcodeproj` in Xcode) |
| `backend/` | The Python data pipeline (sources, ranking, AI explanations, JSON export) |
| `backend/config/sources.toml` | Every source, its schedule and credibility. Add or disable sources here |
| `backend/airadar/migrations/` | Database schema (SQLite) and migrations |
| `backend/tests/` | Automated tests (fake-internet end-to-end tests) |
| `.github/workflows/` | The "backend" (scheduled ingestion), backend tests, iOS build/test/screenshots |
| `docs/` | Guides: iPhone install, troubleshooting, accounts & costs, how it works |

## Guides

- **[Put the app on your iPhone](docs/IPHONE_GUIDE.md)**: step by step, no coding.
- **[Troubleshooting](docs/TROUBLESHOOTING.md)**
- **[Accounts, keys and costs](docs/ACCOUNTS_AND_COSTS.md)**
- **[How AI Radar works](docs/HOW_IT_WORKS.md)**: sources, ranking, explanations, data model.

## Everyday operation

Nothing. The pipeline runs by itself every 15 minutes on GitHub's servers. Your Mac does not need to be on. With a free Apple ID, you re-install the app from Xcode once every 7 days (see the iPhone guide).

## For developers

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q                       # tests (no network needed)
cp .env.example .env                      # optional keys for local runs
python -m airadar.cli run --force all     # fetch everything now -> backend/site/api/v1
python -m airadar.cli serve               # preview at http://127.0.0.1:8787/api/v1/health.json
```

iOS: `xcodebuild test -project ios/AIRadar.xcodeproj -scheme AIRadar -destination 'platform=iOS Simulator,name=iPhone 16'`.
iOS test fixtures are regenerated from the backend with `python backend/tests/export_ios_fixtures.py`.
