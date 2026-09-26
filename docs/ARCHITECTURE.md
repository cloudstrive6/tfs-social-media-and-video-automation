# Architecture

## The agent team

| # | Agent | Prompt | Does | Output |
|---|---|---|---|---|
| 1 | **Trend Scout** | `prompts/trend_scout.md` | Every 3 h: pulls Google Trends PH, 5 news feeds, X/Twitter PH trends, YouTube + Google autocomplete for 13 seed keywords, Reddit (optional), YouTube mostPopular PH (optional), and the civic calendar. Stores every value so the next run can measure **acceleration**, then ranks topics that are about to peak. | `topics` table |
| 2 | **Editor-in-Chief** | `editor_in_chief.md` | When a slot enters the production window (≈8 h ahead), assigns the freshest fitting topic, balancing pillar mix and avoiding repeats. | brief per item |
| 3 | **Researcher** | `researcher.md` | Anthropic web search (≤25 searches), primary sources first. Timeline, facts with `[S#]` citations, people (established vs. alleged), surprising angles, historical roots. | `dossier.md` |
| 4 | **Head Writer** | `scriptwriter.md` | Historically-style script in Taglish: cold-open skit → pop-quiz hook → "Standard Issue #N" → chapters with open loops → system reveal → callback ending. Scene-by-scene with visual cues. | `script_r*.json` |
| 5 | **Hook Master** | `hook_master.md` | Retention psychologist: rewrites first 5 s, re-hooks at 0:30 / 1:30 / 25 / 50 / 75 %, scores hook & retention. Below 8/10 → sent back to the writer (max 3 drafts, then the slot is skipped). | `hook_r*.json` |
| 6 | **Fact-Check & Legal** | `fact_checker.md` | Checks every line against the dossier, enforces cyber-libel rules, flags content naming living people with allegations → **human approval** via Telegram. | `factcheck.json` |
| 7 | **Visual Director** | `visual_director.md` | One visual per scene: AI illustration, motion-graphic card (stat / quote / timeline / document / place), or reuse; camera move. | `shots.json` |
| 8 | **Narrator** | (code: `media/tts.py`) | ElevenLabs per scene with request stitching for natural flow, word timestamps for captions, optional separate character voices for skits. Fish Audio as a cheaper alternative. | `audio/*.mp3` |
| 9 | **Video Editor** | (code: `media/render.py`) | FFmpeg: Ken-Burns shots timed to narration, music bed, loudness-normalised to −14 LUFS, burned word captions + hook text on verticals, SRT, chapters. | `video.mp4` |
| 10 | **Thumbnail Artist** | `thumbnail_artist.md` | 3 ranked concepts (one frozen ironic moment, no text by default), generates the art, composites 1280×720. | `thumbnail.jpg` |
| 11 | **Title Writer** | `title_writer.md` | 10 options scored for curiosity / clarity / keyword / honesty; primary + 2 alternates for later swaps. | `titles.json` |
| 12 | **SEO & Discovery Writer** | `seo_writer.md` | Description written for YouTube search *and* AI answer engines, chapters, sources, tags, and native captions for Shorts / IG / FB / TikTok. | `seo.json` |
| 13 | **Carousel Designer** | `carousel_designer.md` | 6–10 slide scroll-stoppers (cover hook, one idea per slide, "so what", CTA), fact-checked, rendered 1080×1350. | `slides/*.jpg` |
| 14 | **Publisher** | (code: `publish/youtube.py`, `publish/postforme.py`) | YouTube + Shorts upload directly through the TFS Automation Google Cloud project with native `publishAt` scheduling, custom thumbnail and the synthetic-media flag. IG Reels & carousels and FB Reels & multi-photo posts go direct through the Meta app TFS Content Creator at the slot time. TikTok (public, AI-generated label) goes through Post for Me with `scheduled_at` = slot, and each result is confirmed afterwards. | `posts` table |
| 15 | **Growth Analyst** | `analyst.md` | Weekly: YouTube Analytics + IG insights → what worked, standing notes appended to every agent's prompt, schedule retune, title swaps on low-CTR videos. | `analyst_notes/` |

