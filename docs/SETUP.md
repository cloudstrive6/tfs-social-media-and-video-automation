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

## 5. Backups — Cloudflare R2 (optional)
A private bucket for nightly database backups (`S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`,
`S3_BACKUP_BUCKET`). Without it, the backup job just skips.

## 6. Publishing
| Platform | How | Setup |
|---|---|---|
| YouTube + Shorts | direct, Google Cloud project `tfs-automation` | section 7 |
| Facebook + Instagram | direct, Meta app **TFS Content Creator** (App ID 2122587118630314, created 2026-09-26; separate from TFS Publisher, which Post for Me uses) | section 6a |
| TikTok | Post for Me Quickstart project (approved TikTok app, public posts) | section 6b |

### 6a. Meta app "TFS Content Creator"
Do not touch **TFS Publisher**; it's connected to Post for Me.
1. The app stays in **Development mode**. It's used only by you (an app admin) on your own Page and Instagram
   account, so no App Review or Live switch is needed.
2. Get a Page token:
   - In the Graph API Explorer (app TFS Content Creator, User Token), add these permissions: `pages_show_list,
     pages_read_engagement, pages_manage_posts, publish_video, instagram_basic, instagram_content_publish,
     instagram_manage_insights, read_insights, business_management`. Click Generate Access Token and approve for
     The Filipino Standard Page and Instagram account.
   - In the Access Token Debugger, click **Extend Access Token** to get a long-lived user token.
   - Back in the Explorer, with that long-lived token, run
     `me/accounts?fields=name,id,access_token,instagram_business_account`.
   - Copy the Page's `access_token` (this Page token never expires) → `META_PAGE_ACCESS_TOKEN`,
     `id` → `META_PAGE_ID`, and `instagram_business_account.id` → `META_IG_USER_ID`.
3. No media bucket is needed. Reels upload straight to Meta, and carousel images go through unpublished Page photos.

### 6b. TikTok via Post for Me
Quickstart project ("New Project"): connect @thefilipinostandard under Social Media Accounts, then put that
project's API key in `POSTFORME_API_KEY` and set `tiktok.enabled: true` in `config/schedule.yaml`.

## 7. YouTube — Google Cloud project "TFS Automation" (uploads, analytics, trends)
Created 2026-09-26: YouTube Data API v3 and YouTube Analytics API are enabled, the External consent screen
is configured, and it has an OAuth client "TFS Analytics (OAuth Playground)" (Web) and an API key
"TFS trend scout" restricted to the YouTube Data API.
1. OAuth client ID/secret → `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET`; API key → `YOUTUBE_API_KEY`.
2. Google Auth Platform → **Audience → Publish app** (to "In production"). In Testing mode, refresh tokens
   expire after 7 days. The app is unverified, so the consent screen shows a warning; that's fine for your own channel.
3. Refresh token via the **OAuth 2.0 Playground**:
   - ⚙️ → "Use your own OAuth credentials".
   - Scopes: `https://www.googleapis.com/auth/youtube.upload`, `https://www.googleapis.com/auth/youtube.readonly`,
     `https://www.googleapis.com/auth/yt-analytics.readonly`.
   - Authorize as cloudstrive1688@gmail.com (the channel owner), then "Exchange authorization code for tokens".
   - Copy the refresh token → `YOUTUBE_REFRESH_TOKEN`.
4. No audit needed in practice. Google's docs say uploads from unaudited projects created after July 2020 are
   locked as private, but a comparable project (External, In production, unverified, default quota) was checked
   on 2026-09-26: 24 API uploads in 30 days were all public, with normal views. As a safeguard, the pipeline checks
   each YouTube upload after its slot. If one is still private 2 h later, you get a Telegram alert and can switch
   YouTube to Post for Me with `publishing.overrides.youtube: postforme` (and `youtube_shorts`).
5. Quota: uploads use their own "Video Uploads per day" limit (100/day). Thumbnails and status checks use the
   regular 10,000 units/day. 4 uploads/day is far below both.
6. In YouTube Studio, enable advanced features (phone verification) so custom thumbnails and >15-minute
   videos work.

## 8. Direct Meta / TikTok APIs (optional fallback)
`src/tfs/publish/meta.py` and `tiktok.py` remain; switch a platform with `publishing.overrides`.

## 9. Approvals & alerts — Telegram
Message @BotFather → new bot → `TELEGRAM_BOT_TOKEN`; send the bot a message, read your chat id from
`https://api.telegram.org/bot<token>/getUpdates` → `TELEGRAM_CHAT_ID`.

## 10. Automation
Nothing to install: the container's cron is the scheduler (`deploy/crontab`). Producing and publishing use
separate locks, so a long render never delays a post. Logs: provider console → `docker logs -f tfs-tfs-1`.

## 11. First run (before going public)
From GitHub → Actions → **command** → Run workflow: `scout`, then `plan`, then `status`.
Watch the first week's uploads in YouTube Studio and on the other platforms before scaling up.
Watch the first week's output personally. Tighten prompts, voice settings and schedule, *then* switch on
the full cadence.
