# Deploying six-seven-bot on a VPS

Two options: **Docker** (simplest) or a **systemd service** with a virtualenv.

First, in Telegram: message [@BotFather](https://t.me/BotFather), run `/newbot`,
and copy the token. Then **turn off privacy mode** so the bot can see group
media: BotFather → `/setprivacy` → select your bot → **Disable**. Add the bot to
your group as a normal member (admin is not required, but it must be able to
read messages).

> Heads-up: EasyOCR pulls in PyTorch (~1–2 GB) and downloads model weights on
> first run. Give the box **≥ 2 GB RAM** (add swap if needed) and some disk.
> Running OCR-only (no `ANTHROPIC_API_KEY`) is free; the vision layer costs a
> few cents per escalated image.

## Option A — Docker (recommended)

```bash
git clone <your-repo-url> six-seven-bot
cd six-seven-bot
cp .env.example .env
nano .env            # paste TELEGRAM_BOT_TOKEN (and ANTHROPIC_API_KEY if using vision)
docker compose up -d --build
docker compose logs -f
```

The SQLite DB lives in `./data/` and OCR weights are cached in a named volume,
so both survive restarts and rebuilds.

## Option B — systemd + virtualenv

```bash
sudo useradd --system --create-home --home-dir /opt/six-seven-bot sixseven || true
sudo git clone <your-repo-url> /opt/six-seven-bot
cd /opt/six-seven-bot
sudo -u sixseven python3 -m venv .venv
sudo -u sixseven .venv/bin/pip install -r requirements.txt

sudo -u sixseven cp .env.example .env
sudo -u sixseven nano .env      # fill in your token

sudo cp deploy/six-seven-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now six-seven-bot
journalctl -u six-seven-bot -f
```

Edit `deploy/six-seven-bot.service` if your user or paths differ.

## Updating

```bash
# Docker
git pull && docker compose up -d --build

# systemd
cd /opt/six-seven-bot && sudo git pull
sudo -u sixseven .venv/bin/pip install -r requirements.txt
sudo systemctl restart six-seven-bot
```
