import anthropic, requests, json, time, re, os
from datetime import datetime
import pytz

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

# ── Data fetching ─────────────────────────────────────────────────────────────
def fh_quote(symbol, extended=False):
    try:
        r = requests.get(f"{FINNHUB_URL}/quote",
                         params={"symbol": symbol, "token": FINNHUB_KEY}, timeout=10)
        d = r.json()
        if d.get("c") and d["c"] != 0:
            price = round(float(d["c"]), 2)
            prev  = round(float(d["pc"]), 2)
            chg   = round(((price - prev) / prev) * 100, 2) if prev else 0
            q = {"close": price, "change": chg, "prev": prev}
            if extended:
                q["high"] = round(float(d.get("h", price)), 2)
                q["low"]  = round(float(d.get("l", price)), 2)
            return q
    except Exception as e:
        print(f"  Error {symbol}: {e}")
    return None

def fh_metric(symbol):
    try:
        r = requests.get(f"{FINNHUB_URL}/stock/metric",
                         params={"symbol": symbol, "metric": "all", "token": FINNHUB_KEY}, timeout=10)
        d = r.json().get("metric", {})
        return {"h52": round(float(d.get("52WeekHigh", 0)), 2),
                "l52": round(float(d.get("52WeekLow",  0)), 2)}
    except:
        return {}

def fetch_stocks():
    result = {}
    for ticker in QQQ_HOLDINGS:
        print(f"  {ticker}...")
        q = fh_quote(ticker, extended=(ticker == "QQQ"))
        if q: result[ticker] = q
        time.sleep(0.4)
    print("  QQQ metrics...")
    m = fh_metric("QQQ")
    if m and "QQQ" in result:
        result["QQQ"].update(m)
    time.sleep(0.4)
    return result

def fetch_macro():
    result = {}
    for sym, label, key in [("%5ETNX","10Y Yield","TNX"), ("%5EVIX","VIX","VIX")]:
        try:
            r = requests.get(
                f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                headers={"User-Agent": "Mozilla/5.0 (compatible)"}, timeout=8)
            meta  = r.json()["chart"]["result"][0]["meta"]
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
    try:
        r = requests.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/QQQ",
            params={"interval": "1d", "range": "1y"},
            headers={"User-Agent": "Mozilla/5.0 (compatible)"}, timeout=10)
        data  = r.json()["chart"]["result"][0]
        times = data["timestamp"]
        q     = data["indicators"]["quote"][0]
        result = []
        for i, t in enumerate(times):
            o, h, l, c, v = q["open"][i], q["high"][i], q["low"][i], q["close"][i], q["volume"][i]
            if c is None: continue
            dt = datetime.fromtimestamp(t)
            result.append({
                "date":   dt.strftime("%b %-d"),
                "ymd":    dt.strftime("%Y-%m-%d"),
                "open":   round(float(o), 2) if o else round(float(c), 2),
                "high":   round(float(h), 2) if h else round(float(c), 2),
                "low":    round(float(l), 2) if l else round(float(c), 2),
                "close":  round(float(c), 2),
                "volume": int(v) if v else 0,
            })
        print(f"  Chart: {len(result)} days (1Y) OK")
        return result
    except Exception as e:
        print(f"  Chart error: {e}")
        return []

# ── Analysis helpers ──────────────────────────────────────────────────────────
def calc_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains  = [d for d in deltas if d > 0]
    losses = [-d for d in deltas if d < 0]
    if not gains or not losses:
        return None
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100.0
    return round(100 - (100 / (1 + avg_gain / avg_loss)), 1)

def strip_md(text):
    text = re.sub(r'\*{1,3}', '', text)
    text = re.sub(r'_{1,3}', '', text)
    return text.strip()

def extract_section(text, header):
    try:
        start = text.index(header) + len(header)
        headers = ["SECTION 1","SECTION 2","SECTION 3","SECTION 4"]
        end = len(text)
        for h in headers:
            if h in text[start:]:
                pos = text.index(h, start)
                if pos < end: end = pos
        return strip_md(text[start:end].strip())
    except:
        return ""

