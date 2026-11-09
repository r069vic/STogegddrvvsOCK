#!/usr/bin/env python3
"""Fetch US + Taiwan intraday quotes and write out/quotes.json (stdlib only).

- TW stocks: TWSE MIS real-time API (tse_/otc_ auto-resolved), Yahoo fallback.
- US stocks / indices / futures / crypto: Yahoo Finance chart API (1m bars, incl. pre/post).
"""
import http.cookiejar
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "out")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
TPE = timezone(timedelta(hours=8))


def http_get(url, opener=None, timeout=15, retries=2):
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/json,*/*"})
            op = opener.open if opener else urllib.request.urlopen
            with op(req, timeout=timeout) as r:
                return r.read().decode("utf-8")
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


def yahoo(sym):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/"
           f"{urllib.parse.quote(sym)}?interval=1m&range=1d&includePrePost=true")
    d = json.loads(http_get(url))
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


def main():
    with open(os.path.join(ROOT, "tickers.json"), encoding="utf-8") as f:
        cfg = json.load(f)

    quotes, errors = {}, []

    tw_codes = cfg.get("tw", [])
    tw = twse(tw_codes) if tw_codes else {}
    for c in tw_codes:
        if c in tw:
            quotes[c] = {"market": "TW", **tw[c]}
            continue
        q = None
        for suffix in (".TW", ".TWO"):
            try:
                q = yahoo(c + suffix)
            except Exception as e:  # noqa: BLE001
                print(f"[yahoo] {c}{suffix}: {e}", file=sys.stderr)
            if q:
                break
        if q:
            quotes[c] = {"market": "TW", **q}
        else:
            errors.append(c)

    for market, key in (("US", "us"), ("OTHER", "other")):
        for s in cfg.get(key, []):
            try:
                q = yahoo(s)
            except Exception as e:  # noqa: BLE001
                print(f"[yahoo] {s}: {e}", file=sys.stderr)
                q = None
            if q:
                quotes[s] = {"market": market, **q}
            else:
                errors.append(s)
            time.sleep(0.2)

    now = datetime.now(timezone.utc)
    payload = {
        "generated_at": now.isoformat(timespec="seconds"),
        "generated_at_taipei": now.astimezone(TPE).isoformat(timespec="seconds"),
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
