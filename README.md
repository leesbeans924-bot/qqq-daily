# QQQ Daily

A self-updating market briefing page that runs every weekday at 4:30 PM ET.

Pulls live price data for QQQ and its top holdings, runs it through Claude AI for analysis, and publishes a styled HTML page to GitHub Pages automatically.

---

## Setup (5 minutes)

### 1. Create the repo
- Go to github.com → New repository
- Name it `qqq-daily`
- Set to **Public** (required for free GitHub Pages)
- Don't initialize with anything — just create it

### 2. Upload these files
Upload all files from this folder into the root of the repo:
- `generate.py`
- `requirements.txt`
- `index.html` (the placeholder below)
- `.github/workflows/daily.yml`

### 3. Add your Anthropic API key
- Go to your repo → **Settings** → **Secrets and variables** → **Actions**
- Click **New repository secret**
- Name: `ANTHROPIC_API_KEY`
- Value: your key from console.anthropic.com

### 4. Enable GitHub Pages
- Go to your repo → **Settings** → **Pages**
- Source: **Deploy from a branch**
- Branch: `main` / `/ (root)`
- Save

### 5. Run it manually first
- Go to **Actions** tab → **QQQ Daily Update** → **Run workflow**
- Wait ~30 seconds
- Your site will be live at: `https://yourusername.github.io/qqq-daily`

---

## Schedule
Runs automatically Monday–Friday at 4:30 PM ET (after market close).

## Embed on Squarespace
Add a Code Block to any Squarespace page with:
```html
<iframe src="https://yourusername.github.io/qqq-daily"
        width="100%" height="900"
        style="border:none; border-radius:8px;">
</iframe>
```

---

## Stack
- **Data**: Yahoo Finance (free, no API key needed)
- **Analysis**: Anthropic Claude Sonnet
- **Hosting**: GitHub Pages (free)
- **Automation**: GitHub Actions (free)
