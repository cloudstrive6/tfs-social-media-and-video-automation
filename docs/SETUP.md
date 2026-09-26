# Setup & launch checklist

Items marked ⏳ involve a platform review that takes days to weeks — **start those first**.

## 1. Where everything runs (100% cloud — no local PC)

| Piece | Service | Role |
|---|---|---|
| Code + secrets + deploys | **GitHub** (private repo) | push to `main` → tests → Docker image → deployed to the VM |
| Production + publishing | **Cloud VM** running Docker | cron inside the container: `tick` every 15 min, `publish` every 5 min, `analyze` Mondays 09:00, `backup` nightly (all PHT) |
| Publishing | **Post for Me** | uploads + schedules every post on YouTube, Instagram, Facebook, TikTok |
| Backups | **Cloudflare R2** | private bucket for nightly state backups |
| Approvals / manual control | **GitHub Actions → `command`** (works in the GitHub mobile app) + Telegram alerts | `approve <id>`, `reject <id>`, `retry <post>`, `status` |

**VM:** 8 vCPU / 16 GB / 160 GB SSD, Ubuntu 24.04, in Singapore for low latency to PH, e.g. Hetzner Cloud
CPX41 (~€30/mo) or a DigitalOcean CPU-optimised droplet (~$84/mo). One-time prep over the provider's
**web console** (no local tools needed):
```bash
curl -fsSL https://get.docker.com | sh
mkdir -p /opt/tfs
# add the deploy public key to ~/.ssh/authorized_keys (generate the key pair in the provider console or Cloud Shell)
```
GitHub repository secrets: every variable from `.env.example`, plus `VM_HOST`, `VM_USER`, `VM_SSH_KEY`
(private key). Push to `main` and the `deploy` workflow does the rest.

Optional brand assets, committed to the repo (the pipeline works without them):
- `assets/fonts/Anton-Regular.ttf`, `assets/fonts/Montserrat-ExtraBold.ttf` (Google Fonts, OFL)
- `assets/logo.png` (transparent), `assets/music/*.mp3` (royalty-free beds — YouTube Audio Library)
- `assets/characters/juan.png`, `tito_trapo.png`, `kuya_standard.png` — reference sheets that keep
  recurring characters consistent across AI images

## 2. Brains — Claude Max subscription
The agents run through the Claude Code CLI inside the container (`llm.backend: claude_code`).
1. On any machine where you're signed in to Claude Code with the Max account, run `claude setup-token`,
   approve in the browser, and copy the one-year token straight into the GitHub secret
   `CLAUDE_CODE_OAUTH_TOKEN` (never paste it into chats or commit it). Anthropic's Claude Code docs describe
   this token for "CI pipelines and scripts where browser login isn't available".
2. Usage limits: Max has rolling 5-hour and weekly limits. When one is hit, the item stays queued and
   retries on the next tick. If `ANTHROPIC_API_KEY` is also set, that call falls back to pay-per-use
   instead, so no slot is missed.
3. To stretch the subscription, switch high-volume agents (trend_scout, seo_writer, visual_director,
   carousel_designer) to `claude-sonnet-5` in `config/channel.yaml`.
4. Check that using a personal subscription for a commercial channel's automation fits Anthropic's current
   consumer terms (anthropic.com/legal). For clean, uncapped billing, set `llm.backend: api` and use a
   Console API key (~$275/month at this volume).

## 3. Narrator — ElevenLabs
1. Creator plan to test, Scale for full volume.
2. Best result: **Professional Voice Clone** of a real Filipino narrator (yourself or a hired voice actor
   with a written licence). 30+ min of clean Taglish reading → a voice nobody can call robotic.
   Or pick a Filipino voice from the Voice Library.
3. `ELEVENLABS_VOICE_ID`, optional `ELEVENLABS_VOICE_JUAN`, `ELEVENLABS_VOICE_TITO_TRAPO` for skit characters.
4. Try `model_id: eleven_v3` in `config/channel.yaml` for more expressive delivery (supports `[laugh]`, `[whisper]`).

## 4. Images — Google AI Studio
API key → `GEMINI_API_KEY` (billing enabled; free tier is too small).

## 5. Backups — Cloudflare R2 (free tier)
Create a **private** bucket `tfs-backups` and an API token; fill `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`,
`S3_SECRET_ACCESS_KEY`, `S3_BACKUP_BUCKET`. (A public media bucket is only needed if you ever switch
`publishing.provider` to `direct`.)

## 6. Publishing — Post for Me (all platforms)
1. Sign up at postforme.dev (Pro, $10/month = 1,000 posts; we publish ~510/month).
2. Create a **Quickstart** project, which posts through Post for Me's already-approved platform apps. That means:
   - no YouTube API audit or upload quota for us;
   - TikTok posts are public without our own TikTok audit;
   - no Meta developer app to set up.
3. In the Post for Me dashboard, connect YouTube (@TheFilipinoStandard), the Facebook Page, Instagram
   (a Professional account linked to the Page) and, later, TikTok.
4. API key → `POSTFORME_API_KEY`. When TikTok is connected, set `tiktok.enabled: true` in `config/schedule.yaml`.

## 7. Google Cloud project (trend data + analytics)
Uploads don't go through our project, so the default quota is plenty. It's used for:
1. **YouTube Data API v3**, via an API key → `YOUTUBE_API_KEY` (the Trend Scout reads PH trending videos).
2. **YouTube Analytics API**, via OAuth → the Growth Analyst reads CTR, retention and subscriber data:
   - Create an OAuth client of type *Web application* with the authorized redirect URI
     `https://developers.google.com/oauthplayground` → `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET`.
   - Open the **OAuth 2.0 Playground** → ⚙️ "Use your own OAuth credentials".
   - Select scopes `youtube.readonly` and `yt-analytics.readonly`, then authorize with the channel's Google account.
   - Click "Exchange authorization code for tokens" and copy the refresh token → `YOUTUBE_REFRESH_TOKEN`.
   - Set the consent screen's publishing status to **In production**, or the token expires after 7 days.
3. In YouTube Studio, enable advanced features (phone verification) so custom thumbnails and >15-minute
   videos work.

## 8. Direct platform APIs (optional, not needed with Post for Me)
`src/tfs/publish/youtube.py`, `meta.py` and `tiktok.py` remain as a fallback. You can switch one platform
with `publishing.overrides` in `config/channel.yaml`. Each one then needs its own audit and approvals
(YouTube compliance audit + quota, Meta app, TikTok audit).

## 9. Approvals & alerts — Telegram
Message @BotFather → new bot → `TELEGRAM_BOT_TOKEN`; send the bot a message, read your chat id from
`https://api.telegram.org/bot<token>/getUpdates` → `TELEGRAM_CHAT_ID`.

## 10. Automation
Nothing to install: the container's cron is the scheduler (`deploy/crontab`). Producing and publishing use
separate locks, so a long render never delays a post. Logs: provider console → `docker logs -f tfs-tfs-1`.

## 11. First run (before going public)
From GitHub → Actions → **command** → Run workflow: `scout`, then `plan`, then `status`.
Until the YouTube audit clears, uploads stay private anyway — use that week to review every output in
YouTube Studio and on the other platforms.
Watch the first week's output personally. Tighten prompts, voice settings and schedule, *then* switch on
the full cadence.
