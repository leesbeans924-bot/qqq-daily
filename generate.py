import anthropic
import requests
import json
import time
import re
from datetime import datetime
import pytz
import os
 
FINNHUB_KEY = os.environ["FINNHUB_API_KEY"]
FINNHUB_URL = "https://finnhub.io/api/v1"
 
QQQ_HOLDINGS = {
    "QQQ":  "Invesco QQQ",
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
 
def fh_quote(symbol):
    try:
        r = requests.get(f"{FINNHUB_URL}/quote",
                         params={"symbol": symbol, "token": FINNHUB_KEY},
                         timeout=10)
        d = r.json()
        if d.get("c") and d["c"] != 0:
            price = round(float(d["c"]), 2)
            prev  = round(float(d["pc"]), 2)
            chg   = round(((price - prev) / prev) * 100, 2) if prev else 0
            return {"close": price, "change": chg}
    except Exception as e:
        print(f"  Error {symbol}: {e}")
    return None
 
def fetch_stocks():
    result = {}
    for ticker in QQQ_HOLDINGS:
        print(f"  {ticker}...")
        q = fh_quote(ticker)
        if q:
            result[ticker] = q
        time.sleep(0.4)
    return result
 
def fetch_macro():
    result = {}
    for sym, label, key in [
        ("%5ETNX", "10Y Yield", "TNX"),
        ("%5EVIX", "VIX",      "VIX"),
    ]:
        try:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                headers={"User-Agent": "Mozilla/5.0 (compatible)"},
                timeout=8
            )
            meta = r.json()["chart"]["result"][0]["meta"]
            price = round(float(meta["regularMarketPrice"]), 3)
            prev  = round(float(meta["chartPreviousClose"]), 3)
            chg   = round(((price - prev) / prev) * 100, 2) if prev else 0
            result[key] = {"close": price, "change": chg, "label": label}
            print(f"  {label} OK")
        except Exception as e:
            print(f"  {label} failed: {e}")
        time.sleep(0.5)
    q = fh_quote("OANDA:BCO_USD")
    if q:
        q["label"] = "Brent Crude"
        result["OIL"] = q
        print("  Crude OK")
    return result
 
def fetch_qqq_30d():
    now  = int(time.time())
    past = now - (35 * 24 * 3600)
    try:
        r = requests.get(f"{FINNHUB_URL}/stock/candle",
                         params={"symbol": "QQQ", "resolution": "D",
                                 "from": past, "to": now, "token": FINNHUB_KEY},
                         timeout=10)
        d = r.json()
        if d.get("s") == "ok" and d.get("t"):
            return [{"date": datetime.fromtimestamp(t).strftime("%b %-d"),
                     "close": round(float(c), 2)}
                    for t, c in zip(d["t"], d["c"])]
    except Exception as e:
        print(f"  Chart error: {e}")
    return []
 
def get_analysis(quotes, macro, chart_data):
    client = anthropic.Anthropic()
    def fmt(label, q):
        sign = "+" if q["change"] >= 0 else ""
        return f"  {label}: ${q['close']} ({sign}{q['change']}%)"
    holdings_lines = "\n".join(
        fmt(QQQ_HOLDINGS.get(t, t), q)
        for t, q in quotes.items() if t in QQQ_HOLDINGS
    ) or "  (unavailable)"
    macro_lines = "\n".join(fmt(v["label"], v) for v in macro.values()) or "  (unavailable)"
    prices = [d["close"] for d in chart_data[-10:]]
    prompt = f"""You are a sharp market analyst writing the QQQ Daily Briefing for serious retail investors.
 
HOLDINGS:
{holdings_lines}
 
MACRO:
{macro_lines}
 
30-DAY QQQ PRICE TRAIL (oldest to newest): {prices}
 
Write a concise briefing in exactly four sections. No markdown — plain text only. No asterisks or symbols.
 
SECTION 1 - HEADLINE
One punchy sentence capturing today's dominant theme.
 
SECTION 2 - MOVERS
5 bullet points. Each starts with a dash. Stock or macro item, its move, and the specific reason why.
 
SECTION 3 - CHART
2-3 sentences on the 30-day price pattern. Name the pattern. State what it suggests next.
 
SECTION 4 - TOMORROW
3 bullet points. Each starts with a dash. Specific catalysts with a bullish and bearish scenario for each.
 
Plain sentences only. No markdown. No asterisks."""
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=900,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text
 
