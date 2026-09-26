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
            publish/ (YouTube, Meta, Post for Me for TikTok), state.py (R2), pipeline.py (orchestrator), cli.py
.github/    run (the automation), verify, preview-styles, telegram-setup, ci; all go through _run.yml
```

Everything runs in the cloud, with no server to maintain:
- **cron-job.org** starts the GitHub Actions `run` workflow every 30 minutes.
- **GitHub Actions** does the work: scouting, writing, rendering and publishing.
- **Cloudflare R2** keeps the state between runs.

This repo is public, which is what makes GitHub Actions free. It holds no secrets: those live in GitHub
repository secrets, each one mapped by name in `.github/workflows/_run.yml`.

## Commands
The `run` workflow calls `tfs run`. Everything else is for running by hand or for debugging.

| | |
|---|---|
| `tfs run` | restore state from R2 → publish what's due (and keep publishing every minute) → scout / plan / produce → save state |
| `tfs tick` / `tfs publish` | one production step / one publish pass, on the local state only |
| `tfs scout` / `tfs plan` / `tfs produce <id>` | run a stage by hand |
| `tfs status` | items and per-platform post status |
| `tfs retry <post_id>` / `tfs requeue <id>` | recover failures |
| `tfs analyze` | weekly growth report + agent notes (runs itself Mondays 09:00 PHT inside `tfs run`) |
| `tfs verify` | checks every credential; prints names only |
