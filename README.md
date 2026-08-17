# six-seven-bot 🔢

A gloriously silly Telegram bot. Add it to a group chat and it watches every
photo, video, video note ("bubble"), and GIF for the numbers **6 and 7
together** — as digits (`67`, `6 7`, `6-7`), or the words **"six seven"**. Every
hit bumps the sender's running counter, and `/top` shows who sends the most.

## How it works

```
media message ──► sample frames ──► [1] local OCR (EasyOCR)  ──match──► count++
                                     │
                                     └─ no match ──► [2] GPT-4o vision ──match──► count++
```

**Hybrid detection.** Every frame is first read locally with EasyOCR (free, runs
entirely on your VPS). Only frames OCR can't read are escalated to GPT-4o's
vision model — which catches stylized, handwritten, or meme-format "6 7" that
OCR misses. Videos and GIFs are sampled at evenly-spaced frames; one hit per
message is enough (a video full of 6 7s counts once). With no `OPENAI_API_KEY`
set, the bot runs OCR-only.

## Commands

| Command | What it does |
|---|---|
| `/top` | Top six-seveners in this chat |
| `/me` | Your own count |
| `/notify` | Change notification mode (instant, daily, quiet) |
| `/reset` | Reset leaderboard — manual or auto (admin only) |
| `/dispute` | Reply to a 67 award to challenge it → group vote (3 votes within 5 min overturn the point) |
| `/start`, `/help` | How the bot works |

### Reset options

- **Manual:** `/reset now` → confirms with `/reset confirm` within 30s
- **Auto:** `/reset daily` | `/reset weekly` | `/reset monthly` | `/reset off`
- Auto-resets run at midnight (daily), Monday (weekly), or the 1st (monthly)

## Quick start (local)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # add your TELEGRAM_BOT_TOKEN
python -m sixseven
```

Get a token from [@BotFather](https://t.me/BotFather), and **disable privacy
mode** (`/setprivacy` → Disable) so the bot can see group media.

## Configuration

All via environment variables (or a `.env` file):

| Variable | Default | Meaning |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | **Required.** BotFather token |
| `OPENAI_API_KEY` | — | Enables the vision escalation layer |
| `SIXSEVEN_VISION_MODEL` | `gpt-4o` | Vision model for escalated frames |
| `SIXSEVEN_OCR_ENABLED` | `true` | Toggle the local OCR pass |
| `SIXSEVEN_OCR_LANGS` | `en` | Comma-separated EasyOCR languages |
| `SIXSEVEN_VIDEO_FRAMES` | `4` | Frames sampled per video/GIF |
| `SIXSEVEN_VISION_MAX_FRAMES` | `1` | Frames escalated to vision per message |
| `SIXSEVEN_DB_PATH` | `sixseven.db` | SQLite database path |
| `SIXSEVEN_MAX_FILE_MB` | `20` | Skip files larger than this |

## Deploying to a VPS

The bot runs in a Docker container with `--restart unless-stopped`:

```bash
docker build -t six-seven-bot .
docker run -d --name six-seven-bot --restart unless-stopped \
  --env-file .env \
  -v /root/.EasyOCR:/root/.EasyOCR \
  -v /path/to/data:/data \
  six-seven-bot
```

EasyOCR pulls in PyTorch (~1–2 GB in the image) — give the box ≥ 2 GB RAM.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The matcher, storage, and dedup layers are covered by fast, dependency-free unit tests.

## Project layout

```
src/sixseven/
  matcher.py    # pure "is this a six seven?" logic
  ocr.py        # EasyOCR wrapper (lazy, graceful degradation)
  vision.py     # OpenAI vision escalation
  media.py      # download -> frame extraction
  storage.py    # SQLite per-chat/per-member counters + dedup + reset
  detector.py   # orchestrates OCR -> vision -> match
  bot.py        # Telegram handlers & commands
  config.py     # env-based configuration
  __main__.py   # entry point
```

## License

MIT — see [LICENSE](LICENSE).