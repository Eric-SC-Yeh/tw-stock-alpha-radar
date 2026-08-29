# TW Stock Alpha Radar V2.1 Mobile

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

- TWSE OpenAPI：上市最新行情。
- TPEx OpenAPI：上櫃最新行情。
- TWSE / TPEx 三大法人資料。
- Yahoo Finance：歷史 K 線與技術指標計算。

## 注意

V2.1 的法人籌碼仍以當日訊號為主。V3 才會加入 SQLite 每日累積，正式支援法人 5/20 日趨勢、歷史回測與模型權重校正。
