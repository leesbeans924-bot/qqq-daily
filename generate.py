import yfinance as yf
import anthropic
import json
import time
from datetime import datetime
import pytz

# ── Config ────────────────────────────────────────────────────────────────────
QQQ_HOLDINGS = {
    "QQQ":  "QQQ ETF",
    "NVDA": "NVIDIA",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "GOOGL":"Alphabet",
    "META": "Meta",
    "TSLA": "Tesla",
    "AVGO": "Broadcom",
    "COST": "Costco",
    "NFLX": "Netflix",
}

MACRO_TICKERS  = ["^TNX", "^VIX", "CL=F"]
MACRO_LABELS   = {"^TNX": "10Y Yield", "^VIX": "VIX", "CL=F": "Crude Oil"}

# ── Fetch all quotes in one batch call ────────────────────────────────────────
def fetch_all(tickers):
    """Download 5 days of daily data for all tickers in one request."""
    symbols = " ".join(tickers)
    try:
        df = yf.download(symbols, period="5d", interval="1d",
                         group_by="ticker", auto_adjust=True, progress=False)
    except Exception as e:
        print(f"Download error: {e}")
        return {}

    result = {}
    for t in tickers:
        try:
            if len(tickers) == 1:
                closes = df["Close"].dropna()
            else:
                closes = df[t]["Close"].dropna()

            if len(closes) >= 2:
                prev  = float(closes.iloc[-2])
                close = float(closes.iloc[-1])
                chg   = ((close - prev) / prev) * 100
                result[t] = {
                    "close":  round(close, 2),
                    "change": round(chg, 2),
                    "prev":   round(prev, 2),
                }
        except Exception as e:
            print(f"Parse error for {t}: {e}")
    return result

def fetch_qqq_30d():
    """30-day QQQ closes for sparkline."""
    try:
        df = yf.download("QQQ", period="30d", interval="1d",
                         auto_adjust=True, progress=False)
        closes = df["Close"].dropna()
        return [
            {"date": d.strftime("%b %d"), "close": round(float(c), 2)}
            for d, c in zip(closes.index, closes)
        ]
    except Exception as e:
        print(f"Chart fetch error: {e}")
        return []

# ── Claude analysis ───────────────────────────────────────────────────────────
def get_analysis(quotes, macro, chart_data):
    client = anthropic.Anthropic()

    def fmt(ticker, label, q):
        sign = "+" if q["change"] >= 0 else ""
        return f"  {label}: ${q['close']} ({sign}{q['change']}%)"

    holdings_text = "\n".join(
        fmt(t, QQQ_HOLDINGS.get(t, t), q)
        for t, q in quotes.items() if t in QQQ_HOLDINGS
    )
    macro_text = "\n".join(
        fmt(t, MACRO_LABELS.get(t, t), q)
        for t, q in macro.items()
    )
    prices_tail = [d["close"] for d in chart_data[-10:]]

    prompt = f"""You are a sharp market analyst writing the QQQ Daily Briefing — a nightly recap for serious retail investors.

Today's data:

HOLDINGS:
{holdings_text}

MACRO:
{macro_text}

30-DAY QQQ PRICE TRAIL (oldest to newest): {prices_tail}

Write a tight, confident briefing with exactly these four sections. Be specific, not vague. No fluff.

1. HEADLINE (one punchy sentence summarizing today's dominant market theme)

2. WHAT MOVED QQQ TODAY (3-5 bullet points — specific stocks/macro events that drove price, with % moves. Explain the WHY behind each move.)

3. CHART PATTERN (2-3 sentences analyzing the 30-day price action. Name the pattern if there is one. Be direct about what the technicals say.)

4. WHAT TO WATCH TOMORROW (2-3 specific catalysts — earnings, economic data, Fed speakers, geopolitical — and what a bullish vs bearish outcome looks like for each.)

Tone: Bloomberg terminal meets sharp Twitter analyst. Confident, data-driven, no hedging waffle."""

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text

