"use client";

import { useMemo, useState } from "react";
import type { Snapshot, Stock } from "@/lib/types";

type Tab = "top" | "radar" | "risk" | "stock" | "data";

const tabs: { id: Tab; label: string; icon: string }[] = [
  { id: "top", label: "Top 10", icon: "🏆" },
  { id: "radar", label: "飆股", icon: "🚀" },
  { id: "risk", label: "風險", icon: "⚠️" },
  { id: "stock", label: "個股", icon: "🔎" },
  { id: "data", label: "資料", icon: "📦" },
];

function fmt(value: number | null | undefined, digits = 1): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString("zh-TW", { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : "—";
}

function fmtTaipeiTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((item) => item.type === type)?.value ?? "00";
  return `${part("year")}/${part("month")}/${part("day")} ${part("hour")}:${part("minute")}:${part("second")}`;
}

function tags(stock: Stock): string[] {
  const result: string[] = [];
  if (stock.break20) result.push("20 日突破");
  if (stock.break60) result.push("60 日突破");
  if ((stock.vol_ratio ?? 0) >= 1.5) result.push(`量比 ${fmt(stock.vol_ratio)}`);
  if ((stock.foreign_net ?? 0) > 0) result.push("外資買超");
  if ((stock.trust_net ?? 0) > 0) result.push("投信買超");
  return result;
}

function explanation(stock: Stock): string {
  const strengths: string[] = [];
  if (stock.trend_score >= 16) strengths.push("均線趨勢完整");
  if (stock.momentum_score >= 15) strengths.push("短中期動能偏強");
  if (stock.volume_score >= 10) strengths.push(`量價配合（量比 ${fmt(stock.vol_ratio)}）`);
  if (stock.institutional_score >= 9) strengths.push("法人當日籌碼偏多");
  if (stock.break20) strengths.push("突破 20 日高點");
  if (stock.break60) strengths.push("突破 60 日高點");
  return `入選主因：${strengths.slice(0, 3).join("、") || "綜合條件中性偏強"}。主要風險：${stock.risk_reasons || "無明顯過熱"}。`;
}

