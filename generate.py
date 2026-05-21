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

def fh_quote(symbol, extended=False):
    try:
        r = requests.get(f"{FINNHUB_URL}/quote",
                         params={"symbol": symbol, "token": FINNHUB_KEY},
                         timeout=10)
        d = r.json()
        if d.get("c") and d["c"] != 0:
            price = round(float(d["c"]), 2)
            prev  = round(float(d["pc"]), 2)
            chg   = round(((price - prev) / prev) * 100, 2) if prev else 0
            q = {"close": price, "change": chg, "prev": prev}
            if extended:
                q["high"]  = round(float(d.get("h", 0)), 2)
                q["low"]   = round(float(d.get("l", 0)), 2)
                q["h52"]   = round(float(d.get("h", 0)), 2)
                q["l52"]   = round(float(d.get("l", 0)), 2)
            return q
    except Exception as e:
        print(f"  Error {symbol}: {e}")
    return None

def fh_metric(symbol):
    """Fetch 52-week high/low from Finnhub basic financials."""
    try:
        r = requests.get(f"{FINNHUB_URL}/stock/metric",
                         params={"symbol": symbol, "metric": "all", "token": FINNHUB_KEY},
                         timeout=10)
        d = r.json().get("metric", {})
        return {
            "h52": round(float(d.get("52WeekHigh", 0)), 2),
            "l52": round(float(d.get("52WeekLow", 0)), 2),
            "vol": d.get("10DayAverageTradingVolume", None),
        }
    except:
        return {}

def fetch_stocks():
    result = {}
    for ticker in QQQ_HOLDINGS:
        print(f"  {ticker}...")
        q = fh_quote(ticker, extended=(ticker == "QQQ"))
        if q:
            result[ticker] = q
        time.sleep(0.4)
    # Fetch 52w range and avg volume for QQQ separately
    print("  QQQ metrics...")
    m = fh_metric("QQQ")
    if m and "QQQ" in result:
        result["QQQ"].update(m)
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
    """30-day QQQ daily OHLCV via Yahoo Finance chart API — no key needed."""
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/QQQ",
            params={"interval": "1d", "range": "35d"},
            headers={"User-Agent": "Mozilla/5.0 (compatible)"},
            timeout=10
        )
        data   = r.json()["chart"]["result"][0]
        times  = data["timestamp"]
        closes = data["indicators"]["quote"][0]["close"]
        highs  = data["indicators"]["quote"][0]["high"]
        lows   = data["indicators"]["quote"][0]["low"]
        vols   = data["indicators"]["quote"][0]["volume"]
        result = []
        for t, c, h, l, v in zip(times, closes, highs, lows, vols):
            if c is None: continue
            result.append({
                "date":   datetime.fromtimestamp(t).strftime("%b %-d"),
                "close":  round(float(c), 2),
                "high":   round(float(h), 2) if h else None,
                "low":    round(float(l), 2) if l else None,
                "volume": int(v) if v else None,
            })
        print(f"  Chart: {len(result)} days OK")
        return result
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
    prices = [d["close"] for d in chart_data[-15:]]
    # Build volume context for prompt
    vol_context = ""
    if chart_data and len(chart_data) >= 5:
        recent = chart_data[-5:]
        vol_lines = []
        for d in recent:
            if d.get("volume"):
                vol_lines.append(f"{d['date']}: close ${d['close']}, vol {d['volume']/1e6:.1f}M")
        if vol_lines:
            vol_context = "\nRECENT DAILY DETAIL (close + volume):\n" + "\n".join(vol_lines)

    prompt = f"""You are a veteran technical analyst and day trader with 15 years of experience writing nightly market intelligence for serious active traders.

HOLDINGS (today's close and % change):
{holdings_lines}

MACRO:
{macro_lines}

30-DAY QQQ CLOSES (oldest to newest): {prices}{vol_context}

Write a tight, specific nightly briefing in exactly four sections. Plain text only — no markdown, no asterisks, no bold. Write like a sharp trader talking to another sharp trader. Be specific: use price levels, volume figures, and pattern names. No vague language.

SECTION 1 - HEADLINE
One punchy sentence — the single most important thing that happened today.

SECTION 2 - MOVERS
5 bullets starting with a dash. For each mover: name the stock or macro item, state the exact move, then give the specific technical or fundamental reason. Reference actual price levels where relevant.

SECTION 3 - CHART
Analyze the 30-day price action like a trader. Name the pattern. Identify key support and resistance levels from the data. Then give two specific scenarios:
- The bullish case: what the pattern suggests if buyers hold, with a specific price target
- The bearish case: what breaks down and where support is, with specific levels
Then name the one key tell — the specific signal (price level, volume, candle type) that will confirm which scenario is playing out.
Close with one sentence: this is technical analysis, not a prediction — macro events can override any chart setup overnight.

SECTION 4 - TOMORROW
3 bullets starting with a dash. Each bullet names a specific catalyst (not vague — name the actual event, speaker, or data release), then gives a crisp bullish outcome and bearish outcome with price implications for QQQ.

Tone: experienced trader, direct, no hedging waffle, no financial advice disclaimers beyond what is specified above."""
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


