# Project Guide

## Purpose

This repository is a Python Telegram bot that watches one private source
channel, queues posts, converts DiskWala links through a configured affiliate
API, and broadcasts text-only updates to active subscribers.

## Commands

- Install: `.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt`
- Create venv: `py -3.13 -m venv .venv`
- Migrate: `.\.venv\Scripts\python.exe -m alembic upgrade head`
- Run locally: `.\.venv\Scripts\python.exe -m app.main`
- Test: `.\.venv\Scripts\python.exe -m pytest -q`
- Full checks: `.\scripts\run_checks.ps1`
- Format: `.\.venv\Scripts\ruff.exe format app tests scripts alembic`
- Lint: `.\.venv\Scripts\ruff.exe check app tests scripts alembic`

## Environment Rules

- Never commit `.env`.
- Keep real secrets only in `.env` or the deployment secret store.
- `.env.example` must use fake placeholders only.
- `ADMIN_USER_ID` and `SOURCE_CHANNEL_ID` are numeric security identifiers.
- `OWNER_USER_ID` is only a temporary backward-compatible fallback.

## Security Rules

- Never log bot tokens, DiskWala API keys, webhook secrets, authorization headers,
  or database passwords.
- Never authorize admin commands by username.
- Never invent DiskWala API behavior. If the real endpoint, request field, or
  response field is unknown, fail safely and document what is missing.
- Never broadcast attached media.
- Never download DiskWala files.
- Never broadcast private user messages.
- Never send an original unconverted DiskWala link to subscribers after a
  conversion failure.
