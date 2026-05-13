# Deployment And Security Guide

This guide prepares the project for local deployment first, and safe GitHub upload later.

## 1. Security Principles

- Never commit `.env` (contains `DY_COOKIE`, `DEEPSEEK_API_KEY`, etc.).
- Never commit runtime data (`outputs/`, `models/`, `*.db`).
- Keep secrets only in local env vars or local `.env`.

`.gitignore` in this repo is already configured to protect these by default.

## 2. Local Deployment (Windows PowerShell)

```powershell
cd E:\dy_comments
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and fill at least:

- `DY_COOKIE`
- `DY_VERIFY_FP`
- `DOUYIN_SPIDER_PATH`
- `DY_ANALYZE_PATH`

Start service:

```powershell
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health check:

- Open `http://127.0.0.1:8000/api/health`

## 3. Pre-GitHub Safety Checklist

Run these checks before any commit:

```powershell
.\.venv\Scripts\python scripts\post_change_check.py
```

Manual checks:

- Confirm `.env` is local-only and not tracked.
- Confirm `outputs/`, `models/`, `dy_comments.db` are not tracked.
- Confirm no cookie or API key appears in docs/scripts.

Optional quick scans:

```powershell
rg -n "DY_COOKIE|DEEPSEEK_API_KEY|sessionid=|sid_tt=" .
rg -n "sk-[A-Za-z0-9]{20,}" .
```

If any real secret appears in source files, remove it immediately and rotate that secret.

## 4. Recommended GitHub Upload Flow (Later)

When you are ready to upload:

1. Initialize git in project root.
2. Commit only code + docs + `.env.example`.
3. Add GitHub remote.
4. Push branch.

Do not upload:

- `.env`
- `outputs/`
- `models/`
- local DB files
- captured traffic containing sensitive headers/cookies

## 5. Secret Rotation Advice

If a secret was ever exposed (even locally by mistake), rotate it:

- Replace `DY_COOKIE` with a fresh login cookie.
- Regenerate `DEEPSEEK_API_KEY`.
- Re-run tests after replacement.