# ── HTML generator ─────────────────────────────────────────────────────────────
def build_html(quotes, macro, chart_data, analysis):
    et = pytz.timezone("America/New_York")
    now = datetime.now(et)
    date_str = now.strftime("%A, %B %-d, %Y")
    time_str = now.strftime("%-I:%M %p ET")

    import re

    def extract_section(text, header):
        try:
            start = text.index(header) + len(header)
            nxt = re.search(r'\n[1-4]\. [A-Z]', text[start:])
            end = start + nxt.start() if nxt else len(text)
            return text[start:end].strip()
        except:
            return ""

    headline = extract_section(analysis, "1. HEADLINE")
    movers   = extract_section(analysis, "2. WHAT MOVED QQQ TODAY")
    pattern  = extract_section(analysis, "3. CHART PATTERN")
    tomorrow = extract_section(analysis, "4. WHAT TO WATCH TOMORROW")

    qqq      = quotes.get("QQQ", {})
    qqq_chg  = qqq.get("change", 0)
    qqq_color = "#00ff88" if qqq_chg >= 0 else "#ff4466"
    qqq_arrow = "▲" if qqq_chg >= 0 else "▼"

    def holding_row(ticker, name):
        q = quotes.get(ticker, {})
        if not q:
            return ""
        chg   = q.get("change", 0)
        color = "#00ff88" if chg >= 0 else "#ff4466"
        arrow = "▲" if chg >= 0 else "▼"
        return f"""
        <div class="holding-row">
          <span class="ticker">{ticker}</span>
          <span class="name">{name}</span>
          <span class="price">${q['close']}</span>
          <span class="change" style="color:{color}">{arrow} {abs(chg):.2f}%</span>
        </div>"""

    holdings_html = "".join(
        holding_row(t, n) for t, n in QQQ_HOLDINGS.items() if t != "QQQ"
    )

    def macro_row(ticker):
        q     = macro.get(ticker, {})
        label = MACRO_LABELS.get(ticker, ticker)
        if not q:
            return ""
        chg   = q.get("change", 0)
        color = "#00ff88" if chg >= 0 else "#ff4466"
        arrow = "▲" if chg >= 0 else "▼"
        val   = f"{q['close']}%" if ticker == "^TNX" else f"{q['close']}"
        return f"""
        <div class="holding-row">
          <span class="ticker">{label}</span>
          <span class="name"></span>
          <span class="price">{val}</span>
          <span class="change" style="color:{color}">{arrow} {abs(chg):.2f}%</span>
        </div>"""

    macro_html  = "".join(macro_row(t) for t in MACRO_TICKERS)
    chart_json  = json.dumps(chart_data)

    def bullets_to_html(text):
        lines = [l.strip().lstrip("•-* ") for l in text.strip().split("\n") if l.strip()]
        return "<ul>" + "".join(f"<li>{l}</li>" for l in lines) + "</ul>"

    def para_to_html(text):
        return f"<p>{text.replace(chr(10), '<br>')}</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>QQQ Daily — {date_str}</title>
  <link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Syne:wght@400;600;800&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    :root {{
      --bg:#080b10; --surface:#0e1318; --border:#1e2730;
      --text:#c8d6e5; --muted:#4a5a6a; --accent:#00ff88;
      --red:#ff4466; --gold:#f5c842;
      --mono:'Space Mono',monospace; --sans:'Syne',sans-serif;
    }}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:var(--bg);color:var(--text);font-family:var(--mono);font-size:14px;line-height:1.6;min-height:100vh;
      background-image:radial-gradient(ellipse 80% 50% at 50% -10%,rgba(0,255,136,.07),transparent),
      repeating-linear-gradient(0deg,transparent,transparent 40px,rgba(255,255,255,.015) 40px,rgba(255,255,255,.015) 41px),
      repeating-linear-gradient(90deg,transparent,transparent 40px,rgba(255,255,255,.015) 40px,rgba(255,255,255,.015) 41px)}}
    header{{border-bottom:1px solid var(--border);padding:28px 40px 24px;display:flex;align-items:flex-end;justify-content:space-between;gap:20px;flex-wrap:wrap}}
    .logo{{font-family:var(--sans);font-weight:800;font-size:28px;letter-spacing:-.5px;color:#fff}}
    .logo span{{color:var(--accent)}}
    .header-right{{text-align:right}}
    .date{{font-size:12px;color:var(--muted);letter-spacing:.08em;text-transform:uppercase}}
    .qqq-hero{{font-family:var(--sans);font-weight:800;font-size:42px;color:#fff;line-height:1}}
    .qqq-change{{font-size:20px;font-weight:600;color:{qqq_color}}}
    .headline-bar{{background:rgba(0,255,136,.06);border-top:1px solid rgba(0,255,136,.2);border-bottom:1px solid rgba(0,255,136,.2);padding:14px 40px;font-family:var(--sans);font-size:15px;font-weight:600;color:var(--accent);letter-spacing:.01em}}
    .grid{{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border);border-top:1px solid var(--border)}}
    .panel{{background:var(--bg);padding:28px 32px}}
    .panel-full{{background:var(--bg);padding:28px 32px;border-top:1px solid var(--border)}}
    .panel-label{{font-size:10px;letter-spacing:.15em;text-transform:uppercase;color:var(--muted);margin-bottom:16px;font-family:var(--sans)}}
    .holding-row{{display:grid;grid-template-columns:70px 1fr auto auto;gap:8px;align-items:center;padding:8px 0;border-bottom:1px solid var(--border);font-size:13px}}
    .holding-row:last-child{{border-bottom:none}}
    .ticker{{color:#fff;font-weight:700;font-size:12px}}
    .name{{color:var(--muted);font-size:12px}}
    .price{{text-align:right;color:var(--text)}}
    .change{{text-align:right;font-weight:700;font-size:12px;min-width:70px}}
    .analysis-section{{margin-bottom:24px}}
    .analysis-section h3{{font-family:var(--sans);font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--gold);margin-bottom:10px}}
    .analysis-section ul{{padding-left:18px;color:var(--text)}}
    .analysis-section li{{margin-bottom:8px;line-height:1.7;font-size:13px}}
    .analysis-section p{{color:var(--text);font-size:13px;line-height:1.8}}
    canvas{{width:100%!important}}
    .updated{{padding:14px 40px;font-size:11px;color:var(--muted);border-top:1px solid var(--border);display:flex;justify-content:space-between}}
    @media(max-width:700px){{
      header{{padding:20px}}.grid{{grid-template-columns:1fr}}
      .panel,.panel-full{{padding:20px}}.headline-bar{{padding:14px 20px}}
      .qqq-hero{{font-size:32px}}.updated{{padding:14px 20px;flex-direction:column;gap:4px}}
    }}
  </style>
</head>
<body>
<header>
  <div class="logo">QQQ <span>Daily</span></div>
  <div class="header-right">
    <div class="date">{date_str}</div>
    <div class="qqq-hero">${qqq.get('close','--')}</div>
    <div class="qqq-change">{qqq_arrow} {abs(qqq_chg):.2f}% today</div>
  </div>
</header>
<div class="headline-bar">◆ &nbsp;{headline}</div>
<div class="grid">
  <div class="panel">
    <div class="panel-label">Top Holdings</div>
    {holdings_html}
  </div>
  <div class="panel">
    <div class="panel-label">Macro</div>
    {macro_html}
    <div class="panel-label" style="margin-top:20px">30-Day Chart</div>
    <canvas id="chart" height="120"></canvas>
  </div>
</div>
<div class="panel-full">
  <div class="grid" style="background:transparent;border:none;gap:32px">
    <div>
      <div class="analysis-section"><h3>What Moved QQQ Today</h3>{bullets_to_html(movers)}</div>
      <div class="analysis-section"><h3>Chart Pattern</h3>{para_to_html(pattern)}</div>
    </div>
    <div>
      <div class="analysis-section"><h3>What to Watch Tomorrow</h3>{bullets_to_html(tomorrow)}</div>
    </div>
  </div>
</div>
<div class="updated">
  <span>Generated at {time_str}</span>
  <span>Data via Yahoo Finance · Analysis via Claude</span>
</div>
<script>
const chartData={chart_json};
const labels=chartData.map(d=>d.date);
const prices=chartData.map(d=>d.close);
const mn=Math.min(...prices),mx=Math.max(...prices);
const ctx=document.getElementById('chart').getContext('2d');
const grad=ctx.createLinearGradient(0,0,0,120);
grad.addColorStop(0,'rgba(0,255,136,0.25)');grad.addColorStop(1,'rgba(0,255,136,0)');
new Chart(ctx,{{type:'line',data:{{labels,datasets:[{{data:prices,borderColor:'#00ff88',borderWidth:2,backgroundColor:grad,fill:true,tension:0.3,pointRadius:0,pointHoverRadius:4}}]}},options:{{responsive:true,plugins:{{legend:{{display:false}},tooltip:{{callbacks:{{label:c=>'$'+c.parsed.y.toFixed(2)}}}}}},scales:{{x:{{display:false}},y:{{display:true,min:mn*.995,max:mx*1.005,grid:{{color:'rgba(255,255,255,0.04)'}},ticks:{{color:'#4a5a6a',font:{{size:10}},callback:v=>'$'+v.toFixed(0)}}}}}}}}}}});
</script>
</body>
</html>"""

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    all_tickers = list(QQQ_HOLDINGS.keys())

    print("Fetching stock quotes...")
    quotes = fetch_all(all_tickers)
    print(f"  Got {len(quotes)} stock quotes")

    print("Fetching macro data...")
    macro = fetch_all(MACRO_TICKERS)
    print(f"  Got {len(macro)} macro quotes")

    print("Fetching 30-day chart...")
    chart = fetch_qqq_30d()
    print(f"  Got {len(chart)} days of data")

    print("Generating AI analysis...")
    analysis = get_analysis(quotes, macro, chart)
    print("  Analysis complete")

    print("Building HTML...")
    html = build_html(quotes, macro, chart, analysis)
    with open("index.html", "w") as f:
        f.write(html)
    print("Done — index.html written.")

if __name__ == "__main__":
    main()
