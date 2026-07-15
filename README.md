# Telegram Bot: safe DiskWala link validation

This is a complete, modular Telegram bot written in Python. It accepts public
DiskWala links, checks them safely, applies plan limits, and records requests in
SQLite.

The bot **does not download files**. It does not open submitted links or try to
bypass login pages, advertisements, DRM, authentication, rate limits, private
files, or website security. Downloading can be added later only through an
official API or a legally permitted public direct-download method.

## What is implemented

- Async `python-telegram-bot` 22.8 application
- Async SQLAlchemy 2.0 with SQLite
- `/start`, `/help`, `/status`, `/account`, `/plans`, and `/support`
- Strict `http://` and `https://` DiskWala URL validation
- Offline domain allowlist; submitted URLs are never fetched
- Per-user anti-spam cooldown and daily Free/Premium limits
- User accounts, referrals fields, roles, usage, bans, and subscription expiry
- Payment-provider interface with no real gateway and no stored card data
- Owner-only mutations and limited admin access based on Telegram numeric IDs
- Inline owner/admin menu, audit log, editable settings, stats, and maintenance mode
- Sponsored-message creation, editing, activation, deactivation, deletion, caps, and dates
- Free-user ad eligibility and basic prohibited-content checks
- Confirmed broadcast workflow for text, photos, videos, documents, and URL buttons
- Broadcast preview, cancel, pacing, progress, and successful/failed counts
- Environment validation, safe error handling, logging, backup, and cleanup tools
- Docker, Docker Compose, and a hardened example systemd service
- Automated tests, Ruff formatting/linting, Bandit security checks, and import checks

## Not implemented yet

- DiskWala file downloading
- A DiskWala scraper, login bypass, ad bypass, or protection bypass
- Telegram Stars or another real payment provider
- Automatic review of every possible harmful advertisement

The extension point for a future permitted downloader is in
`app/services/link_validator.py`. The payment interface is in
`app/services/subscription_service.py`.

## Project structure

```text
telegram-bot/
├── app/
│   ├── handlers/             # User, links, admin, ads, broadcasts, plans
│   ├── keyboards/            # Inline menu builders
│   ├── middleware/           # Access guard and cooldown limiter
│   ├── services/             # Business logic and extension interfaces
│   ├── utils/                # Logging helpers
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   └── models.py
├── data/                     # Runtime database and temporary files
├── deploy/                   # Example systemd unit
├── logs/                     # Runtime logs
├── scripts/                  # Backup, cleanup, and check commands
├── tests/
├── .env.example
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

## 1. Install Python on Windows

Python 3.12 or newer is required. Download Python from
[python.org](https://www.python.org/downloads/windows/). During installation,
select **Add Python to PATH**.

Open PowerShell and check it:

```powershell
python --version
```

## 2. Create a virtual environment on Windows

Open PowerShell inside this project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run this once for your Windows user, then try
activation again:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 3. Install dependencies

Runtime only:

```powershell
python -m pip install -r requirements.txt
```

Runtime plus test tools:

```powershell
python -m pip install -r requirements-dev.txt
```

## 4. Create the `.env` file

Copy the safe example:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set your real values only in `.env`:

```env
BOT_TOKEN=your_botfather_token_here
OWNER_USER_ID=your_numeric_telegram_id_here
SUPPORT_USERNAME=your_username_without_at_sign
DATABASE_URL=sqlite:///data/bot.db
FREE_DAILY_LIMIT=5
PREMIUM_DAILY_LIMIT=100
LOG_LEVEL=INFO
```

`.env` is ignored by Git. Never paste your token into source code, a GitHub
issue, a chat message, or a screenshot.

## 5. Create a bot and add the BotFather token

1. Open Telegram and start the verified `@BotFather` account.
2. Send `/newbot` and follow its instructions.
3. Copy the token BotFather gives you.
4. Put it after `BOT_TOKEN=` in `.env`.
5. If the token is ever exposed, use BotFather to revoke it and create a new one.

## 6. Find your numeric Telegram user ID

Use a reputable Telegram ID bot such as `@userinfobot`, or inspect your own
updates through Telegram's official Bot API. Your user ID is a number, not your
`@username`. Never give an ID bot your BotFather token.

Put the number after `OWNER_USER_ID=` in `.env`. Only this ID gets complete
control. Start the bot from that same Telegram account.

## 7. Run the bot locally

```powershell
.\.venv\Scripts\Activate.ps1
python -m app.main
```

The first run creates `data/bot.db` and the default editable settings. Send
`/start` to the bot in Telegram.

To stop it, return to PowerShell and press `Ctrl+C`. The application closes its
database engine during shutdown.

## 8. Test user and owner commands

User commands:

```text
/start
/help
/status
/account
/plans
/support
```

Send a complete public link such as `https://diskwala.com/example`. The bot will
validate the URL and clearly say downloading is not connected.

