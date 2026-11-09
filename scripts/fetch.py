#!/usr/bin/env python3
"""Fetch US + Taiwan intraday quotes and write out/quotes.json (stdlib only).

Modes
- scheduled / manual run: every symbol in tickers.json
- on-demand run (env EXTRA_SYMBOLS="SOXX,2330,^VIX"): only those symbols

Providers
- TW stocks : TWSE MIS real-time API (tse_/otc_ auto-resolved), Yahoo fallback
- US stocks : Finnhub (if FINNHUB_API_KEY set) -> Yahoo -> Stooq (delayed, price only)
- crypto (BTC-USD, ETH-USD ...): Coinbase -> Yahoo
- GC=F, DX-Y.NYB, CL=F, ^VIX, ^GSPC, ^SOX: answered by an ETF proxy (see PROXY),
  stored under the ETF symbol with a "proxy_for" field
- other indices (^TWII, ^IXIC, ^TNX ...): Yahoo only (often 429 from GitHub runners)
"""
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "out")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TPE = timezone(timedelta(hours=8))
FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()

# Index/futures symbols that cannot be fetched reliably are answered with an ETF proxy.
# The result is stored under the ETF's own symbol with an explicit "proxy_for" field,
# so a proxy price is never mistaken for the real index/futures value.
PROXY = {
    "GC=F": ("GLD", "Gold futures (COMEX GC) - GLD is a gold ETF, not the futures price"),
    "DX-Y.NYB": ("UUP", "US Dollar Index (DXY) - UUP is a dollar-index futures ETF, not the index value"),
    "CL=F": ("USO", "WTI crude futures - USO is an oil futures ETF, not the front-month price"),
    "^VIX": ("VIXY", "VIX index - VIXY holds short-term VIX futures; its moves differ a lot from the VIX index"),
    "^GSPC": ("SPY", "S&P 500 index - SPY is an ETF; price is ~1/10 of the index level"),
    "^SOX": ("SOXX", "Semiconductor index - SOXX is an ETF, not the index value"),
}

# consecutive-failure circuit breaker per provider (skip a provider that is blocked)
FAILS = {"yahoo": 0, "finnhub": 0}
BREAK_AFTER = 3


