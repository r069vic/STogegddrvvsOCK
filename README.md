# STogegddrvvsOCK (market quotes feed)

GitHub Actions 定時抓美股 / 台股(及指數、黃金、原油、DXY、BTC/ETH)盤中價格,發佈到 `data` 分支的 `quotes.json`,讓 Claude 直接讀取。

## 資料來源
- 台股:TWSE MIS 即時 API(上市/上櫃自動判斷),失敗時退回 Yahoo(`.TW` / `.TWO`,約延遲 20 分鐘)
- 美股 / 指數 / 期貨 / 加密貨幣:Yahoo Finance chart API(1 分鐘 K,含盤前盤後)

## 讀取
```
https://raw.githubusercontent.com/r069vic/STogegddrvvsOCK/data/quotes.json?t=<任意數字>
```
- repo 必須是 **public**,Claude 的 WebFetch 才讀得到
- 每次請求要帶不同的 `?t=`,否則 WebFetch 會有 15 分鐘快取
- 每筆資料有 `time`(該價格的時間)與 `session`(regular / extended),判斷新舊請看 `time`,不是 `generated_at`

## 改標的
編輯 `tickers.json`(`us` / `tw` / `other`),commit 後下一輪排程生效。

## 注意
- GitHub 排程最短 5 分鐘,實際常延遲 5–15 分鐘,不保證準時
- 若 60 天內 repo 無 commit,排程會被 GitHub 自動停用(`data` 分支的 push 不一定算);到 Actions 頁面手動 Run workflow 即可重啟
- 這是報價參考,不是下單用的逐筆資料

## 給 Claude 的使用指示(可貼到 Project instructions)
需要美股/台股即時價格時,用 WebFetch 讀
`https://raw.githubusercontent.com/r069vic/STogegddrvvsOCK/data/quotes.json?t=<目前時間戳>`,
回答時註明該標的的 `time` 與 `source`,若 `time` 距現在過久要說明資料可能過期。
