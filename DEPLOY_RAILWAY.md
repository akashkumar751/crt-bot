# Railway Deployment Guide (Python Worker)

This project is a background worker bot (not an HTTP API), so deploy it as a normal Railway service with a worker start command.

## 1) Files required in repo

These are now present:

- `main.py`
- `requirements.txt`
- `Procfile`
- `runtime.txt`
- `.env.example`

## 2) Push code to GitHub

```bash
cd /Users/akash.kumar3/Desktop/crt-bot
git init
git add .
git commit -m "Railway deploy setup"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

If your repo already exists, only run:

```bash
git add .
git commit -m "Railway deploy setup"
git push
```

## 3) Deploy from Railway dashboard (recommended)

1. Open `https://railway.app`
2. Click **New Project**
3. Select **Deploy from GitHub repo**
4. Choose this repository
5. Wait for first build to start

## 4) Configure runtime command

In Railway service:

1. Open **Settings**
2. In **Start Command**, set:

```bash
python main.py
```

(`Procfile` already has `worker: python main.py`, but setting Start Command explicitly avoids detection issues.)

## 5) Add environment variables

Open service **Variables** and add:

- `OANDA_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Then click **Deploy** staged changes.

## 6) Verify logs

Open service **Logs** and confirm lines like:

- `Bot started. Waiting for closed H1 candles...`
- `Checking CRT -> ...`

If env vars are missing, app now fails fast with a clear error message.

## 7) Optional CLI deploy flow

```bash
npm i -g @railway/cli
railway login
cd /Users/akash.kumar3/Desktop/crt-bot
railway init
railway up
```

After deploy, still set variables in Railway dashboard or via CLI.

## 8) Update flow for future changes

Every code update:

```bash
git add .
git commit -m "update bot logic"
git push
```

Railway autodeploys from GitHub (if enabled).
