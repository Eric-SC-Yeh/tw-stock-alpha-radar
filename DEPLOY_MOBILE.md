# 手機部署步驟

## A. Streamlit Community Cloud（推薦）

- 前置：GitHub 帳號。
- 將此資料夾的所有檔案上傳到一個 GitHub repository。
- 到 `share.streamlit.io` 建立 App。
- 選 Repository、Branch、`app.py`。
- 部署完成後得到 `https://<你的名稱>.streamlit.app`。
- 在手機 Chrome/Safari 開啟網址並加入主畫面。

## B. 介面使用

首頁會先顯示：市場模式、市場分數、通過篩選檔數、A 級以上檔數。

下方 5 個頁籤：

1. Top 10：手機卡片快速掃描。
2. 飆股：依 breakout score 排序。
3. 風險：RSI、MA20 乖離與模型扣分。
4. 個股：分項評分、ATR 停損與移動停利。
5. 資料：完整 Top 表格與 CSV 匯出。

## C. 效能建議

手機雲端版建議每市場 80~120 檔完整分析。若調到 200~250 檔，首次更新時間與雲端資源需求會明顯增加。