Every agent's system prompt = `docs/STYLE_BIBLE.md` + its role prompt + the analyst's standing notes
(prompt-cached, so the shared prefix is billed at the cache rate).

## Flow

```mermaid
flowchart LR
  subgraph every3h[every 3 h]
    S[Trend Scout] --> T[(topic pool)]
  end
  subgraph every15[every 15 min: tfs tick]
    T --> E[Editor-in-Chief] --> R[Researcher] --> W[Head Writer] --> H{Hook Master ≥ 8/10?}
    H -- no, notes --> W
    H -- yes --> F{Fact-Check & Legal}
    F -- names a person + allegation --> A[/Telegram: tfs approve/] --> F2[continue]
    F -- pass --> V[Visual Director] --> I[Images + cards] --> N[Narrator] --> ED[Video Editor]
    ED --> P[Thumbnail + Titles + SEO] --> Q[(posts queue)]
    F -- carousel --> C[Carousel Designer] --> Q
  end
  subgraph every5[every 5 min: tfs publish]
    Q --> YT[YouTube / Shorts via Data API, publishAt = slot]
    Q --> META[Meta Graph API, at slot] --> IG[Instagram] & FB[Facebook]
    Q --> PFM[Post for Me, scheduled_at = slot] --> TT[TikTok]
  end
  YT & IG --> AN[Growth Analyst weekly] -.notes & schedule.-> E & W & H & P
```

## Daily output (config/schedule.yaml)

| Produced | Published as |
|---|---|
| 1 long-form (10–16 min, 16:9) — scale later by adding slots | 1 × YouTube long-form (18:00 PHT) |
| 3 verticals (35–58 s, 9:16) | 3 × Shorts, 3 × IG Reels, 3 × FB Reels, 3 × TikTok — same master, staggered times, platform-native captions |
| 2 carousels (1080×1350) | 2 × IG carousel, 2 × FB multi-photo post |

## Reliability

- **Checkpointed**: every step writes its artifact to `TFS_DATA_DIR/items/<id>/`; a crash or approval pause resumes where it stopped.
- **Skip, don't ship junk**: failing the quality bar, a fact-check reject, or missing the first slot → the slot is skipped and you're notified.
- **Producer and publisher are separate** cron jobs with separate locks, so a 40-minute render never makes an
  Instagram post late.
- **Fully cloud**: Docker container on a cloud VM (cron inside), deployed from GitHub on every push; state on a
  persistent volume, backed up nightly to a private R2 bucket; remote control via the GitHub `command` workflow.
- All times are Asia/Manila.

## Running costs (1 long-form + 3 verticals + 2 carousels a day; Sep 2026 list prices — verify)

| Item | Basis | ≈ / month |
|---|---|---|
| Claude — Max subscription via Claude Code (default) | flat plan, within its 5-hour/weekly usage limits | the Max plan you already pay |
| … or Claude API (`llm.backend: api`) | ~$3.5 per long-form, ~$1.2 per vertical, ~$1 per carousel incl. web search | ~$275 |
| ElevenLabs narration | ~430k characters/month (multilingual v2) → Pro tier (500k) | ~$99 |
| Images (Gemini 2.5 Flash Image, ~$0.04 each) | ~130 images/day | ~$160 |
| Post for Me (TikTok only) | ~90 posts/month | $10 |
| Cloud VM (Docker, Singapore) | 8 vCPU / 16 GB | $30–85 |
| Cloudflare R2 backups | < 1 GB | ~$0 |
| **Total** | | **≈ $300–355 + your Max plan** (≈ $575–630 with the API instead) |

Each extra daily long-form adds roughly $200/month (Claude ~$105, images ~$100, and ElevenLabs moves up to the Scale tier after the second).