def calc_rsi(prices, period=14):
    """Calculate RSI from a list of closing prices."""
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    if not gains or not losses:
        return None
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs  = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)

def build_html(quotes, macro, chart_data, analysis):
    et       = pytz.timezone("America/New_York")
    now      = datetime.now(et)
    date_str = now.strftime("%B %-d, %Y").upper()
    time_str = now.strftime("%-I:%M %p ET")
    day_str  = now.strftime("%A").upper()

    # RSI from chart data
    chart_prices = [d["close"] for d in chart_data]
    rsi_val = calc_rsi(chart_prices)
    rsi_str  = f"{rsi_val}" if rsi_val else "--"

    headline = extract_section(analysis, "SECTION 1 - HEADLINE")
    movers   = extract_section(analysis, "SECTION 2 - MOVERS")
    pattern  = extract_section(analysis, "SECTION 3 - CHART")
    tomorrow = extract_section(analysis, "SECTION 4 - TOMORROW")

    qqq       = quotes.get("QQQ", {})
    qqq_chg   = qqq.get("change", 0)
    qqq_color = "#a78bfa" if qqq_chg >= 0 else "#f87171"
    qqq_arrow = "▲" if qqq_chg >= 0 else "▼"
    qqq_price = f'${qqq.get("close","--")}' if qqq else "$--"
    qqq_sign  = "+" if qqq_chg >= 0 else ""
    qqq_high  = qqq.get("high", "--")
    qqq_low   = qqq.get("low",  "--")
    qqq_prev  = qqq.get("prev", "--")
    qqq_h52   = qqq.get("h52",  "--")
    qqq_l52   = qqq.get("l52",  "--")

    def stock_row(ticker, name):
        q = quotes.get(ticker, {})
        if not q: return ""
        chg   = q.get("change", 0)
        color = "#a78bfa" if chg >= 0 else "#f87171"
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
        color = "#a78bfa" if chg >= 0 else "#f87171"
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
  const vols   = raw.map(d => d.volume || 0);
  const maxVol = Math.max(...vols);
  const mn = Math.min(...prices) * 0.995;
  const mx = Math.max(...prices) * 1.005;

  const priceCtx = document.getElementById('sparkline').getContext('2d');
  const g = priceCtx.createLinearGradient(0, 0, 0, 140);
  g.addColorStop(0, 'rgba(167,139,250,0.18)');
  g.addColorStop(1, 'rgba(167,139,250,0)');

  new Chart(priceCtx, {
    type: 'line',
    data: { labels, datasets: [{ data: prices, borderColor: '#a78bfa',
      borderWidth: 2, backgroundColor: g, fill: true,
      tension: 0.3, pointRadius: 0, pointHoverRadius: 5,
      pointHoverBackgroundColor: '#a78bfa' }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: i => i[0].label,
            label: i => {
              const d = raw[i[0].dataIndex];
              const lines = ['Close: $' + i[0].parsed.y.toFixed(2)];
              if (d.high)   lines.push('High:  $' + d.high.toFixed(2));
              if (d.low)    lines.push('Low:   $' + d.low.toFixed(2));
              if (d.volume) lines.push('Vol:   ' + (d.volume/1e6).toFixed(1) + 'M');
              return lines;
            }
          },
          backgroundColor: '#0d0e12', titleColor: '#c0c8e8',
          bodyColor: '#a78bfa', borderColor: '#252838', borderWidth: 1, padding: 10
        }
      },
      scales: {
        x: { display: false },
        y: { min: mn, max: mx, display: true, position: 'right',
          grid: { color: 'rgba(167,139,250,0.05)', drawBorder: false },
          ticks: { color: '#7880a8', font: { size: 10 },
            callback: v => '$' + v.toFixed(0), maxTicksLimit: 5 }
        }
      }
    }
  });

  // Volume bars
  const volCtx = document.getElementById('volbars').getContext('2d');
  new Chart(volCtx, {
    type: 'bar',
    data: { labels, datasets: [{ data: vols,
      backgroundColor: raw.map((d, i) =>
        i === 0 ? 'rgba(167,139,250,0.3)' :
        d.close >= raw[i-1].close ? 'rgba(167,139,250,0.45)' : 'rgba(248,113,113,0.35)'
      ),
      borderWidth: 0, borderRadius: 1 }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: {
        callbacks: { label: i => (i.parsed.y/1e6).toFixed(1) + 'M shares' },
        backgroundColor: '#0d0e12', bodyColor: '#7880a8',
        borderColor: '#252838', borderWidth: 1, padding: 8
      }},
      scales: {
        x: { display: false },
        y: { display: false, min: 0, max: maxVol * 3 }
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
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;0,600;1,300;1,400&family=Inter:wght@300;400;500;600&family=Space+Mono:wght@400;700&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg:      #0d0e12;
      --surface: #11131a;
      --card:    #11131a;
      --border:  #1c1f2a;
      --border2: #252838;
      --text:    #c0c8e8;
      --dim:     #7880a8;
      --gold:    #a78bfa;
      --gold2:   #c0c8e8;
      --red:     #f87171;
      --white:   #e8ecf8;
      --serif:   'Cormorant Garamond', Georgia, serif;
      --sans:    'Inter', sans-serif;
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
        radial-gradient(ellipse 120% 60% at 50% 0%, rgba(167,139,250,0.04) 0%, transparent 60%),
        radial-gradient(ellipse 60% 40% at 100% 100%, rgba(167,139,250,0.02) 0%, transparent 50%);
    }}

    /* ── MASTHEAD ── */
    .masthead {{
      border-bottom: 1px solid var(--border2);
      padding: 0 56px;
      display: grid;
      grid-template-columns: 180px 1fr 1fr;
      align-items: stretch;
      gap: 0;
    }}
    .masthead-brand {{
      padding: 32px 40px 32px 0;
      border-right: 1px solid var(--border2);
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .brand {{
      font-family: var(--serif);
      font-size: 38px;
      font-weight: 300;
      font-style: italic;
      color: var(--white);
      letter-spacing: 0.02em;
      line-height: 1;
    }}
    .brand-rule {{
      width: 40px;
      height: 1px;
      background: var(--gold);
      margin: 10px 0;
      opacity: 0.4;
    }}
    .brand-sub {{
      font-family: var(--sans);
      font-size: 8px;
      font-weight: 500;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      color: var(--dim);
    }}
    .masthead-price {{
      padding: 32px 40px;
      border-right: 1px solid var(--border2);
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .price-eyebrow {{
      font-family: var(--sans);
      font-size: 8px;
      font-weight: 500;
      letter-spacing: 0.2em;
      text-transform: uppercase;
      color: var(--dim);
      margin-bottom: 10px;
    }}
    .price-row {{
      display: flex;
      align-items: baseline;
      gap: 16px;
      margin-bottom: 14px;
    }}
    .price-num {{
      font-family: var(--mono);
      font-size: 44px;
      font-weight: 700;
      color: var(--white);
      line-height: 1;
      letter-spacing: -2px;
    }}
    .price-delta {{
      font-family: var(--mono);
      font-size: 16px;
      font-weight: 700;
      letter-spacing: 0.03em;
    }}
    .price-stats {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px 0;
      align-items: center;
    }}
    .pstat {{
      font-family: var(--mono);
      font-size: 10px;
      color: var(--text);
    }}
    .pstat-l {{
      color: var(--dim);
      margin-right: 4px;
      font-size: 9px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .pstat-sep {{
      color: var(--border2);
      margin: 0 8px;
      font-size: 12px;
    }}
    .masthead-thesis {{
      padding: 32px 0 32px 40px;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .headline-kicker {{
      font-family: var(--sans);
      font-size: 8px;
      font-weight: 600;
      letter-spacing: 0.25em;
      text-transform: uppercase;
      color: var(--gold);
      margin-bottom: 12px;
    }}
    .headline-text {{
      font-family: var(--serif);
      font-size: 20px;
      font-weight: 400;
      color: #e8ecf8;
      line-height: 1.45;
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
      color: #7880a8;
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
      height: 150px;
      margin-top: 10px;
    }}
    .vol-wrap {{
      height: 40px;
      margin-top: 3px;
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
      font-family: var(--sans);
      font-size: 14px;
      font-weight: 400;
      color: #c0c8e8;
      line-height: 1.75;
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
      font-family: var(--sans);
      font-size: 14px;
      font-weight: 400;
      color: #c0c8e8;
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
      .masthead {{ grid-template-columns: 1fr; }}
      .masthead-brand {{ border-right: none; padding-right: 0; border-bottom: 1px solid var(--border2); }}
      .masthead-price {{ border-right: none; border-bottom: 1px solid var(--border2); }}
      .masthead-thesis {{ padding-left: 0; }}
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
  <div class="masthead-brand">
    <div class="brand">QQQ Daily</div>
    <div class="brand-rule"></div>
    <div class="brand-sub">Nasdaq&#8209;100 &nbsp;·&nbsp; Evening Report</div>
  </div>
  <div class="masthead-price">
    <div class="price-eyebrow">QQQ · {day_str} · {date_str}</div>
    <div class="price-row">
      <div class="price-num">{qqq_price}</div>
      <div class="price-delta" style="color:{qqq_color}">{qqq_arrow} {qqq_sign}{abs(qqq_chg):.2f}%</div>
    </div>
    <div class="price-stats">
      <span class="pstat"><span class="pstat-l">H</span> ${qqq_high}</span>
      <span class="pstat-sep">·</span>
      <span class="pstat"><span class="pstat-l">L</span> ${qqq_low}</span>
      <span class="pstat-sep">·</span>
      <span class="pstat"><span class="pstat-l">Prev</span> ${qqq_prev}</span>
      <span class="pstat-sep">·</span>
      <span class="pstat"><span class="pstat-l">52W H</span> ${qqq_h52}</span>
      <span class="pstat-sep">·</span>
      <span class="pstat"><span class="pstat-l">52W L</span> ${qqq_l52}</span>
      <span class="pstat-sep">·</span>
      <span class="pstat"><span class="pstat-l">RSI 14</span> {rsi_str}</span>
    </div>
  </div>
  <div class="masthead-thesis">
    <div class="headline-kicker">Today's Thesis</div>
    <div class="headline-text">{headline}</div>
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
    <div class="vol-wrap"><canvas id="volbars"></canvas></div>
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