def bullets_to_html(text):
    lines = []
    for line in text.split("\n"):
        line = strip_md(line.strip().lstrip("-• ").strip())
        if line: lines.append(f"<li>{line}</li>")
    return "<ul>" + "".join(lines) + "</ul>" if lines else ""

def parse_chart_section(raw):
    out = {"summary": "", "scenarios": [], "tell": "", "caveat": ""}
    sm = re.search(r"SUMMARY:\s*(.+?)(?=BULLISH|BEARISH|KEY TELL|$)", raw, re.DOTALL)
    if sm: out["summary"] = strip_md(sm.group(1).strip())
    pat = re.compile(
        r"(BULLISH|BEARISH)\s*\|\s*~?(\d+)%[^|]*\|\s*([^\n]+)\n(.*?)TRIGGER:\s*([^\n]+)",
        re.DOTALL)
    for m in pat.finditer(raw):
        out["scenarios"].append({
            "type":    m.group(1),
            "pct":     m.group(2),
            "title":   strip_md(m.group(3).strip()),
            "body":    strip_md(m.group(4).strip()),
            "trigger": strip_md(m.group(5).strip()),
        })
    tm = re.search(r"KEY TELL:\s*([^\n]+)", raw)
    if tm: out["tell"] = strip_md(tm.group(1).strip())
    cm = re.search(r"CAVEAT:\s*(.+?)$", raw, re.DOTALL)
    if cm: out["caveat"] = strip_md(cm.group(1).strip())
    return out

def scenario_cards_html(cp):
    bits = []
    if cp["summary"]:
        bits.append('<p class="chart-summary">' + cp["summary"] + '</p>')
    for s in cp["scenarios"]:
        typ   = s["type"].lower()
        color = "#a78bfa" if typ == "bullish" else "#f87171"
        bg    = "rgba(167,139,250,0.07)" if typ == "bullish" else "rgba(248,113,113,0.07)"
        lbl   = "Bullish" if typ == "bullish" else "Bearish"
        trig  = ('<div class="sc-trigger"><span>' + lbl + ' trigger:</span> ' + s["trigger"] + '</div>') if s["trigger"] else ""
        bits.append(
            '<div class="scenario-card" style="border-left:3px solid ' + color + ';background:' + bg + '">'
            '<div class="sc-header">'
            '<span class="sc-title">' + s["title"] + '</span>'
            '<span class="sc-badge" style="color:' + color + ';border-color:' + color + '">~' + s["pct"] + '% likely</span>'
            '</div>'
            '<p class="sc-body">' + s["body"] + '</p>'
            + trig + '</div>'
        )
    if cp["tell"]:
        bits.append('<div class="sc-tell"><span>Key tell:</span> ' + cp["tell"] + '</div>')
    if cp["caveat"]:
        bits.append('<p class="sc-caveat">' + cp["caveat"] + '</p>')
    return "\n".join(bits)

# ── Claude analysis ───────────────────────────────────────────────────────────
def get_analysis(quotes, macro, chart_data):
    client = anthropic.Anthropic()
    def fmt(label, q):
        sign = "+" if q["change"] >= 0 else ""
        return f"  {label}: ${q['close']} ({sign}{q['change']}%)"
    holdings_lines = "\n".join(
        fmt(QQQ_HOLDINGS.get(t, t), q) for t, q in quotes.items() if t in QQQ_HOLDINGS
    ) or "  (unavailable)"
    macro_lines = "\n".join(fmt(v["label"], v) for v in macro.values()) or "  (unavailable)"
    ohlcv_lines = "\n".join(
        f"  {d['date']}: O={d['open']} H={d['high']} L={d['low']} C={d['close']} Vol={d['volume']/1e6:.1f}M"
        for d in chart_data[-15:] if d.get("open")
    ) if chart_data else "  (no data)"

    prompt = f"""You are a veteran technical analyst and day trader with 15 years of experience.

HOLDINGS (today):
{holdings_lines}

MACRO:
{macro_lines}

30-DAY QQQ OHLCV (last 15 sessions, oldest to newest):
{ohlcv_lines}

Write a nightly briefing in exactly four sections. Plain text only. No markdown, no asterisks.

SECTION 1 - HEADLINE
One punchy sentence capturing today's dominant theme.

SECTION 2 - MOVERS
5 bullets starting with a dash. Name the stock or macro item, exact move, specific reason. Reference price levels.

SECTION 3 - CHART
First: SUMMARY: [2 sentences — name the pattern, identify key support/resistance from actual prices]

Then two scenario blocks in EXACTLY this format (no deviation):

BULLISH | ~[X]% likely | [5-word title]
[2-3 sentences: what the bull case looks like with specific upside price target]
TRIGGER: [exact price level or volume signal]

BEARISH | ~[X]% likely | [5-word title]
[2-3 sentences: what the bear case looks like with specific downside price target]
TRIGGER: [exact price level or volume signal]

KEY TELL: [one sentence — the single most important signal to watch]
CAVEAT: This is technical pattern analysis, not a prediction or financial advice — macro events can override any chart setup overnight.

SECTION 4 - TOMORROW
3 bullets starting with a dash. Name the specific catalyst, bullish outcome, bearish outcome with QQQ price implications.

Write like a trader talking to a trader. Direct, specific, no filler."""

    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text