Owner and limited-admin commands:

```text
/admin
/stats
/users
/broadcast
/addpremium USER_ID DAYS
/removepremium USER_ID
/ban USER_ID
/unban USER_ID
/setlimit free|premium NUMBER
/addadmin USER_ID
/removeadmin USER_ID
/ads
/addad TITLE | MESSAGE | BUTTON TEXT | URL | START_DATE | END_DATE | MAX
/removead AD_ID
/maintenance on|off
/settings
/settings KEY VALUE
```

Use `/ads activate AD_ID`, `/ads deactivate AD_ID`, or
`/ads edit AD_ID FIELD VALUE` to manage an existing sponsored message. A maximum
display value of `0` means no display cap.

The broadcast workflow asks for content, an optional button, shows a private
preview, and requires **Confirm send**. Cancel exits without sending anything.

To test authorization, type an owner command from a different Telegram account.
It must receive an unauthorized response. Limited admins can view the panel,
stats, and user list, but owner-only changes remain blocked.

## 9. Run tests and checks

Run everything on Windows:

```powershell
.\scripts\run_checks.ps1
```

Or run tools separately:

```powershell
python -m pytest -q
ruff format --check app tests scripts
ruff check app tests scripts
python -m compileall -q app tests scripts
bandit -q -r app scripts
python -m pip check
```

To apply formatting after an edit:

```powershell
ruff format app tests scripts
```

## 10. Back up the database

Create a consistent SQLite backup while the bot is running:

```powershell
python scripts\backup_database.py
```

Backups are written to `data/backups/` and are ignored by Git. Copy important
backups to encrypted storage outside the server. Test restoration on a separate
machine before depending on a backup.

Clean project temporary files older than 24 hours:

```powershell
python scripts\cleanup_temp.py
```

The cleanup script can only delete regular files inside `data/tmp`.

## 11. Run continuously with Docker

Install Docker Desktop, create `.env`, then run:

```powershell
docker compose up -d --build
docker compose logs -f bot
```

Stop it with:

```powershell
docker compose down
```

The compose file keeps `data` and `logs` on the host so rebuilding the container
does not remove the database.

## 12. Deploy to an Ubuntu VPS with Docker

Docker is the simplest production option for a beginner:

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-v2
sudo systemctl enable --now docker
git clone YOUR_PRIVATE_REPOSITORY_URL telegram-bot
cd telegram-bot
cp .env.example .env
nano .env
sudo docker compose up -d --build
sudo docker compose logs -f bot
```

Keep the repository private and protect SSH access to the VPS. Do not place the
token directly in `docker-compose.yml`.

## 13. Run continuously with systemd instead

Install Python, create a dedicated user, and copy the project to
`/opt/telegram-bot`. Then:

```bash
cd /opt/telegram-bot
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
sudo chown -R telegrambot:telegrambot /opt/telegram-bot
sudo cp deploy/telegram-bot.service /etc/systemd/system/telegram-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now telegram-bot
sudo systemctl status telegram-bot
sudo journalctl -u telegram-bot -f
```

The example service blocks privilege escalation, gives the process a private
temporary directory, and permits writes only to the project data/log folders.

## 14. Update the bot later

Back up first. Then update the code and dependencies:

```bash
cd /opt/telegram-bot
.venv/bin/python scripts/backup_database.py
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
sudo systemctl restart telegram-bot
```

For Docker:

```bash
python3 scripts/backup_database.py
git pull --ff-only
sudo docker compose up -d --build
```

## 15. Safe future downloader work

Do not add scraping or bypass code. Before enabling downloads, confirm in writing
that DiskWala provides an official API or a legally permitted public direct-file
method. Add an implementation of the existing downloader interface, validate
responses, enforce size limits, and add tests. Keep the validation-only fallback
available if the provider is unavailable.

## License

MIT. See `LICENSE`.

