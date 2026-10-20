# Troubleshooting

## Installing with Xcode

| What you see | What to do |
|---|---|
| Red error: *"Failed to register bundle identifier"* or *"not available"* | Signing & Capabilities → change **Bundle Identifier** to something unique (for example `com.arnit.airadar2`). |
| *"No account for team"* / Team is empty | Xcode → Settings → Accounts → add your Apple ID, then pick "(Personal Team)". |
| Your iPhone isn't in the device list | Unlock the iPhone, re-plug the cable, tap **Trust**. Check Developer Mode is on (Settings → Privacy & Security). |
| *"iOS xx is not supported by this version of Xcode"* | Update Xcode from the Mac App Store, then try again. |
| *"Untrusted Developer"* on the iPhone | Settings → General → VPN & Device Management → your Apple ID → **Trust**. |
| *"Could not launch… device locked"* | Unlock the iPhone and press ▶ again. |
| App stopped opening after a week | Normal with a free Apple ID: open the project and press ▶ again (see the iPhone guide). |
| *"Maximum number of apps for free development"* | Free accounts can have 3 self-installed apps per device. Delete an old test app from the iPhone. |

## Inside the app

| What you see | What to do |
|---|---|
| "Can't reach the AI Radar server" | Check the internet connection. In Safari, open https://heatblast0421.github.io/ai-radar-ios/api/v1/health.json. If it shows `"status"`, the server is fine; pull down to refresh. |
| Orange "Offline" banner | You're seeing the copy saved on the phone. Pull down when you're back online. |
| Feed looks old (Settings → Status → "Last update" is hours ago) | Open https://github.com/heatblast0421/ai-radar-ios/actions. If "Ingest & publish" has a yellow banner saying the workflow is disabled, click **Enable workflow**. To force a run, open the workflow → **Run workflow** → type `all` → **Run workflow**. |
| No "AI summary" on items | Settings → Status → AI explanations. "Not configured" means the `GEMINI_API_KEY` secret is missing. "Recent AI issue: …rate limited" means the free daily quota is used up; it resumes automatically. Lower-ranked items intentionally show source text only. |
| A source shows "Error" in Settings → Data sources | The site was unreachable or changed its feed. Others keep working. Persistent errors can be switched off (see below). |
| GitHub "Fastest growing" is empty | It fills after the second measurement (every 6 hours). AI Radar never estimates growth. |
| No notifications | Settings in the app → Notifications. If iOS says notifications are off, tap the button to open iPhone Settings. "Important news" alerts depend on iOS background refresh, which iOS schedules itself. |

## Changing how the backend behaves (no code)

On GitHub: repository → **Settings → Secrets and variables → Actions → Variables** tab → **New repository variable**:

| Variable | Example | Effect |
|---|---|---|
| `AIRADAR_DISABLED_SOURCES` | `venturebeat-ai,aws-ml` | Turns sources off (ids are listed in `backend/config/sources.toml`). |
| `LLM_MAX_CALLS_PER_DAY` | `60` | Caps daily AI calls (Gemini default 90). |
| `LLM_MAX_CALLS_PER_RUN` | `4` | Caps AI calls per 15-minute run (Gemini default 6). |
| `LLM_MODEL` | `gemini-3.5-flash` | Forces a specific model instead of auto-selection. |

Secrets (same page, **Secrets** tab): `GEMINI_API_KEY`, or `LLM_API_KEY` for a Groq/xAI/OpenAI/Anthropic key.
