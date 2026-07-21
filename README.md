# six-seven-bot 🔢

A gloriously silly Telegram bot. Add it to a group chat and it watches every
photo, video, video note ("bubble"), GIF, and sticker for the numbers **6 and
7 together** — as digits (`67`, `6 7`), or the words **"six seven"**. Every hit
bumps the sender's running counter, and `/leaderboard` shows who sends the most.

## How it works

```
media message ──► sample frames ──► [1] local OCR (EasyOCR)  ──match──► count++
                                     │
                                     └─ no match ──► [2] Claude vision ──match──► count++
```

**Hybrid detection.** Every frame is first read locally with EasyOCR (free, runs
entirely on your VPS). Only frames OCR can't read are escalated to a Claude
vision model — which catches stylized, handwritten, or meme-format "6 7" that
OCR misses. Videos, GIFs, video notes, and video stickers are sampled at a few
evenly-spaced frames; one hit per message is enough (a video full of 6 7s counts
once). With no `ANTHROPIC_API_KEY` set, the bot happily runs OCR-only.

## Commands

| Command | What it does |
|---|---|
| `/leaderboard` (also `/scoreboard`, `/sixseven`) | Top six-seveners in this chat |
| `/me` | Your own count |
| `/start`, `/help` | How the bot works |

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
| `ANTHROPIC_API_KEY` | — | Enables the vision escalation layer |
| `SIXSEVEN_VISION_MODEL` | `claude-haiku-4-5` | Vision model for escalated frames |
| `SIXSEVEN_OCR_ENABLED` | `true` | Toggle the local OCR pass |
| `SIXSEVEN_OCR_LANGS` | `en` | Comma-separated EasyOCR languages |
| `SIXSEVEN_VIDEO_FRAMES` | `4` | Frames sampled per video/GIF |
| `SIXSEVEN_VISION_MAX_FRAMES` | `1` | Frames escalated to vision per message |
| `SIXSEVEN_DB_PATH` | `sixseven.db` | SQLite database path |
| `SIXSEVEN_MAX_FILE_MB` | `20` | Skip files larger than this (Telegram caps bot downloads at 20 MB) |
| `SIXSEVEN_SCAN_STICKERS` | `true` | Scan stickers too |

## Deploying to a VPS

See [`deploy/DEPLOY.md`](deploy/DEPLOY.md) for Docker and systemd instructions.
Note EasyOCR pulls in PyTorch (~1–2 GB) — give the box ≥ 2 GB RAM.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The matcher and storage layers are covered by fast, dependency-free unit tests.

## Project layout

```
src/sixseven/
  matcher.py    # pure "is this a six seven?" logic
  ocr.py        # EasyOCR wrapper (lazy, graceful degradation)
  vision.py     # Claude vision escalation
  media.py      # download -> frame extraction
  storage.py    # SQLite per-chat/per-member counters
  detector.py   # orchestrates OCR -> vision -> match
  bot.py        # Telegram handlers & commands
  __main__.py   # entry point
```

## License

MIT — see [LICENSE](LICENSE).