def http_get(url, opener=None, timeout=15, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/json,*/*"})
            op = opener.open if opener else urllib.request.urlopen
            with op(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404, 429):  # retrying will not help
                raise
            last = e
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1 + i)
    raise last


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def make(price, prev, ts, **extra):
    q = {
        "price": round(price, 4),
        "prev_close": round(prev, 4) if prev else None,
        "change": round(price - prev, 4) if prev else None,
        "change_pct": round((price - prev) / prev * 100, 2) if prev else None,
        "time": iso(ts) if ts else None,
    }
    q.update(extra)
    return q


def classify(s):
    """TW / US / OTHER from the symbol shape."""
    if s.isdigit() or (len(s) > 1 and s[:-1].isdigit() and s[-1].isalpha()):
        return "TW"
    if s in PROXY or s.startswith("^") or "=" in s or s.upper().endswith("-USD"):
        return "OTHER"
    return "US"


# ---------------------------------------------------------------- providers
def yahoo(sym):
    q = urllib.parse.quote(sym)
    path = f"/v8/finance/chart/{q}?interval=1m&range=1d&includePrePost=true"
    d, err = None, None
    for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        try:
            d = json.loads(http_get("https://" + host + path))
            break
        except Exception as e:  # noqa: BLE001
            err = e
    if d is None:
        raise err
    res = (d.get("chart") or {}).get("result")
    if not res:
        return None
    r = res[0]
    m = r.get("meta") or {}
    ts = r.get("timestamp") or []
    closes = (((r.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    price = t = None
    for tt, c in zip(reversed(ts), reversed(closes)):
        if c is not None:
            price, t = c, tt
            break
    if price is None:
        price, t = m.get("regularMarketPrice"), m.get("regularMarketTime")
    if price is None:
        return None
    prev = m.get("previousClose") or m.get("chartPreviousClose")
    reg = ((m.get("currentTradingPeriod") or {}).get("regular")) or {}
    session = None
    if t and reg.get("start") and reg.get("end"):
        session = "regular" if reg["start"] <= t < reg["end"] else "extended"
    return make(
        price, prev, t,
        regular_price=m.get("regularMarketPrice"),
        session=session,
        currency=m.get("currency"),
        exchange=m.get("exchangeName"),
        name=m.get("shortName") or m.get("longName"),
        source="yahoo",
    )


def finnhub(sym):
    url = ("https://finnhub.io/api/v1/quote?symbol="
           f"{urllib.parse.quote(sym)}&token={FINNHUB_KEY}")
    d = json.loads(http_get(url))
    if not d.get("c"):
        return None
    return make(d["c"], d.get("pc"), d.get("t"),
                session=None, currency="USD", source="finnhub")


def stooq(sym):
    url = f"https://stooq.com/q/l/?s={sym.lower()}.us&f=sd2t2ohlcv&h&e=csv"
    rows = http_get(url).strip().splitlines()
    if len(rows) < 2:
        return None
    f = rows[1].split(",")
    if len(f) < 7 or f[6] in ("", "N/D"):
        return None
    return make(float(f[6]), None, None,
                session=None, currency="USD", source="stooq",
                delayed=True, stooq_datetime=f"{f[1]} {f[2]}")


def coinbase(sym):
    base = "https://api.exchange.coinbase.com/products/" + urllib.parse.quote(sym)
    d = json.loads(http_get(base + "/ticker"))
    if not d.get("price"):
        return None
    ts = datetime.fromisoformat(d["time"].replace("Z", "+00:00")).timestamp()
    extra = {}
    try:
        st = json.loads(http_get(base + "/stats"))
        extra["open_24h"] = float(st["open"])
    except Exception:  # noqa: BLE001
        pass
    return make(float(d["price"]), None, ts, session="24x7",
                currency="USD", exchange="Coinbase", source="coinbase", **extra)


def try_provider(name, fn, sym):
    if FAILS.get(name, 0) >= BREAK_AFTER:
        return None
    try:
        q = fn(sym)
    except Exception as e:  # noqa: BLE001
        print(f"[{name}] {sym}: {e}", file=sys.stderr)
        if name in FAILS:
            FAILS[name] += 1
        return None
    if q and name in FAILS:
        FAILS[name] = 0
    return q


def fetch_us(sym):
    chain = []
    if FINNHUB_KEY:
        chain.append(("finnhub", finnhub))
    chain.append(("yahoo", yahoo))
    chain.append(("stooq", stooq))
    for name, fn in chain:
        q = try_provider(name, fn, sym)
        if q:
            return q
        if name == "finnhub":
            time.sleep(1.1)  # free tier: 60 req/min
    return None


def fetch_other(sym):
    if sym.upper().endswith("-USD"):
        q = try_provider("coinbase", coinbase, sym.upper())
        if q:
            return q
    return try_provider("yahoo", yahoo, sym)


def twse(codes):
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    try:
        http_get("https://mis.twse.com.tw/stock/index.jsp", op)
    except Exception as e:  # noqa: BLE001
        print(f"[twse] cookie warmup failed: {e}", file=sys.stderr)
    out = {}
    for i in range(0, len(codes), 20):
        chunk = codes[i:i + 20]
        ex = "|".join(f"{p}_{c}.tw" for c in chunk for p in ("tse", "otc"))
        url = ("https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch="
               f"{urllib.parse.quote(ex, safe='|_.')}&json=1&delay=0&_={int(time.time() * 1000)}")
        try:
            d = json.loads(http_get(url, op))
        except Exception as e:  # noqa: BLE001
            print(f"[twse] batch failed: {e}", file=sys.stderr)
            continue
        for x in d.get("msgArray", []):
            try:
                price = float(x.get("z"))
                prev = float(x.get("y"))
            except (TypeError, ValueError):
                continue  # no trade yet -> Yahoo fallback
            ts = int(x["tlong"]) / 1000 if x.get("tlong") else None
            out[x["c"]] = make(
                price, prev, ts,
                session="regular", currency="TWD",
                exchange="TWSE" if x.get("ex") == "tse" else "TPEx",
                name=x.get("n"), source="twse-mis",
            )
    return out


def fetch_tw_fallback(code):
    for suffix in (".TW", ".TWO"):
        q = try_provider("yahoo", yahoo, code + suffix)
        if q:
            return q
    return None


# --------------------------------------------------------------------- main
def main():
    extra = [s.strip() for s in os.environ.get("EXTRA_SYMBOLS", "").split(",") if s.strip()]
    if extra:
        groups = {"TW": [], "US": [], "OTHER": []}
        for s in extra:
            groups[classify(s)].append(s)
    else:
        with open(os.path.join(ROOT, "tickers.json"), encoding="utf-8") as f:
            cfg = json.load(f)
        groups = {"TW": cfg.get("tw", []), "US": cfg.get("us", []),
                  "OTHER": cfg.get("other", [])}

    quotes, errors = {}, []

    tw = twse(groups["TW"]) if groups["TW"] else {}
    for c in groups["TW"]:
        q = tw.get(c) or fetch_tw_fallback(c)
        if q:
            quotes[c] = {"market": "TW", **q}
        else:
            errors.append(c)

    for s in groups["US"]:
        q = fetch_us(s)
        if q:
            quotes[s] = {"market": "US", **q}
        else:
            errors.append(s)
        time.sleep(0.3)

    for s in groups["OTHER"]:
        if s in PROXY:
            etf, desc = PROXY[s]
            if etf not in quotes:
                q = fetch_us(etf)
                if q:
                    quotes[etf] = {"market": "US", **q}
                time.sleep(0.3)
            if etf in quotes:
                quotes[etf].setdefault("proxy_for", []).append({"symbol": s, "note": desc})
            else:
                errors.append(s)
            continue
        q = fetch_other(s)
        if q:
            quotes[s] = {"market": "OTHER", **q}
        else:
            errors.append(s)
        time.sleep(0.3)

    now = datetime.now(timezone.utc)
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_at_taipei": now.astimezone(TPE).isoformat(timespec="seconds"),
        "mode": "on-demand" if extra else "scheduled",
        "note": "Compare each quote's 'time' with the current time to judge staleness.",
        "errors": errors,
        "quotes": quotes,
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "quotes.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"ok={len(quotes)} errors={len(errors)} {errors}")
    return 0 if quotes else 1


if __name__ == "__main__":
    sys.exit(main())
