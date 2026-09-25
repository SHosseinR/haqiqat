# Deploying Haqiqat on a small VPS

Target: one small VPS (1 vCPU, 2 GB RAM, about €4–5/month). Embeddings and the LLM run
through APIs; the server only fetches feeds, runs the pipeline every 30 minutes and serves
static files.

## 1. Install

```bash
sudo useradd --system --create-home --home-dir /opt/haqiqat haqiqat
sudo -u haqiqat git clone https://github.com/SHosseinR/haqiqat /opt/haqiqat/app
cd /opt/haqiqat/app
sudo -u haqiqat curl -LsSf https://astral.sh/uv/install.sh | sudo -u haqiqat sh
sudo -u haqiqat /opt/haqiqat/.local/bin/uv sync --no-dev --extra anthropic
sudo -u haqiqat cp config/config.example.yaml config/config.yaml
```

Edit `config/config.yaml`:

- `site.base_url`: your domain
- `stages`: which models to use
- `budget.daily_usd`: your daily cap
- `telegram`: bot and channels

## 2. Secrets

Create `/etc/haqiqat.env` (mode 600, owner root):

```
OPENAI_API_KEY=...          # embeddings (or whichever provider config names)
ANTHROPIC_API_KEY=...       # synthesis (or another provider's key)
TELEGRAM_BOT_TOKEN=...      # from @BotFather; add the bot as admin of both channels
```

## 3. First checks

```bash
cd /opt/haqiqat/app
H=/opt/haqiqat/app/.venv/bin/haqiqat
sudo -u haqiqat $H validate-sources --probe                  # fix failing feeds
sudo -u haqiqat env $(sudo cat /etc/haqiqat.env | xargs) \
     $H eval-embeddings                                       # set clustering.join_threshold
sudo -u haqiqat env $(sudo cat /etc/haqiqat.env | xargs) \
     $H run --once --max-calls 3 --telegram-dry-run
```

## 4. Schedule

```bash
sudo cp deploy/haqiqat.service deploy/haqiqat.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now haqiqat.timer
journalctl -u haqiqat -f
```

## 5. Serve the site

Any static web server works. For example, with [Caddy](https://caddyserver.com), which
provides automatic HTTPS:

```
your.domain {
    root * /opt/haqiqat/app/build/site
    file_server
    encode gzip zstd
}
```

**Mirrors.** The site uses only relative links, so `build/site` can be copied anywhere: a
second domain, Cloudflare Pages, GitHub Pages or IPFS. This matters for readers behind
censorship. A Tor onion service pointing at the same directory is on the roadmap.

## Docker (alternative)

```bash
docker compose -f deploy/docker-compose.yml up -d
```

This runs the pipeline every 30 minutes and serves the site on port 8080. Mount your
`config.yaml` and set the environment variables in `deploy/.env`.

## Backups

Everything that matters is in `data/haqiqat.db` (SQLite) and your `config/config.yaml`. Back
up the database daily, for example with `sqlite3 data/haqiqat.db ".backup backup.db"`.
