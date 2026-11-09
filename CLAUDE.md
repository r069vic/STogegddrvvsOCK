# Quote feed — 給 Claude session 的用法

這個 repo 負責提供美股/台股盤中價格。session 取價有兩種方式:

## 1. 取排程快取(最快,秒回)
`tickers.json` 內的標的,Actions 每 5 分鐘更新一次(台股 09:00–13:30、美股盤前到盤後)。
```bash
gh api "repos/r069vic/STogegddrvvsOCK/contents/quotes.json?ref=data" -q .content | base64 -d
```
判斷新舊看每檔的 `time`,不是 `generated_at`。

## 2. 臨時查任意代號(約 30–90 秒)
```bash
scripts/q.sh SOXX,2330,^VIX
```
會觸發 workflow 並回傳價格,不需要先改 `tickers.json`。
代號規則:純數字(含 00981A 這類)= 台股;`^`、`=F`、`-USD` 開頭/結尾 = 指數/期貨/加密;其餘 = 美股。

## 3. 永久加入排程
編輯 `tickers.json` 的 `us` / `tw` / `other`,commit + push 到 `main`。

## ETF 代理(重要)
下列指數/期貨抓不到原始報價,改用 ETF 代理。資料存在 **ETF 自己的代號**底下,並帶有 `proxy_for` 欄位說明代理對象。
回報給使用者時必須註明「這是 ETF 價格,不是指數/期貨本身」。

| 要查 | 實際回傳 | 備註 |
|---|---|---|
| GC=F 黃金 | GLD | 黃金 ETF |
| DX-Y.NYB 美元指數 | UUP | 美元指數期貨 ETF |
| CL=F 原油 | USO | 原油期貨 ETF |
| ^VIX | VIXY | 短天期 VIX 期貨 ETF,走勢和 VIX 差很多 |
| ^GSPC | SPY | 價格約為指數的 1/10 |
| ^SOX | SOXX | ETF,非指數值 |

`^TWII`、`^IXIC`、`^TNX` 目前沒有可用來源。BTC-USD / ETH-USD 走 Coinbase(24 小時現價,無漲跌幅,附 `open_24h`)。

## 注意
- 只用 REST(`gh api repos/...`),GraphQL 在 session 內不可用。
- 美股來源:Finnhub(secret `FINNHUB_API_KEY` 已設定)→ Yahoo → Stooq。Yahoo 對 GitHub runner 回 429、Stooq 回 404,實際上都由 Finnhub 提供。
- Finnhub 回傳不標示盤前盤後,`session` 為空。
- 台股走 TWSE MIS 即時 API,盤後 `time` 會停在收盤時間。
