# GX Hosting Bot — Render setup

## Deploy

Set the Render service root directory to `gxhosting_bot`.

- Build command: `pip install -r requirements.txt`
- Start command: `python app.py`

Add these environment variables in Render. Keep the service-account JSON and
Telegram token private; never paste them into chat or commit them to the repo.

- `TELEGRAM_BOT_TOKEN`
- `OWNER_ID`
- `ADMIN_ID`
- `GOOGLE_SHEET_ID`
- `GOOGLE_SERVICE_ACCOUNT_JSON` — the complete JSON for a newly created service-account key
- `BOT_DATA_DIR=/var/data`
- `GOOGLE_SYNC_INTERVAL=30` (optional)

Attach a persistent Render disk mounted at `/var/data`. The bot stores its
SQLite database and uploaded scripts under this path. Google Sheets and Drive
remain the off-host recovery copies.

## Google permissions

Enable the Google Sheets API and Google Drive API in the service account's
Google Cloud project. Share the spreadsheet with the service account's
`client_email` as an Editor. A new service account does not automatically have
access to an existing spreadsheet.

The key included in the originally attached source was exposed, even though it
was inside a comment. Revoke that key in Google Cloud, create a replacement,
and save only the replacement in Render's secret environment variable. Removing
the old key from code does not invalidate it.

On the first run of this fixed version, the bot imports existing data from
Google Sheets into SQLite. Later restarts use the persistent SQLite copy first
and retry Google sync and Drive file restores in the background if Google is
temporarily unavailable.