function downloadCsv(snapshot: Snapshot) {
  const columns: (keyof Stock)[] = [
    "date", "code", "name", "market", "close", "trade_value", "total_score",
    "grade", "trend_score", "momentum_score", "volume_score", "institutional_score",
    "breakout_score", "risk_score", "ma20_bias", "rsi14", "vol_ratio", "atr14",
    "stop_loss", "trail_trigger",
  ];
  const escape = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  const rows = [columns.join(","), ...snapshot.stocks.map((s) => columns.map((key) => escape(s[key])).join(","))];
  const blob = new Blob(["\uFEFF", rows.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `tw_stock_alpha_radar_${snapshot.trading_date || "latest"}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function StockCard({ stock, rank }: { stock: Stock; rank?: number }) {
  return (
    <article className="stock-card">
      <div className="stock-card-head">
        <div>
          <p className="eyebrow">{rank ? `#${String(rank).padStart(2, "0")} · ` : ""}{stock.code} · {stock.market}</p>
          <h3>{stock.name}</h3>
          <p className="muted">收盤 {fmt(stock.close, 2)}　成交額 {fmt((stock.trade_value ?? 0) / 100_000_000, 1)} 億</p>
        </div>
        <div className="score-block">
          <strong>{fmt(stock.total_score, 0)}</strong>
          <span>{stock.grade} 級</span>
        </div>
      </div>
      <div className="tags">{(tags(stock).length ? tags(stock).slice(0, 4) : ["趨勢與動能綜合入選"]).map((tag) => <span key={tag}>{tag}</span>)}</div>
      <p className="score-line">趨勢 {fmt(stock.trend_score, 0)}/20　動能 {fmt(stock.momentum_score, 0)}/20　量價 {fmt(stock.volume_score, 0)}/15　爆發 {fmt(stock.breakout_score, 0)}/100</p>
    </article>
  );
}

export default function Dashboard({ snapshot }: { snapshot: Snapshot }) {
  const [tab, setTab] = useState<Tab>("top");
  const [topN, setTopN] = useState(10);
  const [selectedCode, setSelectedCode] = useState(snapshot.stocks[0]?.code ?? "");
  const stocks = snapshot.stocks;
  const top = stocks.slice(0, topN);
  const radar = useMemo(() => [...stocks].sort((a, b) => b.breakout_score - a.breakout_score || b.total_score - a.total_score).slice(0, 10), [stocks]);
  const risks = useMemo(() => stocks.filter((s) => s.risk_score < 0 || (s.rsi14 ?? 0) >= 75 || (s.ma20_bias ?? 0) >= snapshot.config.warn_ma20_bias)
    .sort((a, b) => a.risk_score - b.risk_score || (b.ma20_bias ?? 0) - (a.ma20_bias ?? 0)).slice(0, 12), [stocks, snapshot.config.warn_ma20_bias]);
  const selected = top.find((s) => s.code === selectedCode) ?? top[0];
  const regimeLabel = { Bull: "多頭", Neutral: "盤整", Bear: "空頭" }[snapshot.market.regime] ?? "未取得";
  const regimeIcon = { Bull: "🟢", Neutral: "🟡", Bear: "🔴" }[snapshot.market.regime] ?? "⚪";
  const isReady = snapshot.status !== "pending" && stocks.length > 0;

  return (
    <main className="shell">
      <header className="hero">
        <div className="hero-top"><span className="brand-mark">↗</span><span className="version">V2.3 · VERCEL</span></div>
        <h1>TW Stock<br /><em>Alpha Radar</em></h1>
        <p>台股短線選股雷達 · 每日資料快照</p>
        <div className="hero-footer">
          <span className="source-pill">{snapshot.status === "ready" ? "真實資料快照" : snapshot.status === "partial" ? "部分市場資料" : "等待首份資料"}</span>
          <span>資料日 {snapshot.trading_date || "—"}</span>
        </div>
      </header>

      {!isReady ? (
        <section className="empty-state" role="status">
          <span className="empty-icon">📭</span>
          <h2>尚未建立選股快照</h2>
          <p>每日資料更新完成後會在這裡顯示真實行情。頁面不會填入示意股票或假分數。</p>
          <button className="primary-button" onClick={() => window.location.reload()}>重新載入頁面</button>
        </section>
      ) : (
        <>
          {snapshot.schema_version < 2 && <div className="coverage-alert" role="status">此為舊版快照，尚未完成技術指標與法人資料日期核對；請先將分數視為參考。</div>}
          {snapshot.status === "partial" && <div className="coverage-alert" role="status">資料品質未達完整狀態；目前涵蓋 {snapshot.coverage.join("、")}。請查看「資料」頁的來源提示，勿將排名視為完整市場結果。</div>}
          <section className="summary-grid" aria-label="市場摘要">
            <div className="metric"><span>市場模式</span><strong>{regimeIcon} {regimeLabel}</strong></div>
            <div className="metric"><span>市場分數</span><strong>{snapshot.market.regime === "Unknown" ? "—" : `${snapshot.market.market_score}/100`}</strong></div>
            <div className="metric"><span>通過硬篩選</span><strong>{stocks.length} <small>檔</small></strong></div>
            <div className="metric"><span>A 級以上</span><strong>{stocks.filter((s) => s.total_score >= 80).length} <small>檔</small></strong></div>
          </section>

          <div className="data-note">
            <span>最新交易日：{snapshot.trading_date}</span>
            <span>更新：{snapshot.generated_at ? fmtTaipeiTime(snapshot.generated_at) : "—"}</span>
            <span>開啟網頁不會即時抓取行情；平日 18:43 排程產生快照，成功發布後重開頁面即可看到新資料。</span>
          </div>

          <nav className="tabbar" aria-label="儀表板頁籤">
            {tabs.map((item) => (
              <button key={item.id} type="button" aria-current={tab === item.id ? "page" : undefined}
                className={tab === item.id ? "active" : ""} onClick={() => setTab(item.id)}>
                <span>{item.icon}</span>{item.label}
              </button>
            ))}
          </nav>

          <div className="section-head">
            <div>
              <p className="eyebrow">TW MARKET / {snapshot.trading_date}</p>
              <h2>{tabs.find((item) => item.id === tab)?.icon} {tabs.find((item) => item.id === tab)?.label}</h2>
            </div>
            {tab === "top" && <label className="select-wrap">顯示
              <select value={topN} onChange={(event) => setTopN(Number(event.target.value))}>
                <option value={5}>5 檔</option><option value={10}>10 檔</option><option value={20}>20 檔</option>
              </select>
            </label>}
          </div>

          {tab === "top" && <section className="card-stack">{top.map((stock, index) => <StockCard key={stock.code} stock={stock} rank={index + 1} />)}</section>}

          {tab === "radar" && <section className="card-stack">
            <p className="section-intro">依突破分數排序，搭配成交量與法人訊號觀察。</p>
            {radar.map((stock, index) => <article className="rank-row" key={stock.code}>
              <div className="rank-index">{String(index + 1).padStart(2, "0")}</div>
              <div className="rank-main"><strong>{stock.code} {stock.name}</strong><span>總分 {fmt(stock.total_score, 0)}　{tags(stock).slice(0, 2).join(" · ") || "無額外訊號"}</span><div className="bar"><i style={{ width: `${stock.breakout_score}%` }} /></div></div>
              <strong className="rank-score">{fmt(stock.breakout_score, 0)}</strong>
            </article>)}
          </section>}

          {tab === "risk" && <section className="card-stack">
            <p className="section-intro">過熱與風險僅在已通過硬篩選的股票中顯示。</p>
            {risks.length === 0 ? <div className="notice">目前篩選池沒有明顯過熱警戒。</div> :
              risks.map((stock) => <article className="risk-card" key={stock.code}>
                <div><strong>{stock.code} {stock.name}</strong><span className="risk-points">{fmt(stock.risk_score, 0)}</span></div>
                <p>RSI {fmt(stock.rsi14, 0)} · MA20 乖離 {fmt(stock.ma20_bias)}%</p>
                <small>{stock.risk_reasons || "過熱條件觸發"}</small>
              </article>)}
          </section>}

          {tab === "stock" && selected && <section className="card-stack">
            <label className="field-label">選擇 Top 股票
              <select className="full-select" value={selected.code} onChange={(event) => setSelectedCode(event.target.value)}>
                {top.map((s) => <option key={s.code} value={s.code}>{s.code} {s.name} · {fmt(s.total_score, 0)} 分</option>)}
              </select>
            </label>
            <article className="detail-card">
              <p className="eyebrow">{selected.market} · {selected.code}</p>
              <h3>{selected.name}</h3>
              <p className="detail-explain">{explanation(selected)}</p>
              <p className="muted">技術資料日：{selected.history_date || "未驗證"}　技術來源：{selected.source_history || "未記錄"}　法人資料日：{selected.inst_date || "未取得／未驗證"}</p>
              <div className="detail-grid">
                <div><span>綜合評分</span><strong>{fmt(selected.total_score, 0)}/100</strong></div>
                <div><span>爆發分</span><strong>{fmt(selected.breakout_score, 0)}/100</strong></div>
                <div><span>交易型態</span><strong>{selected.trade_type} 型</strong></div>
                <div><span>ATR14</span><strong>{fmt(selected.atr14, 2)}</strong></div>
                <div><span>收盤價</span><strong>{fmt(selected.close, 2)}</strong></div>
                <div><span>MA20</span><strong>{fmt(selected.ma20, 2)}</strong></div>
                <div><span>停損 2×ATR</span><strong>{fmt(selected.stop_loss, 2)}</strong></div>
                <div><span>移動停利啟動</span><strong>{fmt(selected.trail_trigger, 2)}</strong></div>
              </div>
              <h4>評分明細</h4>
              <div className="score-breakdown">
                {([["市場", selected.market_score_component], ["趨勢", selected.trend_score], ["動能", selected.momentum_score], ["量價", selected.volume_score], ["籌碼", selected.institutional_score], ["突破", selected.breakout_score_component], ["風險", selected.risk_score]] as const)
                  .map(([label, value]) => <div key={label}><span>{label}</span><strong>{fmt(value, 0)}</strong></div>)}
              </div>
            </article>
          </section>}

          {tab === "data" && <section className="card-stack">
            <button className="primary-button" onClick={() => downloadCsv(snapshot)}>⬇️ 匯出完整評分 CSV</button>
            <div className="data-table-wrap"><table><thead><tr><th>代號／名稱</th><th>收盤</th><th>總分</th><th>量比</th></tr></thead><tbody>
              {top.map((stock) => <tr key={stock.code}><td><strong>{stock.code}</strong><br />{stock.name}</td><td>{fmt(stock.close, 2)}</td><td>{fmt(stock.total_score, 0)}</td><td>{fmt(stock.vol_ratio)}</td></tr>)}
            </tbody></table></div>
            <details className="source-details"><summary>資料來源與限制</summary>
              <p>最新行情：TWSE 與 TPEx 官方 OpenAPI；技術歷史與大盤：Yahoo Finance。V2.3 僅採用交易日相符的技術資料，法人日期未驗證或缺漏時籌碼按 0 分計；尚未建立 5／20 日法人累計資料。</p>
              <p>大盤技術資料日：{snapshot.market.history_date || "未驗證"}。每個股票的來源日期可在「個股」頁查看。</p>
              <p>本頁為靜態盤後快照，重新整理不會立即重算選股；資料更新取決於排程成功、Git 推送及 Vercel 部署完成。</p>
              <p>固定條件：日成交額至少 {fmt(snapshot.config.min_trade_value / 100_000_000, 0)} 億元、MA20 乖離最多 {fmt(snapshot.config.max_ma20_bias, 0)}%、每市場分析最多 {snapshot.config.top_liquid_per_market} 檔。</p>
              {snapshot.errors.length > 0 && <p>更新時資料來源提示：{snapshot.errors.join("；")}</p>}
            </details>
          </section>}
        </>
      )}

      <footer className="footer">V2.3 Vercel · 資料為盤後選股快照，非盤中報價。評分不保證報酬，亦非個人化投資建議。</footer>
    </main>
  );
}
