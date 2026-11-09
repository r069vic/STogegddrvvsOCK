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

## 注意
- 只用 REST(`gh api repos/...`),GraphQL 在 session 內不可用。
- 美股來源優先順序:Finnhub(需 secret `FINNHUB_API_KEY`)→ Yahoo → Stooq(延遲、無漲跌幅)。
  Yahoo 對 GitHub runner 常回 429;要穩定請設定 Finnhub key。
- 台股走 TWSE MIS 即時 API,盤後 `time` 會停在收盤時間。
