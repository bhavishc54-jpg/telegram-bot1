# Telegram DiskWala Broadcast Bot

This bot watches one private Telegram source channel, waits before publishing,
converts DiskWala links through your affiliate API, and sends text-only updates
to users who pressed `/start`.

It never downloads DiskWala files and never broadcasts attached media. Photos,
videos, documents, audio, GIFs, stickers, and albums are ignored except for any
useful caption text.

## What It Does

- Accepts posts only from `SOURCE_CHANNEL_ID`, a numeric private-channel ID.
- Stores every accepted post in SQLite before the delay starts.
- Defaults to immediate broadcasting with `POST_DELAY_MINUTES=0`.
- Extracts DiskWala links from visible URLs, URL entities, and hidden
  `text_link` entities.
- Removes every non-DiskWala URL from the visible message text.
- Converts DiskWala links through `app/services/diskwala_client.py`.
- Sends only plain text and converted links to active subscribers.
- Forwards private user messages only to `ADMIN_USER_ID`.
- Supports `/stats`, `/queue`, `/retry`, `/pause`, and `/resume` for the admin.

## What It Does Not Do

- It does not download videos, files, or direct links from DiskWala.
- It does not send source-channel media to subscribers.
- It does not use Telegram Stars, Paddle, purchases, credits, `/buy`, or paid
  broadcasts by default.
- It does not authorize admin actions by username.
- It does not invent DiskWala API behavior. If the real API fields are not
  configured, conversion fails safely and the admin is notified.

## Setup

Create a bot with BotFather, then put the token in `.env`.

```powershell
copy .env.example .env
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

Use Python 3.13 for a fresh venv:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

Do not use Python 3.14 for this project yet. Some compiled dependencies may not
have stable wheels for it. On this machine, the global `python` command may
point to a Microsoft Store alias, so prefer the venv interpreter:

```powershell
.\.venv\Scripts\python.exe -m app.main
```

## Environment

Fill these in `.env`:

```env
BOT_TOKEN=your_botfather_token_here
BOT_USERNAME=your_bot_username

ADMIN_USER_ID=123456789
ADMIN_USERNAME=your_admin_username

SOURCE_CHANNEL_ID=-1001234567890
SOURCE_CHANNEL_USERNAME=your_private_channel_label

POST_DELAY_MINUTES=0

DISKWALA_API_BASE_URL=https://api.diskwala.example
DISKWALA_API_ENDPOINT=/convert
DISKWALA_API_KEY=your_diskwala_api_key_here
DISKWALA_API_AUTH_HEADER=Authorization
DISKWALA_API_AUTH_SCHEME=Bearer
DISKWALA_API_REQUEST_FIELD=url
DISKWALA_API_RESPONSE_FIELD=data.url
DISKWALA_ALLOWED_HOSTS=diskwala.com,www.diskwala.com

DATABASE_URL=sqlite:///data/bot.db

BROADCAST_RATE_PER_SECOND=25
ALLOW_PAID_BROADCAST=false

APP_MODE=polling
WEBHOOK_URL=
WEBHOOK_SECRET=

LOG_LEVEL=INFO
```

`OWNER_USER_ID` still works as a temporary fallback for `ADMIN_USER_ID`, but
`ADMIN_USER_ID` is preferred.

If `SOURCE_CHANNEL_ID` is missing, the bot will not broadcast. When a channel
post arrives, it logs the channel title and numeric ID so you can copy the ID
into `.env`, then restart the bot.

## Source Channel

Add the bot to your private source channel as an admin so it receives channel
posts. Use the numeric channel ID as `SOURCE_CHANNEL_ID`; do not rely on the
channel username for security.

## User Commands

- `/start` subscribes the private user to automatic updates.
- `/stop` marks the user inactive.
- `/help` explains the bot briefly.
- `/myid` shows the numeric Telegram user ID.

Users must press `/start` before receiving broadcasts.

## Admin Commands

Only `ADMIN_USER_ID` can run these:

- `/stats` shows subscriber and queue counts.
- `/queue` shows the next pending source posts.
- `/broadcast TEXT` queues a text-only manual broadcast to active subscribers.
- Reply with `/broadcast` to broadcast the replied message's text or caption only.
- `/retry JOB_ID` retries a failed source post or broadcast job.
- `/pause` pauses processing without deleting queued jobs.
- `/resume` resumes processing.

Private non-command messages from users are copied only to the admin inbox and
are never added to the public broadcast queue.

## DiskWala API

The adapter is [app/services/diskwala_client.py](app/services/diskwala_client.py).
It sends a JSON POST with the configured request field, for example:

```json
{"url": "https://diskwala.com/original"}
```

It reads the converted URL from `DISKWALA_API_RESPONSE_FIELD`, such as
`data.url`. Change the environment values to match the real DiskWala API docs.
Normal tests use mocks and never call the real API.

Missing real API details still needed from you:

- Exact API base URL
- Exact endpoint path
- Required auth header and scheme
- Request JSON field name
- Response JSON field path containing the converted affiliate URL

## Database And Migration

The default database is `data/bot.db`. It is ignored by git.

Before a production migration, make a backup:

```powershell
.\.venv\Scripts\python.exe scripts\backup_database.py
```

Run migrations:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
```

The broadcaster migration creates `subscribers`, `source_posts`,
`source_links`, `conversion_cache`, `broadcast_jobs`, and
`broadcast_deliveries`. If the old `users` table exists, usable Telegram users
are copied into `subscribers` without deleting the old table.

## Local Testing

Run all checks:

```powershell
.\scripts\run_checks.ps1
```

Or run just tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Manual five-minute test:

1. Start the bot with `.\.venv\Scripts\python.exe -m app.main`.
2. Send `/start` to the bot from a private Telegram account.
3. Post text-only content in the source channel and confirm it arrives after the delay.
4. Post one DiskWala link plus a Telegram link; the Telegram link should be removed.
5. Post multiple DiskWala links with a photo; subscribers should receive only text and converted links.

Large broadcasts may take time because the bot sends at a controlled rate and
respects Telegram flood limits.

## Troubleshooting

- `ADMIN_USER_ID is required`: send `/myid` to the bot, copy the number into
  `.env`, and restart.
- `SOURCE_CHANNEL_ID is missing`: post once in the source channel, read the log
  line with the numeric channel ID, copy it into `.env`, and restart.
- DiskWala conversion fails: verify the API endpoint, auth, request field, and
  response field. The bot never sends original unconverted DiskWala links.
- A user stops receiving updates: they may have sent `/stop` or blocked the bot.

## Security Rules

- Never commit `.env`.
- Never put real bot tokens or API keys in `.env.example` or README examples.
- Rotate any token that was pasted into chat or committed by mistake.
- Admin and source-channel checks use numeric IDs.
- Broadcasts are text-only.
- Private user messages are never public broadcasts.
