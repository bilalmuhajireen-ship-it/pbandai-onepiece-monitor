# Setup

1. Create a new **public** GitHub repository named `pbandai-onepiece-monitor`.
2. Extract this ZIP and upload all contents, including `.github` and `state`.
3. In the repository, open **Settings → Secrets and variables → Actions**.
4. Add repository secret `DISCORD_WEBHOOK_URL` with your regenerated webhook URL.
5. Add repository secret `DISCORD_MENTION` with `<@&YOUR_ROLE_ID>`.
6. Add repository secret `NTFY_TOPIC` with only your topic name.
7. Open **Actions**, select **P-Bandai Monitor**, and click **Run workflow**.
8. The first run creates a baseline and sends a monthly heartbeat.
9. The schedule requests a run every five minutes. GitHub may delay scheduled runs during busy periods.

Never upload your `.env` file or place secrets directly in the code.
