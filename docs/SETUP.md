# Setup & launch checklist

Items marked ⏳ involve a platform review that takes days to weeks — **start those first**.

## 1. Where everything runs (100% cloud — no local PC, no server)

| Piece | Service | Role |
|---|---|---|
| Code + secrets | **GitHub**, public repo `cloudstrive6/tfs-social-media-and-video-automation` | public = free Actions minutes; secrets are GitHub repository secrets |
| Trigger | **cron-job.org** | calls GitHub's `workflow_dispatch` API for `run.yml` every 30 min (:25 and :55 PHT) |
| Production + publishing | **GitHub Actions** `run` workflow | restore state → publish → scout/plan/produce → save state (section 10) |
| State between runs | **Cloudflare R2**, a private bucket | DB, analyst notes, and media of items not yet posted; a dated DB backup each day |
| Publishing | YouTube + Meta direct, TikTok via **Post for Me** | section 6 |
| Alerts | **Telegram** bot | every finished post (with its images/video), every go-live, every failure |

Public-repo rules: never put a secret, email address or rendered media in the repo, in workflow logs or in
artifacts. Workflows never dump all secrets at once (`toJSON(secrets)`); `_run.yml` maps each one by name.
Commit as `cloudstrive6@users.noreply.github.com`.

Optional brand assets, committed to the repo (the pipeline works without them):
- `assets/fonts/Anton-Regular.ttf`, `assets/fonts/Montserrat-ExtraBold.ttf` (Google Fonts, OFL)
- `assets/logo.png` (transparent), `assets/music/*.mp3` (royalty-free beds — YouTube Audio Library)
- `assets/characters/*.png` — the cast's model sheets (made with `make-characters`), which keep the recurring
  characters consistent across AI images

## 2. Brains — Claude Max subscription
The agents run through the Claude Code CLI on the Actions runner (`llm.backend: claude_code`).
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

## 5. State — Cloudflare R2 (required)
Each Actions run starts on a blank machine, so the state lives in a private R2 bucket (free up to 10 GB).
Media of finished items is pruned from R2 after 10 days; their text files stay.
1. In the Cloudflare dashboard, go to R2 Object Storage, then Create bucket: `tfs-state`, location hint Asia-Pacific.
   Leave it private.
2. Go to R2, then Manage API tokens, then Create **Account** API token:
   - Permission: Object Read & Write.
   - Apply to: the `tfs-state` bucket only.
3. Set four GitHub secrets:
   - `S3_ENDPOINT_URL`: `https://<account id>.r2.cloudflarestorage.com`
   - `S3_BACKUP_BUCKET`: `tfs-state`
   - `S3_ACCESS_KEY_ID` and `S3_SECRET_ACCESS_KEY`: from the token page (shown once).

`tfs run` refuses to start without it, because without saved state every run would re-plan and re-post the same slots.

## 6. Publishing
| Platform | How | Setup |
|---|---|---|
| YouTube + Shorts | direct, Google Cloud project `tfs-automation` | section 7 |
| Facebook + Instagram | direct, Meta app **TFS Content Creator** (App ID 4222661254707523, classic Business-type app in Development mode, created 2026-09-26 on the Whop Clipper pattern; separate from TFS Publisher, which Post for Me uses) | section 6a |
| TikTok | Post for Me Quickstart project (approved TikTok app, public posts) | section 6b |

### 6a. Meta app "TFS Content Creator"
Do not touch **TFS Publisher**; it's connected to Post for Me.
1. Created with Meta's "Other" option (the old, classic experience) → type Business, with no products and no
   business portfolio, the same as the working Whop Clipper apps. It stays in **Development mode**. It's used only by you (an app admin) on your own Page and Instagram
   account, so no App Review or Live switch is needed.
2. Get a Page token:
   - In the Graph API Explorer (app TFS Content Creator, User Token), add these permissions (all Standard access,
     no App Review): `pages_show_list, pages_read_engagement, pages_manage_posts, publish_video, instagram_basic,
     instagram_content_publish, instagram_manage_insights, read_insights, business_management`. Click Generate Access Token and approve for
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
   - Authorize with the Google account that owns the channel, then "Exchange authorization code for tokens".
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

## 9. Alerts — Telegram
Message @BotFather → new bot → `TELEGRAM_BOT_TOKEN`. Send the bot "hi", then run the **telegram-setup**
workflow. It prints your chat id for `TELEGRAM_CHAT_ID` and sends a test message.

## 10. Automation — cron-job.org → GitHub Actions
`run.yml` is in the concurrency group `tfs-state`, so two runs never touch the state at once. A trigger that
arrives mid-run waits, and a newer trigger replaces an older waiting one. Every run does the same work, so
nothing is lost. Inside a run:
- A publisher thread publishes every minute, so a long render never delays a post.
- A run stays up for any Facebook/Instagram post due in the next 35 minutes, because Meta has no API
  scheduling and those posts go out at the exact minute.
- YouTube (`publishAt`) and TikTok (Post for Me `scheduled_at`) are handed over as soon as they're produced.

Setup:
1. GitHub → Settings → Developer settings → **Fine-grained personal access tokens** → Generate:
   - Name: `cron-job.org TFS run`
   - Expiration: 1 year
   - Repository access: only `tfs-social-media-and-video-automation`
   - Permissions: **Actions: Read and write** (Metadata: read-only is added automatically)
2. cron-job.org → Create cronjob:
   - Title: `TFS run (every 30 min)`
   - URL: `https://api.github.com/repos/cloudstrive6/tfs-social-media-and-video-automation/actions/workflows/run.yml/dispatches`
   - Schedule: custom, minutes 25 and 55 of every hour, time zone Asia/Manila
   - Advanced → Request method: POST
   - Headers:
     - `Accept: application/vnd.github+json`
     - `Authorization: Bearer <the token>`
     - `X-GitHub-Api-Version: 2022-11-28`
   - Request body: `{"ref":"main"}`
   - A successful call returns **204 No Content**.
3. Logs: GitHub → Actions → run. When the token nears expiry, generate a new one and update the cronjob header.

## 11. First run
Run **verify** (every credential), then **run** once by hand from GitHub → Actions. The first run scouts,
plans the next ~8 hours of slots and starts producing; Telegram shows each post as it's ready and again when
it's live. Watch the first week before trusting it blind.
