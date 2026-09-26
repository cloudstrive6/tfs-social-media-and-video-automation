# The Filipino Standard — content automation

An agent team that finds Philippine topics before they peak, researches them, writes
Historically-style Taglish scripts engineered for retention, fact-checks them against cyber-libel
risk, narrates, illustrates, edits and publishes to YouTube, Shorts, Instagram, Facebook and TikTok
on a fixed daily schedule — then studies the analytics and retunes itself weekly.

- **What we're copying and why:** [docs/STYLE_BIBLE.md](docs/STYLE_BIBLE.md)
- **Agents, flow, costs:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Accounts, keys, go-live:** [docs/SETUP.md](docs/SETUP.md)

```
config/     channel (brand, models, quality gates, voice, image style), schedule (PHT slots), sources
prompts/    one system prompt per agent
src/tfs/    agents/ (Claude), media/ (TTS, images, cards, FFmpeg render, thumbnails, slides),
            publish/ (Post for Me for all platforms; direct YouTube/Meta/TikTok fallback; R2 backups), pipeline.py (orchestrator), cli.py
deploy/     crontab (tick 15 min, publish 5 min, analyze weekly, backup nightly) + docker-compose
.github/    deploy (push → test → image → cloud VM), command (remote control), ci
```

Everything runs in the cloud: a Docker container on a cloud VM with cron inside, deployed from GitHub.

## Commands
Run from GitHub → Actions → **command**, or automatically by cron in the container.

| | |
|---|---|
| `tfs tick` | scout if stale → plan slots in the next ~8 h → produce the next item |
| `tfs publish` | publish every post whose time has come |
| `tfs scout` / `tfs plan` / `tfs produce <id>` | run a stage by hand |
| `tfs status` | items and per-platform post status |
| `tfs approve <id>` / `tfs reject <id>` | answer a legal-review request |
| `tfs retry <post_id>` / `tfs requeue <id>` | recover failures |
| `tfs analyze` | weekly growth report + agent notes |
| `tfs backup` | snapshot the state DB to the private R2 bucket (runs nightly) |
