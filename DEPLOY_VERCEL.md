# V2.3 Vercel 部署與資料更新

## 運作方式

1. `scripts/build_snapshot.py` 呼叫原有 `engine.py`，計算真實上市／上櫃行情與選股分數。
2. `.github/workflows/update-selection.yml` 每個交易日盤後執行，將有效快照寫回 `data/latest-selection.json`。
3. GitHub 提交會觸發 Vercel 重新建置。Next.js 使用靜態輸出，手機開啟時不需執行 Python。

排程是臺灣時間週一至週五 18:43（UTC 10:43）。國定假日仍可能執行，但若行情與既有快照相同，不會建立新提交。GitHub 排程可能延遲，應以畫面顯示的交易日期判斷資料新舊。

開啟或重新整理網頁只會讀取目前已發布的靜態快照，不會呼叫市場資料來源。新快照需依序通過 GitHub Actions 測試及產生、Git 推送、Vercel 建置；因此不設會令人誤以為即時更新的「更新行情」按鈕。需要立即嘗試時，可在 GitHub Actions 手動執行「更新台股選股快照」。

## 第一次部署

1. 在 GitHub 確認本專案位於 `Eric-SC-Yeh/tw-stock-alpha-radar` 的 `main` 分支。
2. 前往 Vercel，選擇 **Add New → Project**，匯入上述 repository。
3. Framework Preset 選 **Next.js**，Root Directory 保留 repository 根目錄。
4. Build Command 使用 `npm run build`，安裝指令使用 `npm ci`。不需要設定執行時環境變數。
5. 部署完成後，在 GitHub 的 **Actions → 更新台股選股快照 → Run workflow** 執行首份資料更新。GitHub Actions 需要允許工作流程寫入 repository。
6. 等快照提交觸發 Vercel 自動部署後，在手機檢查交易日期、上市／上櫃涵蓋範圍及 Top 10。

若 TPEx 官方來源暫時失敗，而此前沒有完整快照，系統可先發布僅上市資料，頁面會顯示「部分市場資料」。若日期不一致或部分法人資料未驗證，也會標示資料品質未達完整狀態；已有完整快照時，單一市場失敗不會覆蓋它。

## 本機建置

```powershell
npm ci
npm run typecheck
npm run build
./.venv/Scripts/python.exe -m unittest discover -s scripts -p 'test_*.py'
```

建置結果在 `out/`。Vercel 會依 `next.config.ts` 的靜態輸出設定處理，不需啟動常駐後端。

資料計算可在 Python 3.12 環境執行：

```powershell
python -m pip install -r requirements-data.txt
python scripts/build_snapshot.py
```

## 資料限制

- 最新收盤快照來自 TWSE／TPEx 官方 OpenAPI；技術歷史來自 Yahoo Finance。
- V2.3 僅使用與官方行情同日的 Yahoo 技術資料，官方與 Yahoo 收盤價差超過 2% 時排除該股；這是資料口徑防護，不代表除權息調整已完成。
- 法人資料必須有可核對的同日日期；缺漏或欄位無法辨認者不給籌碼分，尚無 5／20 日累計。
- Yahoo Finance 或官方端點暫時不可用時，快照可能延後更新。不要把最後更新時間視為盤中即時行情。
- V2.1 Streamlit 入口 `app.py` 仍保留作舊版使用。V2.3 的網站入口是 `app/page.tsx`。
