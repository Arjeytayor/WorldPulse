# Deploying WorldPulse as a daily automated run

The pipeline runs once per day at **07:00 WAT** as a stress test — the point is
to catch breakage early rather than discover months later that it degraded
quietly. This document is the runbook for putting it on an always-on box.

## Why a VM and not GitHub Actions

`cache/` and `vector_index/` are gitignored and **stateful** — `vector_store.py`
embeds every published topic so `pick_best_topics()` can filter tomorrow's
duplicates against them (`DUPLICATE_THRESHOLD = 0.92`). Ephemeral CI runners
start empty every run, so dedup would reset daily and the pipeline would happily
re-cover the same story forever. A VM with a persistent disk keeps that state
without any extra machinery.

A laptop with Task Scheduler also preserves state, but only runs when the laptop
is awake — a missing run becomes ambiguous between "machine asleep" and
"pipeline broken", which destroys the signal the daily run exists to produce.

## Target

**Oracle Cloud Always Free**, Ampere A1 (ARM), Ubuntu 22.04.

Sizing against what this actually needs: `vector_store.py` lazy-loads
`sentence-transformers`, which pulls PyTorch — ~496 MB on disk, ~400–500 MB
resident once imported. Always Free A1 gives up to 4 OCPU / 24 GB RAM / 200 GB,
so roughly 50× headroom.

> **Capacity warning.** Always Free A1 shapes are frequently unavailable
> ("Out of host capacity") in popular regions and can take days of retries.
> The AMD micro shape (1/8 OCPU, 1 GB RAM) is always available and will work,
> but 1 GB is tight once PyTorch is resident — expect it to be slow, not broken.

## Provision

```bash
sudo timedatectl set-timezone Africa/Lagos
sudo apt update && sudo apt install -y python3.11 python3.11-venv git

git clone https://github.com/Arjeytayor/WorldPulse.git
cd WorldPulse                       # note: default branch is `master`, not `main`
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

The first `pip install` is slow — PyTorch is a large aarch64 wheel.

## Secrets

**The GitHub repo is public. `.env` is gitignored and must never be committed.**
Create it by hand on the box:

```bash
cp .env.example .env
nano .env
```

Four values are required. Copy them from your local
`C:\Users\DELL\Documents\WorldPulse\.env`:

| Key | Purpose |
|---|---|
| `NVIDIA_NIM_API_KEY` | LLM provider |
| `NIM_BASE_URL` | `https://integrate.api.nvidia.com/v1` |
| `TELEGRAM_BOT_TOKEN` | delivery + failure alerts |
| `TELEGRAM_CHAT_ID` | your chat |

Then `chmod 600 .env`.

## Schedule

Use cron rather than running `main.py` as a systemd service. Each run is a fresh
process, so a hang or a leak cannot poison the next day's run.

```bash
crontab -e
```

```cron
0 7 * * * cd ~/WorldPulse && .venv/bin/python run_once.py >> logs/cron.log 2>&1
```

`run_once.py` exits **1** on failure and **0** on success, so cron records a real
result. On failure it also sends a Telegram alert with the exception type and
message — a stress test you have to remember to check is one you will stop
checking.

## Verify the deployment

1. **One manual run.** `cd ~/WorldPulse && .venv/bin/python run_once.py; echo $?`
   Expect `0`, files under `outputs/`, and the Telegram briefing card.
   The first run downloads `all-MiniLM-L6-v2` (~90 MB) to the HF cache and will
   be noticeably slower than later ones.
2. **Prove cron fires.** Temporarily set the schedule to `*/5 * * * *`, wait for
   one automatic run, confirm `logs/cron.log` grew, then restore `0 7 * * *`.
3. **Prove state persists.** The morning after the second run, confirm
   `vector_index/` has grown. That is the evidence dedup is carrying across
   runs — the whole reason for choosing a VM.

## Operating notes

- Oracle reclaims Always Free compute left idle ~7 days. A daily cron keeps it
  active.
- `logs/cron.log` grows without bound; `cleanup_old_cache(days=7)` only prunes
  the research cache. Add logrotate if it becomes an issue.
- NVIDIA retires NIM models on a rolling basis — five died between Jul 20 and
  Aug 7, 2026. When output quality drops or alerts fire, re-check the pool:
  ```bash
  .venv/bin/python -c "import nim_client; print(nim_client.health_check())"
  ```
  A retired model returns `410 Gone` with its EOL date in the message. Replace
  it in `MODEL_POOL` (`nim_client.py`) and redeploy.
- `POST_SUBSTACK` and `POST_X` stay `false`. The daily run exercises generation
  and delivery, not public posting.
