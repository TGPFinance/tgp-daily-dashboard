# Daily Dashboard → GitHub Pages → Slack

## Repo structure
```
your-repo/
  .github/
    workflows/
      daily-dashboard.yml
  generate_dashboard.py
  index.html              ← auto-generated, do not edit manually
```

## One-time setup

### 1. Create the GitHub repo
- Create a new public repo on GitHub (e.g. `daily-dashboard`)
- Push these files to the `main` branch

### 2. Enable GitHub Pages
- Go to repo → **Settings** → **Pages**
- Source: **Deploy from a branch**
- Branch: `main` / `/ (root)`
- Click **Save**
- Your URL will be: `https://YOUR_USERNAME.github.io/daily-dashboard`

### 3. Add secrets
Go to repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Name | Value |
|------|-------|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `SLACK_WEBHOOK_URL` | Your Slack webhook URL |

### 4. Customize the prompt
Open `generate_dashboard.py` and edit the `DASHBOARD_PROMPT` variable to describe
exactly what dashboard you want Claude to generate each day.

### 5. Test it
Go to repo → **Actions** → **Daily Dashboard** → **Run workflow**
This triggers it manually so you can verify it works before the first scheduled run.

## Schedule
The workflow runs Mon–Fri at 9am UTC by default.
To change the time, edit the `cron` line in `.github/workflows/daily-dashboard.yml`.

Cron format: `minute hour day month weekday`
- `0 9 * * 1-5` = 9:00 UTC, Monday–Friday
- `0 14 * * *`  = 2:00pm UTC, every day
