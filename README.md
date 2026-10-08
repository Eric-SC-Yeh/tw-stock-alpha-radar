# TW Stock Alpha Radar V2.3 Vercel

V2.3 沿用原版評分權重，新增行情、技術歷史、大盤與法人資料的交易日核對。GitHub Actions 在盤後產生 `data/latest-selection.json`，Vercel 將 Next.js 頁面建置成靜態網站。手機開啟時直接取得已發布的快照，不會即時計算。

- 手機頁面：Top 10、飆股、風險、個股、資料與 CSV 匯出。
- 來源更新：臺灣時間週一至週五 18:43 自動執行，也可在 GitHub Actions 手動啟動。
- 更新失敗時保留既有快照；若第一次僅取得單一市場，畫面會明示涵蓋範圍。
- 頁面顯示交易日期與快照產生時間，不把盤後資料稱為即時報價。
- 日期不一致的技術資料不參與評分；法人日期缺漏時籌碼按 0 分計並標示。舊版快照會顯示尚未核對提示。

部署、資料更新與驗證方式請見 [DEPLOY_VERCEL.md](DEPLOY_VERCEL.md)。

## V2.1 Streamlit 版

手機優先的台股短線選股 Dashboard。V2.1 保留 V2 真實資料與評分引擎，將操作介面改成適合 Android / iPhone 的單欄卡片式布局。

## V2.1 新增

- 手機優先 RWD 介面。
- Top 10 改為大字卡片，不必橫向拖曳表格。
- 五個手機頁籤：Top 10 / 飆股 / 風險 / 個股 / 資料。
- 選股設定改成可收合區塊，手機畫面不被側欄占用。
- 預設每市場分析 100 檔，降低雲端 CPU / 網路負荷。
- 一鍵更新真實資料與 CSV 匯出。
- 已附 Streamlit Community Cloud / Render 部署所需檔案。

## 最推薦：部署到 Streamlit Community Cloud

1. 把整個資料夾放進 GitHub repository。
2. 進入 Streamlit Community Cloud，建立新 App。
3. Repository 選擇剛才的 GitHub repo。
4. Entry point 選 `app.py`。
5. Deploy。
6. 手機開啟產生的 `*.streamlit.app` 網址。
7. Android Chrome：選單 →「加到主畫面」。iPhone Safari：分享 →「加入主畫面」。

`requirements.txt` 已放在 `app.py` 同層，`.streamlit/config.toml` 也已就緒。

## Render 備用部署

專案已附 `render.yaml` 與 `Procfile`。建立 Render Web Service 並連結 GitHub repo 後，可使用專案內設定啟動。

## 本機測試

Windows：雙擊 `run_local_windows.bat`。

macOS：執行 `run_local_mac.command`。

## 資料來源

- TWSE OpenAPI：上市最新行情；若尚未更新，查證交所指定日期的每日收盤報表。
- TPEx OpenAPI：上櫃最新行情；若尚未更新，查櫃買中心指定日期的上櫃行情報表。兩市場日期必須一致。
- TWSE / TPEx 三大法人資料。
- Yahoo Finance：個股歷史 K 線的初始來源；若只缺官方快照當日一筆，使用同日官方開高低收與成交量補齊。
- FinMind `TaiwanStockPrice`：個股歷史缺口較長或 Yahoo 歷史不足時才查詢；須通過代碼、日期、價格與筆數檢核。
- TWSE 加權指數歷史資料：大盤技術指標優先來源；官方歷史不足時才退回 Yahoo `^TWII`。
- 備援資料仍須與上市、上櫃官方快照交易日一致；不合格個股不納入排名，來源顯示於個股頁。

## 注意

V2.1 的法人籌碼仍以當日訊號為主。V3 才會加入 SQLite 每日累積，正式支援法人 5/20 日趨勢、歷史回測與模型權重校正。
