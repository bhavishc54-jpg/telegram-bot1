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
- Telegram Stars invoices with verified, idempotent fulfillment
- Paddle sandbox/live checkout creation and signed FastAPI webhooks
- Shared credits, Premium fulfillment, saved-link resumption, and payment audit records
- Alembic migrations for safe upgrades of existing SQLite databases
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
- Production Paddle catalog IDs, credentials, and notification destination
- Live payment testing with your own Telegram and Paddle accounts
- Automatic review of every possible harmful advertisement

The extension point for a future permitted downloader is in
`app/services/link_validator.py`. Payment fulfillment never downloads a file.

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

ENABLE_TELEGRAM_STARS=true
ENABLE_PADDLE=true
PADDLE_ENV=sandbox
PADDLE_API_KEY=your_private_sandbox_api_key
PADDLE_CLIENT_TOKEN=your_sandbox_client_side_token
PADDLE_WEBHOOK_SECRET=your_notification_destination_secret
BASE_URL=http://localhost:8000
FRONTEND_URL=http://localhost:8000
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
`/start` to the bot in Telegram. It also starts FastAPI on port `8000` when
`ENABLE_PADDLE=true`.

Run migrations manually after pulling an update, before starting the bot:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

Startup also applies pending migrations automatically. Back up `data/bot.db`
before every production migration.

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
/buy
/credits
/paymentstatus
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
/payments
/products
/products enable|disable PRODUCT_CODE
/products configure PRODUCT_CODE pro_ID pri_ID
/givecredits USER_ID AMOUNT
/removecredits USER_ID AMOUNT
/finduser USER_ID
/userpayments USER_ID
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

## 15. How Telegram Stars works

Telegram Stars are used for small credit packs inside Telegram:

1. The user opens `/buy` and chooses a Stars product.
2. The bot creates a pending internal payment with a random order ID and invoice payload.
3. Telegram shows an invoice using currency `XTR`.
4. The bot validates the pre-checkout query but does not add access yet.
5. Credits are added only after Telegram sends `successful_payment`.
6. Duplicate updates cannot add credits twice.
7. The latest unexpired pending link is automatically validated after fulfillment.

To test, set `ENABLE_TELEGRAM_STARS=true`, run the bot, and choose a Stars item
from `/buy`. Telegram provides a dedicated test environment for Stars payments.
Use that environment while developing; do not assume clicking the Pay button is
proof of payment. The bot always waits for `successful_payment`.

Telegram's rules require Telegram Stars for digital goods and services sold
inside Telegram. Before enabling external credit sales in production, confirm
that your exact hybrid flow complies with the current Telegram and Paddle terms.

## 16. How Paddle works

Paddle is prepared for larger packs and monthly/yearly Premium products:

1. The bot creates an internal pending payment.
2. The server calls Paddle's transaction API using `PADDLE_API_KEY`.
3. The transaction contains the internal order ID, Telegram user ID, and product code.
4. The bot sends a **Pay with Paddle** button.
5. The checkout page uses `PADDLE_CLIENT_TOKEN` with Paddle.js.
6. The success page does not add credits.
7. Only a valid signed `transaction.completed` webhook can fulfill the payment.
8. Product ID, price ID, amount, currency, user, order, and transaction are rechecked.
9. Duplicate webhooks are recorded and cannot add access twice.

### Create a Paddle sandbox account

Create a Paddle Sandbox account and use the sandbox dashboard while developing.
Sandbox and live workspaces have separate API keys, tokens, products, prices,
and webhook destinations.

In **Developer Tools → Authentication**:

- Create a server-side API key and paste it after `PADDLE_API_KEY=` in `.env`.
- Create a client-side token and paste it after `PADDLE_CLIENT_TOKEN=` in `.env`.
- Never put the API key in browser code. The client-side token is the credential intended for Paddle.js.

### Create Paddle products and prices

Create these catalog entries in the sandbox dashboard:

- Starter credit pack
- 100 credits
- 500 credits
- Monthly Premium recurring price
- Yearly Premium recurring price

Copy each `pro_...` product ID and `pri_...` price ID, then configure and enable
the matching bot product from the owner account:

```text
/products
/products configure paddle_starter pro_YOUR_ID pri_YOUR_ID
/products enable paddle_starter
```

Repeat for `paddle_100`, `paddle_500`, `paddle_premium_monthly`, and
`paddle_premium_yearly`. Paddle products are inactive by default until both IDs
are configured.

### Create the Paddle webhook destination

Paddle does not create the webhook URL for you.
The app creates the route `/webhooks/paddle`.
After deployment, your domain makes it a real URL:
`https://api.yourdomain.com/webhooks/paddle`

In Paddle Sandbox, open **Developer Tools → Notifications**, create a URL
notification destination, and subscribe at least to:

- `transaction.completed`
- `transaction.payment_failed`
- `transaction.canceled`
- Relevant subscription created/activated/updated/canceled/past-due events

Copy that destination's endpoint secret into:

```env
PADDLE_WEBHOOK_SECRET=pdl_ntfset_your_secret
```

The webhook verifier uses the exact raw request body, the `Paddle-Signature`
header, HMAC-SHA256, timing-safe comparison, and timestamp tolerance.

### Test Paddle locally

1. Keep `PADDLE_ENV=sandbox`.
2. Put sandbox credentials in `.env`.
3. Set the Paddle default payment link to your checkout page. Paddle Sandbox may use localhost.
4. Run `python -m app.main` and check `http://localhost:8000/health`.
5. Use `/buy` and open **Pay with Paddle**.
6. Use Paddle's sandbox test card details, not a real card.
7. Paddle cannot send an internet webhook to plain localhost. Use an HTTPS tunnel for testing, for example:
   `https://your-tunnel.example/webhooks/paddle`.
8. Put that public URL in the Paddle sandbox notification destination.
9. Confirm `/credits` changes only after the signed webhook arrives.

The checkout page may use `FRONTEND_URL=http://localhost:8000` in sandbox. For a
tunnel or deployment, set both URLs to the appropriate HTTPS origin:

```env
BASE_URL=https://api.yourdomain.com
FRONTEND_URL=https://api.yourdomain.com
```

### Switch Paddle from sandbox to live

Do this only after sandbox tests pass:

1. Create separate live products and prices.
2. Create a live API key, live client-side token, and live notification destination.
3. Replace all sandbox IDs and credentials in `.env`.
4. Set `PADDLE_ENV=live`.
5. Set `BASE_URL` and `FRONTEND_URL` to HTTPS URLs.
6. Configure the live `pro_...` and `pri_...` IDs with `/products configure`.
7. Send a small real test purchase and verify the payment table and credit balance.

Never commit `.env`. API keys and webhook secrets must remain server-side.

## 17. Safe future downloader work

Do not add scraping or bypass code. Before enabling downloads, confirm in writing
that DiskWala provides an official API or a legally permitted public direct-file
method. Add an implementation of the existing downloader interface, validate
responses, enforce size limits, and add tests. Keep the validation-only fallback
available if the provider is unavailable.

## License

MIT. See `LICENSE`.
