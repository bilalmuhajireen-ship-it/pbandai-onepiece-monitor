# Upgrade to GitHub V4

## Replace the old files

Upload these files and folders to the root of your existing repository:

- `.github`
- `docs`
- `state`
- `monitor.py`
- `requirements.txt`
- `README.md`

When GitHub asks, overwrite the older copies.

Do not upload an `.env` file.

## Keep your repository secrets

These existing repository secrets continue to work:

- `DISCORD_WEBHOOK_URL`
- `DISCORD_MENTION`
- `NTFY_TOPIC`

## Enable GitHub Pages

Open:

Settings → Pages

Under **Build and deployment**, choose:

- Source: `Deploy from a branch`
- Branch: `main`
- Folder: `/docs`

Save.

Your dashboard URL will be shown by GitHub after Pages deploys.

## Run the workflow

Open:

Actions → P-Bandai Monitor V4 → Run workflow

The first run records the current baseline. Later discoveries produce alerts.

## What V4 monitors

- Premium Bandai US ONE PIECE CARD GAME product page
- Official English ONE PIECE CARD GAME news page
- New public items
- Preorder opening times
- Restock/availability changes
- 24h, 1h, 15m, 5m, and live alerts
- Discord and ntfy
- GitHub Pages dashboard

## Important limitations

GitHub scheduled jobs can start later than the requested five-minute schedule.
The monitor uses lightweight HTTP requests. If Premium Bandai changes its site
or blocks non-browser requests, the parser may require an update.
