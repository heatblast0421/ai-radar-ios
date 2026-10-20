# Accounts, keys and costs

## What's set up

| Service | Used for | Cost | Notes |
|---|---|---|---|
| **GitHub** (account `heatblast0421`, public repo `ai-radar-ios`) | Runs the backend every 15 min (Actions), hosts the JSON API (Pages), stores the database (`data` branch), builds/tests the iOS app on a cloud Mac | **$0** | Actions minutes are free and unlimited for public repositories. Pages: 1 GB site and about 100 GB/month bandwidth (AI Radar uses a few MB). GitHub pauses schedules in repos idle for 60 days; the workflow re-enables itself daily. |
| **Google Gemini API** (free tier) | AI summaries, deep explanations, daily briefing | **$0** | Google sets the free limits and can change them. AI Radar caps itself at 6 calls per run and 90 per day by default, and pauses after a rate limit. On the free tier Google may use prompts to improve its products; AI Radar only sends public news text. |
| **Apple ID** (free) | Installing the app from Xcode | **$0** | The app must be re-installed every 7 days. No server push notifications. |
| Hacker News, arXiv, Hugging Face, RSS feeds, Trendshift/GitHub Trending pages | Data sources | **$0** | Public endpoints, used politely (caching, rate limits). |

**Current total: $0 per month.**

## Keys and where they live

| Key | Where | Who needs it |
|---|---|---|
| `GEMINI_API_KEY` | GitHub → repo Settings → Secrets → Actions (encrypted) | The backend only. Never in the app or the code. |
| GitHub fine-grained token "AI Radar setup" | `~/Claude/AI-Radar-private/github-token.txt` on your Mac (never uploaded) | Only so Claude can push changes. Expires 2026-11-19. Delete it any time at github.com/settings/personal-access-tokens; the app and backend keep working without it. |
| `GITHUB_TOKEN` | Created automatically by GitHub for each workflow run | The backend's GitHub API access. Nothing to manage. |

The iPhone app contains **no secrets**. It only reads public JSON.

**Recommended:** because the Gemini key was pasted into a chat, create a fresh key at https://aistudio.google.com/apikey, delete the old one there, and update the `GEMINI_API_KEY` secret on GitHub.

## Optional upgrades (only if you want them)

| Upgrade | Cost | What you get |
|---|---|---|
| Apple Developer Program | $99/year | Installs last 1 year, TestFlight installs without Xcode or a cable, real push notifications (would need a small push service). |
| Paid Gemini tier, or Claude Haiku / Groq | Usage-based. At AI Radar's caps (about 90 calls/day, roughly 3k tokens each), typically **about $1–5/month** on small "flash/haiku-class" models. Prices change, so check the provider's pricing page. | Higher daily limits, explanations for more items. Swap by changing the secret; the provider is auto-detected from the key. |

## Usage-based uncertainties

- Free-tier AI limits can shrink. AI Radar then simply explains fewer items, and the feed itself is unaffected.
- A source may block automated readers (PyTorch's blog does). It shows as "Error" in Settings and the rest continues.
- GitHub may change free-tier policies for Actions or Pages. The pipeline is plain Python and can run on any scheduler (for example, a $5/month VPS or Cloudflare) if needed.