# ── HTML builder ──────────────────────────────────────────────────────────────
def build_html(quotes, macro, chart_data, analysis):
    et       = pytz.timezone("America/New_York")
    now      = datetime.now(et)
    date_str = now.strftime("%B %-d, %Y").upper()
    time_str = now.strftime("%-I:%M %p ET")
    day_str  = now.strftime("%A").upper()

    # Stats
    chart_prices = [d["close"] for d in chart_data]
    rsi_val      = calc_rsi(chart_prices)
    rsi_str      = f"{rsi_val}" if rsi_val else "--"
    period_high  = max((d["high"]  for d in chart_data if d.get("high")),  default=None)
    period_low   = min((d["low"]   for d in chart_data if d.get("low")),   default=None)
    last_close   = chart_data[-1]["close"] if chart_data else None
    drawdown     = round((last_close - period_high) / period_high * 100, 1) if period_high and last_close else None
    ph_str       = f"${period_high:.2f}"  if period_high else "--"
    pl_str       = f"${period_low:.2f}"   if period_low  else "--"
    lc_str       = f"${last_close:.2f}"   if last_close  else "--"
    dd_str       = f"{drawdown:.1f}%"     if drawdown is not None else "--"
    dd_color     = "#a78bfa" if (drawdown or 0) >= 0 else "#f87171"

    # Parse sections
    headline          = extract_section(analysis, "SECTION 1 - HEADLINE")
    movers            = extract_section(analysis, "SECTION 2 - MOVERS")
    chart_section_raw = extract_section(analysis, "SECTION 3 - CHART")
    tomorrow          = extract_section(analysis, "SECTION 4 - TOMORROW")
    chart_parsed      = parse_chart_section(chart_section_raw)
    chart_cards       = scenario_cards_html(chart_parsed)

    # QQQ price block
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
        return (f'<div class="row"><span class="sym">{ticker}</span>'
                f'<span class="co">{name}</span>'
                f'<span class="px">${q["close"]}</span>'
                f'<span class="ch" style="color:{color}">{arrow}{sign}{abs(chg):.2f}%</span></div>')

    def macro_row(key):
        m = macro.get(key, {})
        if not m: return ""
        label = m.get("label", key)
        chg   = m.get("change", 0)
        color = "#a78bfa" if chg >= 0 else "#f87171"
        arrow = "▲" if chg >= 0 else "▼"
        sign  = "+" if chg >= 0 else ""
        val   = f'{m["close"]}%' if key in ("TNX","VIX") else f'${m["close"]}'
        return (f'<div class="row"><span class="sym">{label}</span>'
                f'<span class="co"></span>'
                f'<span class="px">{val}</span>'
                f'<span class="ch" style="color:{color}">{arrow}{sign}{abs(chg):.2f}%</span></div>')

    stocks_html = "".join(stock_row(t, n) for t, n in QQQ_HOLDINGS.items() if t != "QQQ")
    macro_html  = macro_row("TNX") + macro_row("VIX") + macro_row("OIL")
    chart_json  = json.dumps(chart_data)

    js = """
const raw = JSON_DATA;
if (raw.length > 1 && typeof LightweightCharts !== 'undefined') {
  const wrap = document.getElementById('lw-chart');
  const chart = LightweightCharts.createChart(wrap, {
    width: wrap.clientWidth || 800,
    height: 220,
    layout: { background: { color: 'transparent' }, textColor: '#7880a8' },
    grid: { vertLines: { color: 'rgba(167,139,250,0.05)' }, horzLines: { color: 'rgba(167,139,250,0.05)' } },
    crosshair: { mode: 1 },
    rightPriceScale: { borderColor: '#1c1f2a', scaleMargins: { top: 0.05, bottom: 0.28 } },
    timeScale: { borderColor: '#1c1f2a', timeVisible: true },
  });
  const candles = chart.addCandlestickSeries({
    upColor: '#a78bfa', downColor: '#f87171',
    borderUpColor: '#a78bfa', borderDownColor: '#f87171',
    wickUpColor: '#a78bfa', wickDownColor: '#f87171',
  });
  candles.setData(raw.map(d => ({ time: d.ymd, open: d.open, high: d.high, low: d.low, close: d.close })));
  const vol = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: 'vol' });
  chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  vol.setData(raw.map((d, i) => ({
    time: d.ymd, value: d.volume,
    color: i > 0 && d.close >= raw[i-1].close ? 'rgba(167,139,250,0.4)' : 'rgba(248,113,113,0.35)',
  })));
  window.addEventListener('resize', () => chart.applyOptions({ width: wrap.clientWidth }));
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
  <script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    :root {{
      --bg:#0d0e12; --surface:#11131a; --border:#1c1f2a; --border2:#252838;
      --text:#c0c8e8; --dim:#7880a8; --green:#a78bfa; --red:#f87171;
      --white:#e8ecf8; --gold:#a78bfa;
      --serif:'Cormorant Garamond',Georgia,serif;
      --sans:'Inter',sans-serif; --mono:'Space Mono',monospace;
    }}
    *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:var(--bg);color:var(--text);font-family:var(--sans);font-weight:300;line-height:1.6;min-height:100vh;
      background-image:radial-gradient(ellipse 120% 60% at 50% 0%,rgba(167,139,250,0.04) 0%,transparent 60%)}}

    /* MASTHEAD */
    .masthead{{border-bottom:1px solid var(--border2);padding:0 56px;display:grid;grid-template-columns:180px 1fr 1fr;align-items:stretch}}
    .masthead-brand{{padding:32px 40px 32px 0;border-right:1px solid var(--border2);display:flex;flex-direction:column;justify-content:center}}
    .brand{{font-family:var(--serif);font-size:38px;font-weight:300;font-style:italic;color:var(--white);line-height:1}}
    .brand-rule{{width:40px;height:1px;background:var(--gold);margin:10px 0;opacity:0.4}}
    .brand-sub{{font-family:var(--sans);font-size:8px;font-weight:500;letter-spacing:0.22em;text-transform:uppercase;color:var(--dim)}}
    .masthead-price{{padding:32px 40px;border-right:1px solid var(--border2);display:flex;flex-direction:column;justify-content:center}}
    .price-eyebrow{{font-size:8px;font-weight:500;letter-spacing:0.2em;text-transform:uppercase;color:var(--dim);margin-bottom:10px}}
    .price-row{{display:flex;align-items:baseline;gap:16px;margin-bottom:14px}}
    .price-num{{font-family:var(--mono);font-size:44px;font-weight:700;color:var(--white);line-height:1;letter-spacing:-2px}}
    .price-delta{{font-family:var(--mono);font-size:16px;font-weight:700;color:{qqq_color}}}
    .price-stats{{display:flex;flex-wrap:wrap;gap:4px}}
    .pstat{{font-family:var(--mono);font-size:10px;color:var(--text)}}
    .pstat-l{{color:var(--dim);margin-right:4px;font-size:9px;text-transform:uppercase;letter-spacing:0.08em}}
    .pstat-sep{{color:var(--border2);margin:0 6px;font-size:12px}}
    .masthead-thesis{{padding:32px 0 32px 40px;display:flex;flex-direction:column;justify-content:center}}
    .headline-kicker{{font-size:8px;font-weight:600;letter-spacing:0.25em;text-transform:uppercase;color:var(--gold);margin-bottom:12px}}
    .headline-text{{font-family:var(--serif);font-size:20px;font-weight:400;color:var(--white);line-height:1.45}}

    /* DATELINE */
    .dateline{{padding:10px 56px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:16px}}
    .dateline-day{{font-family:var(--serif);font-size:11px;font-style:italic;color:#7a6a52}}
    .dateline-line{{flex:1;height:1px;background:linear-gradient(90deg,var(--border2),transparent)}}
    .dateline-edition{{font-size:9px;font-weight:500;letter-spacing:0.2em;text-transform:uppercase;color:var(--dim)}}

    /* COLUMNS */
    .columns{{display:grid;grid-template-columns:1.1fr 0.9fr;border-bottom:1px solid var(--border2)}}
    .col{{padding:36px 56px}}
    .col+.col{{border-left:1px solid var(--border2)}}
    .col-label{{font-size:8px;font-weight:600;letter-spacing:0.3em;text-transform:uppercase;color:var(--gold);
      padding-bottom:12px;margin-bottom:6px;border-bottom:1px solid var(--border2);
      display:flex;align-items:center;gap:10px}}
    .col-label::before{{content:'';display:inline-block;width:16px;height:1px;background:var(--gold);opacity:0.5}}

    /* ROWS */
    .row{{display:grid;grid-template-columns:56px 1fr auto 84px;align-items:center;gap:10px;padding:10px 0;border-bottom:1px solid var(--border)}}
    .row:last-child{{border-bottom:none}}
    .sym{{font-family:var(--mono);font-size:10px;font-weight:700;color:var(--white);letter-spacing:0.08em}}
    .co{{font-size:11px;font-weight:300;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
    .px{{font-family:var(--mono);font-size:11px;color:var(--text);text-align:right}}
    .ch{{font-family:var(--mono);font-size:10px;font-weight:700;text-align:right;letter-spacing:0.05em}}

    /* STATS + CHART */
    .chart-container{{margin-top:28px}}
    .stat-strip{{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}}
    .stat-pill{{background:rgba(167,139,250,0.07);border:0.5px solid var(--border);border-radius:6px;
      padding:5px 10px;display:flex;flex-direction:column;align-items:center;gap:2px;flex:1;min-width:55px}}
    .sl{{font-size:8px;letter-spacing:0.12em;text-transform:uppercase;color:var(--dim)}}
    .sv{{font-family:var(--mono);font-size:11px;font-weight:700;color:var(--white)}}

    /* ANALYSIS */
    .analysis{{display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid var(--border2)}}
    .a-col{{padding:36px 56px}}
    .a-col+.a-col{{border-left:1px solid var(--border2)}}
    .a-label{{font-size:8px;font-weight:600;letter-spacing:0.3em;text-transform:uppercase;color:var(--gold);
      padding-bottom:12px;margin-bottom:16px;border-bottom:1px solid var(--border2);
      display:flex;align-items:center;gap:10px}}
    .a-label::before{{content:'';display:inline-block;width:16px;height:1px;background:var(--gold);opacity:0.5}}
    .a-col ul{{list-style:none;padding:0}}
    .a-col li{{font-size:14px;font-weight:400;color:#c0c8e8;line-height:1.75;padding:10px 0 10px 18px;
      border-bottom:1px solid var(--border);position:relative}}
    .a-col li::before{{content:'◆';position:absolute;left:0;font-size:5px;color:var(--gold);top:17px}}
    .a-col li:last-child{{border-bottom:none}}
    .a-divider{{border:none;border-top:1px solid var(--border2);margin:28px 0 24px}}

    /* SCENARIO CARDS */
    .chart-summary{{font-size:13px;color:var(--text);line-height:1.7;margin-bottom:14px}}
    .scenario-card{{border-radius:6px;padding:14px 16px;margin-bottom:10px}}
    .sc-header{{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap}}
    .sc-title{{font-size:13px;font-weight:600;color:var(--white)}}
    .sc-badge{{font-family:var(--mono);font-size:10px;font-weight:700;border:1px solid;border-radius:4px;padding:2px 7px}}
    .sc-body{{font-size:13px;color:#c0c8e8;line-height:1.7;margin:0 0 8px}}
    .sc-trigger{{font-size:12px;color:var(--dim);border-top:0.5px solid rgba(255,255,255,0.06);padding-top:8px}}
    .sc-trigger span{{font-weight:600;color:var(--text)}}
    .sc-tell{{font-size:12px;color:var(--text);background:rgba(167,139,250,0.05);
      border:0.5px solid var(--border);border-radius:6px;padding:10px 14px;margin:10px 0}}
    .sc-tell span{{font-weight:600;color:#a78bfa}}
    .sc-caveat{{font-size:11px;color:var(--dim);font-style:italic;margin-top:10px;line-height:1.6}}

    /* FOOTER */
    .colophon{{padding:16px 56px;display:flex;justify-content:space-between;align-items:center}}
    .colophon-left{{font-family:var(--serif);font-style:italic;font-size:12px;color:var(--dim)}}
    .colophon-right{{font-size:9px;font-weight:500;letter-spacing:0.18em;text-transform:uppercase;color:var(--dim)}}

    @media(max-width:780px){{
      .masthead,.dateline,.col,.a-col,.colophon{{padding-left:20px;padding-right:20px}}
      .masthead{{grid-template-columns:1fr}}
      .masthead-brand{{border-right:none;padding-right:0;border-bottom:1px solid var(--border2)}}
      .masthead-price{{border-right:none;border-bottom:1px solid var(--border2)}}
      .masthead-thesis{{padding-left:0}}
      .columns,.analysis{{grid-template-columns:1fr}}
      .col+.col,.a-col+.a-col{{border-left:none;border-top:1px solid var(--border2)}}
      .price-num{{font-size:32px}}
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
      <div class="price-delta">{qqq_arrow} {qqq_sign}{abs(qqq_chg):.2f}%</div>
    </div>
    <div class="price-stats">
      <span class="pstat"><span class="pstat-l">H</span>${qqq_high}</span>
      <span class="pstat-sep">·</span>
      <span class="pstat"><span class="pstat-l">L</span>${qqq_low}</span>
      <span class="pstat-sep">·</span>
      <span class="pstat"><span class="pstat-l">Prev</span>${qqq_prev}</span>
      <span class="pstat-sep">·</span>
      <span class="pstat"><span class="pstat-l">52W H</span>${qqq_h52}</span>
      <span class="pstat-sep">·</span>
      <span class="pstat"><span class="pstat-l">52W L</span>${qqq_l52}</span>
      <span class="pstat-sep">·</span>
      <span class="pstat"><span class="pstat-l">RSI 14</span>{rsi_str}</span>
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
      <div class="col-label" style="margin-top:28px;margin-bottom:14px">30-Day Price · Volume</div>
      <div class="stat-strip">
        <div class="stat-pill"><span class="sl">Period H</span><span class="sv">{ph_str}</span></div>
        <div class="stat-pill"><span class="sl">Period L</span><span class="sv">{pl_str}</span></div>
        <div class="stat-pill"><span class="sl">Last</span><span class="sv">{lc_str}</span></div>
        <div class="stat-pill"><span class="sl">Drawdown</span><span class="sv" style="color:{dd_color}">{dd_str}</span></div>
        <div class="stat-pill"><span class="sl">RSI 14</span><span class="sv">{rsi_str}</span></div>
      </div>
      <div id="lw-chart" style="margin-top:12px"></div>
    </div>
  </div>
</div>

<div class="analysis">
  <div class="a-col">
    <div class="a-label">What Moved QQQ Today</div>
    {bullets_to_html(movers)}
  </div>
  <div class="a-col">
    <div class="a-label">Chart Pattern &amp; Scenarios</div>
    {chart_cards}
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

# ── Main ──────────────────────────────────────────────────────────────────────
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