def strip_md(text):
    text = re.sub(r'\*{1,3}', '', text)
    text = re.sub(r'_{1,3}', '', text)
    return text.strip()
 
def extract_section(text, header):
    try:
        start = text.index(header) + len(header)
        headers = ["SECTION 1", "SECTION 2", "SECTION 3", "SECTION 4"]
        end = len(text)
        for h in headers:
            if h in text[start:]:
                pos = text.index(h, start)
                if pos < end:
                    end = pos
        return strip_md(text[start:end].strip())
    except:
        return ""
 
def bullets_to_html(text):
    lines = []
    for line in text.split("\n"):
        line = strip_md(line.strip().lstrip("-• ").strip())
        if line:
            lines.append(f"<li>{line}</li>")
    return "<ul>" + "".join(lines) + "</ul>" if lines else ""
 
def build_html(quotes, macro, chart_data, analysis):
    et       = pytz.timezone("America/New_York")
    now      = datetime.now(et)
    date_str = now.strftime("%B %-d, %Y").upper()
    time_str = now.strftime("%-I:%M %p ET")
    day_str  = now.strftime("%A").upper()
 
    headline = extract_section(analysis, "SECTION 1 - HEADLINE")
    movers   = extract_section(analysis, "SECTION 2 - MOVERS")
    pattern  = extract_section(analysis, "SECTION 3 - CHART")
    tomorrow = extract_section(analysis, "SECTION 4 - TOMORROW")
 
    qqq       = quotes.get("QQQ", {})
    qqq_chg   = qqq.get("change", 0)
    qqq_color = "#c9a84c" if qqq_chg >= 0 else "#c0392b"
    qqq_arrow = "▲" if qqq_chg >= 0 else "▼"
    qqq_price = f'${qqq.get("close","--")}' if qqq else "$--"
    qqq_sign  = "+" if qqq_chg >= 0 else ""
 
    def stock_row(ticker, name):
        q = quotes.get(ticker, {})
        if not q: return ""
        chg   = q.get("change", 0)
        color = "#c9a84c" if chg >= 0 else "#c0392b"
        arrow = "▲" if chg >= 0 else "▼"
        sign  = "+" if chg >= 0 else ""
        return f"""<div class="row">
          <span class="sym">{ticker}</span>
          <span class="co">{name}</span>
          <span class="px">${q['close']}</span>
          <span class="ch" style="color:{color}">{arrow}{sign}{abs(chg):.2f}%</span>
        </div>"""
 
    def macro_row(key):
        m = macro.get(key, {})
        if not m: return ""
        label = m.get("label", key)
        chg   = m.get("change", 0)
        color = "#c9a84c" if chg >= 0 else "#c0392b"
        arrow = "▲" if chg >= 0 else "▼"
        sign  = "+" if chg >= 0 else ""
        val   = f'{m["close"]}%' if key in ("TNX", "VIX") else f'${m["close"]}'
        return f"""<div class="row">
          <span class="sym">{label}</span>
          <span class="co"></span>
          <span class="px">{val}</span>
          <span class="ch" style="color:{color}">{arrow}{sign}{abs(chg):.2f}%</span>
        </div>"""
 
    stocks_html = "".join(stock_row(t, n) for t, n in QQQ_HOLDINGS.items() if t != "QQQ")
    macro_html  = macro_row("TNX") + macro_row("VIX") + macro_row("OIL")
    chart_json  = json.dumps(chart_data)
 
    pat_html = "".join(
        f"<p>{strip_md(s.strip())}</p>"
        for s in pattern.split("\n") if s.strip()
    )
 
    js = """
const raw = JSON_DATA;
if (raw.length > 1) {
  const labels = raw.map(d => d.date);
  const prices = raw.map(d => d.close);
  const mn = Math.min(...prices) * 0.997;
  const mx = Math.max(...prices) * 1.003;
  const ctx = document.getElementById('sparkline').getContext('2d');
  const g = ctx.createLinearGradient(0, 0, 0, 180);
  g.addColorStop(0, 'rgba(201,168,76,0.15)');
  g.addColorStop(1, 'rgba(201,168,76,0)');
  new Chart(ctx, {
    type: 'line',
    data: { labels, datasets: [{ data: prices, borderColor: '#c9a84c',
      borderWidth: 1.5, backgroundColor: g, fill: true,
      tension: 0.4, pointRadius: 0, pointHoverRadius: 5,
      pointHoverBackgroundColor: '#c9a84c' }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: { label: c => '$' + c.parsed.y.toFixed(2) },
          backgroundColor: '#12100e', titleColor: '#6b5e3e',
          bodyColor: '#c9a84c', borderColor: '#2a2318', borderWidth: 1,
          padding: 10
        }
      },
      scales: {
        x: { display: false },
        y: { min: mn, max: mx, display: true,
          grid: { color: 'rgba(201,168,76,0.06)', drawBorder: false },
          ticks: { color: '#5a4e36', font: { size: 10, family: 'Cormorant Garamond' },
            callback: v => '$' + v.toFixed(0), maxTicksLimit: 4 }
        }
      }
    }
  });
}
""".replace("JSON_DATA", chart_json)
 
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>QQQ Daily — {date_str}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,500;0,600;1,300;1,400&family=Montserrat:wght@300;400;500;600&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg:      #0a0905;
      --surface: #0f0c08;
      --card:    #13100c;
      --border:  #1e1a12;
      --border2: #2a2318;
      --text:    #a89880;
      --dim:     #4a4030;
      --gold:    #c9a84c;
      --gold2:   #e8d4a0;
      --red:     #c0392b;
      --white:   #f0e8d8;
      --serif:   'Cormorant Garamond', Georgia, serif;
      --sans:    'Montserrat', sans-serif;
      --mono:    'Space Mono', monospace;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: var(--sans);
      font-weight: 300;
      line-height: 1.6;
      min-height: 100vh;
      background-image:
        radial-gradient(ellipse 120% 60% at 50% 0%, rgba(201,168,76,0.04) 0%, transparent 60%),
        radial-gradient(ellipse 60% 40% at 100% 100%, rgba(201,168,76,0.02) 0%, transparent 50%);
    }}
 
    /* ── MASTHEAD ── */
    .masthead {{
      border-bottom: 1px solid var(--border2);
      padding: 0 56px;
      display: flex;
      align-items: stretch;
      justify-content: space-between;
      gap: 0;
    }}
    .masthead-left {{
      padding: 36px 0;
      display: flex;
      flex-direction: column;
      justify-content: center;
      border-right: 1px solid var(--border2);
      padding-right: 48px;
    }}
    .brand {{
      font-family: var(--serif);
      font-size: 42px;
      font-weight: 300;
      font-style: italic;
      color: var(--white);
      letter-spacing: 0.02em;
      line-height: 1;
    }}
    .brand-rule {{
      width: 48px;
      height: 1px;
      background: var(--gold);
      margin: 10px 0;
      opacity: 0.6;
    }}
    .brand-sub {{
      font-family: var(--sans);
      font-size: 9px;
      font-weight: 500;
      letter-spacing: 0.25em;
      text-transform: uppercase;
      color: var(--dim);
    }}
    .masthead-center {{
      flex: 1;
      padding: 36px 48px;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .headline-text {{
      font-family: var(--serif);
      font-size: 22px;
      font-weight: 400;
      color: var(--white);
      line-height: 1.4;
      max-width: 700px;
    }}
    .headline-kicker {{
      font-family: var(--sans);
      font-size: 9px;
      font-weight: 600;
      letter-spacing: 0.25em;
      text-transform: uppercase;
      color: var(--gold);
      margin-bottom: 10px;
    }}
    .masthead-right {{
      padding: 36px 0 36px 48px;
      border-left: 1px solid var(--border2);
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: flex-end;
      min-width: 200px;
    }}
    .price-eyebrow {{
      font-family: var(--sans);
      font-size: 9px;
      font-weight: 500;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: var(--dim);
      margin-bottom: 8px;
    }}
    .price-num {{
      font-family: var(--mono);
      font-size: 40px;
      font-weight: 700;
      color: var(--white);
      line-height: 1;
      letter-spacing: -1px;
    }}
    .price-delta {{
      font-family: var(--mono);
      font-size: 13px;
      color: {qqq_color};
      margin-top: 8px;
      letter-spacing: 0.05em;
    }}
    .price-date {{
      font-family: var(--sans);
      font-size: 9px;
      color: var(--dim);
      letter-spacing: 0.15em;
      margin-top: 10px;
      text-transform: uppercase;
    }}
 
    /* ── DATELINE ── */
    .dateline {{
      padding: 10px 56px;
      border-bottom: 1px solid var(--border);
      display: flex;
      align-items: center;
      gap: 16px;
    }}
    .dateline-day {{
      font-family: var(--serif);
      font-size: 11px;
      font-style: italic;
      color: var(--dim);
      letter-spacing: 0.05em;
    }}
    .dateline-line {{
      flex: 1;
      height: 1px;
      background: linear-gradient(90deg, var(--border2), transparent);
    }}
    .dateline-edition {{
      font-family: var(--sans);
      font-size: 9px;
      font-weight: 500;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: var(--dim);
    }}
 
    /* ── COLUMNS ── */
    .columns {{
      display: grid;
      grid-template-columns: 1.1fr 0.9fr;
      border-bottom: 1px solid var(--border2);
    }}
    .col {{
      padding: 36px 56px;
    }}
    .col + .col {{
      border-left: 1px solid var(--border2);
    }}
    .col-label {{
      font-family: var(--sans);
      font-size: 8px;
      font-weight: 600;
      letter-spacing: 0.3em;
      text-transform: uppercase;
      color: var(--gold);
      padding-bottom: 12px;
      margin-bottom: 6px;
      border-bottom: 1px solid var(--border2);
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .col-label::before {{
      content: '';
      display: inline-block;
      width: 16px;
      height: 1px;
      background: var(--gold);
      opacity: 0.5;
    }}
 
    /* ── TICKER ROWS ── */
    .row {{
      display: grid;
      grid-template-columns: 56px 1fr auto 84px;
      align-items: center;
      gap: 10px;
      padding: 10px 0;
      border-bottom: 1px solid var(--border);
    }}
    .row:last-child {{ border-bottom: none; }}
    .sym {{
      font-family: var(--mono);
      font-size: 10px;
      font-weight: 700;
      color: var(--gold2);
      letter-spacing: 0.08em;
    }}
    .co {{
      font-size: 11px;
      font-weight: 300;
      color: var(--dim);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      letter-spacing: 0.03em;
    }}
    .px {{
      font-family: var(--mono);
      font-size: 11px;
      color: var(--text);
      text-align: right;
    }}
    .ch {{
      font-family: var(--mono);
      font-size: 10px;
      font-weight: 700;
      text-align: right;
      letter-spacing: 0.05em;
    }}
 
    /* ── CHART ── */
    .chart-container {{
      margin-top: 28px;
    }}
    .chart-wrap {{
      height: 180px;
      margin-top: 10px;
    }}
 
    /* ── ANALYSIS SECTION ── */
    .analysis {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      border-bottom: 1px solid var(--border2);
    }}
    .a-col {{
      padding: 36px 56px;
    }}
    .a-col + .a-col {{
      border-left: 1px solid var(--border2);
    }}
    .a-label {{
      font-family: var(--sans);
      font-size: 8px;
      font-weight: 600;
      letter-spacing: 0.3em;
      text-transform: uppercase;
      color: var(--gold);
      padding-bottom: 12px;
      margin-bottom: 16px;
      border-bottom: 1px solid var(--border2);
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    .a-label::before {{
      content: '';
      display: inline-block;
      width: 16px;
      height: 1px;
      background: var(--gold);
      opacity: 0.5;
    }}
    .a-col ul {{
      list-style: none;
      padding: 0;
    }}
    .a-col li {{
      font-family: var(--serif);
      font-size: 15px;
      font-weight: 400;
      color: var(--text);
      line-height: 1.65;
      padding: 11px 0 11px 20px;
      border-bottom: 1px solid var(--border);
      position: relative;
    }}
    .a-col li::before {{
      content: '◆';
      position: absolute;
      left: 0;
      font-size: 5px;
      color: var(--gold);
      top: 18px;
    }}
    .a-col li:last-child {{ border-bottom: none; }}
    .a-col p {{
      font-family: var(--serif);
      font-size: 15px;
      font-weight: 400;
      color: var(--text);
      line-height: 1.75;
      margin-bottom: 12px;
    }}
    .a-col p:last-child {{ margin-bottom: 0; }}
    .a-divider {{
      border: none;
      border-top: 1px solid var(--border2);
      margin: 28px 0 24px;
    }}
 
    /* ── COLOPHON ── */
    .colophon {{
      padding: 16px 56px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .colophon-left {{
      font-family: var(--serif);
      font-style: italic;
      font-size: 12px;
      color: var(--dim);
    }}
    .colophon-right {{
      font-family: var(--sans);
      font-size: 9px;
      font-weight: 500;
      letter-spacing: 0.18em;
      text-transform: uppercase;
      color: var(--dim);
    }}
 
    @media (max-width: 780px) {{
      .masthead, .dateline, .col, .a-col, .colophon {{ padding-left: 20px; padding-right: 20px; }}
      .masthead {{ flex-direction: column; }}
      .masthead-left {{ border-right: none; padding-right: 0; border-bottom: 1px solid var(--border2); padding-bottom: 24px; }}
      .masthead-right {{ border-left: none; padding-left: 0; align-items: flex-start; border-top: 1px solid var(--border2); padding-top: 24px; }}
      .columns, .analysis {{ grid-template-columns: 1fr; }}
      .col + .col, .a-col + .a-col {{ border-left: none; border-top: 1px solid var(--border2); }}
      .price-num {{ font-size: 32px; }}
      .brand {{ font-size: 34px; }}
      .headline-text {{ font-size: 18px; }}
    }}
  </style>
</head>
<body>
 
<div class="masthead">
  <div class="masthead-left">
    <div class="brand">QQQ Daily</div>
    <div class="brand-rule"></div>
    <div class="brand-sub">Nasdaq&#8209;100 &nbsp;·&nbsp; Market Intelligence</div>
  </div>
  <div class="masthead-center">
    <div class="headline-kicker">Today's Thesis</div>
    <div class="headline-text">{headline}</div>
  </div>
  <div class="masthead-right">
    <div class="price-eyebrow">QQQ Close</div>
    <div class="price-num">{qqq_price}</div>
    <div class="price-delta">{qqq_arrow} {qqq_sign}{abs(qqq_chg):.2f}%</div>
    <div class="price-date">{day_str} · {date_str}</div>
  </div>
</div>
 
<div class="dateline">
  <span class="dateline-day">Evening Edition</span>
  <div class="dateline-line"></div>
  <span class="dateline-edition">After Hours Report</span>
</div>
 
<div class="columns">
  <div class="col">
    <div class="col-label">Top Holdings</div>
    {stocks_html}
  </div>
  <div class="col">
    <div class="col-label">Macro Indicators</div>
    {macro_html}
    <div class="chart-container">
      <div class="col-label">30-Day Price</div>
      <div class="chart-wrap"><canvas id="sparkline"></canvas></div>
    </div>
  </div>
</div>
 
<div class="analysis">
  <div class="a-col">
    <div class="a-label">What Moved QQQ Today</div>
    {bullets_to_html(movers)}
  </div>
  <div class="a-col">
    <div class="a-label">Chart Pattern</div>
    {pat_html}
    <hr class="a-divider">
    <div class="a-label">What to Watch Tomorrow</div>
    {bullets_to_html(tomorrow)}
  </div>
</div>
 
<div class="colophon">
  <span class="colophon-left">Generated {time_str}</span>
  <span class="colophon-right">Data: Finnhub &nbsp;·&nbsp; Analysis: Claude AI</span>
</div>
 
<script>{js}</script>
</body>
</html>"""
 
def main():
    print("Fetching stocks...")
    quotes = fetch_stocks()
    print(f"  {len(quotes)} quotes")
    print("Fetching macro...")
    macro = fetch_macro()
    print(f"  {len(macro)} macro items")
    print("Fetching 30-day chart...")
    chart = fetch_qqq_30d()
    print(f"  {len(chart)} days")
    print("Generating analysis...")
    analysis = get_analysis(quotes, macro, chart)
    print("Building page...")
    html = build_html(quotes, macro, chart, analysis)
    with open("index.html", "w") as f:
        f.write(html)
    print("Done!")
 
if __name__ == "__main__":
    main()
 
