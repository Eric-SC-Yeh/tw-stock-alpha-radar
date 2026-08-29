from __future__ import annotations

import pandas as pd
import streamlit as st
import plotly.express as px

from engine import Config, build_screen, explain

st.set_page_config(
    page_title="TW Stock Alpha Radar V2.1",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
<style>
:root{--line:#d8e9f6;--soft:#eff8ff;--ink:#17324a;--sub:#607d93}
.stApp{background:linear-gradient(180deg,#f9fcff 0%,#edf7ff 100%);color:var(--ink)}
.block-container{padding-top:.65rem;padding-bottom:5rem;max-width:1180px}
#MainMenu, footer{visibility:hidden}
header[data-testid="stHeader"]{background:rgba(249,252,255,.82);backdrop-filter:blur(10px)}
.hero{padding:16px 17px;border-radius:20px;background:linear-gradient(120deg,#fff,#e9f6ff);border:1px solid var(--line);box-shadow:0 7px 24px rgba(25,75,110,.07);margin-bottom:10px}
.hero h1{font-size:27px;margin:0;line-height:1.18}.hero p{margin:7px 0 0;color:var(--sub);font-size:14px}
.source-chip{display:inline-block;margin-top:9px;padding:5px 9px;border-radius:999px;background:#e8f5ff;color:#315d7a;font-size:12px}
[data-testid="stMetric"]{background:rgba(255,255,255,.94);border:1px solid var(--line);padding:12px;border-radius:16px;box-shadow:0 5px 18px rgba(25,75,110,.05)}
[data-testid="stMetricLabel"]{font-size:12px}[data-testid="stMetricValue"]{font-size:22px}
div[data-testid="stDataFrame"]{border:1px solid var(--line);border-radius:16px;overflow:hidden;background:white}
.stTabs [data-baseweb="tab-list"]{gap:6px;overflow-x:auto;padding-bottom:3px}
.stTabs [data-baseweb="tab"]{height:42px;white-space:nowrap;border-radius:12px;background:#f4f9fd;padding:0 13px}
.stTabs [aria-selected="true"]{background:#dff1ff!important}
div.stButton>button,div.stDownloadButton>button{border-radius:14px;min-height:44px}
.stock-card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:13px 14px;margin:8px 0;box-shadow:0 5px 18px rgba(25,75,110,.05)}
.stock-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.stock-name{font-weight:750;font-size:18px}.stock-code{color:#7590a3;font-size:12px}.stock-score{font-size:24px;font-weight:800}.stock-tags{margin-top:8px;color:#476b84;font-size:13px}.risk{color:#a84242}.good{color:#177245}
.mobile-note{font-size:12px;color:#708b9f;margin:4px 0 10px}
@media(max-width:700px){
 .block-container{padding-left:.75rem;padding-right:.75rem;padding-top:.35rem}
 .hero{padding:14px}.hero h1{font-size:23px}.hero p{font-size:13px}
 [data-testid="column"]{min-width:0!important}
 div[data-testid="stHorizontalBlock"]{gap:.45rem}
 [data-testid="stMetric"]{padding:9px 10px;border-radius:14px}
 [data-testid="stMetricLabel"]{font-size:11px}[data-testid="stMetricValue"]{font-size:18px}
 .stTabs [data-baseweb="tab"]{padding:0 11px;font-size:13px}
 .stock-name{font-size:16px}.stock-score{font-size:21px}
 h2{font-size:1.35rem!important}h3{font-size:1.1rem!important}
}
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    """
<div class="hero">
  <h1>📈 TW Stock Alpha Radar <b>V2.1 Mobile</b></h1>
  <p>台股短線選股雷達｜手機優先 · TWSE + TPEx · 100 分評分 · 飆股雷達 · ATR 交易計畫</p>
  <span class="source-chip">真實資料模式｜非示意數據</span>
</div>
""",
    unsafe_allow_html=True,
)

# Mobile-friendly controls in an expander instead of permanent sidebar.
with st.expander("⚙️ 選股設定", expanded=False):
    c1, c2 = st.columns(2)
    with c1:
        min_value_b = st.slider("最低日成交額（億元）", 5, 50, 10, 1)
        max_bias = st.slider("MA20 最大乖離（%）", 8, 25, 15, 1)
    with c2:
        warn_bias = st.slider("過熱扣分起點（%）", 5, max_bias, min(10, max_bias), 1)
        liquid_n = st.slider("每市場完整分析檔數", 40, 250, 100, 10)
    top_n = st.slider("Top N", 5, 20, 10, 1)
    refresh = st.button("🔄 更新今日真實資料", use_container_width=True, type="primary")
    st.caption("手機版預設每市場分析 100 檔，以兼顧雲端速度；可自行調高。")

cfg = Config(
    min_trade_value=min_value_b * 100_000_000,
    max_ma20_bias=float(max_bias),
    warn_ma20_bias=float(warn_bias),
    top_liquid_per_market=int(liquid_n),
    top_n=int(top_n),
)

@st.cache_data(ttl=1800, show_spinner=False)
def load_data(minv, maxb, warnb, liquid):
    c = Config(
        min_trade_value=minv,
        max_ma20_bias=maxb,
        warn_ma20_bias=warnb,
        top_liquid_per_market=liquid,
    )
    return build_screen(c)

if refresh:
    st.cache_data.clear()

with st.spinner("更新上市/上櫃行情與技術指標…"):
    df, market, errors = load_data(
        cfg.min_trade_value,
        cfg.max_ma20_bias,
        cfg.warn_ma20_bias,
        cfg.top_liquid_per_market,
    )

if errors:
    with st.expander("ℹ️ 資料來源狀態", expanded=False):
        for e in errors:
            st.warning(e)

if df.empty:
    st.error("目前沒有成功產生選股結果。請確認網路可用後，再按『更新今日真實資料』。")
    st.stop()

regime = market.get("regime", "Unknown")
regime_emoji = {"Bull": "🟢", "Neutral": "🟡", "Bear": "🔴", "Unknown": "⚪"}.get(regime, "⚪")
latest_date = pd.to_datetime(df["date"], errors="coerce").max()
latest_label = latest_date.strftime("%Y-%m-%d") if pd.notna(latest_date) else "Unknown"

m1, m2 = st.columns(2)
m1.metric("市場模式", f"{regime_emoji} {regime}")
m2.metric("市場分數", f"{market.get('market_score', 0)}/100")
m3, m4 = st.columns(2)
m3.metric("通過硬篩選", f"{len(df)} 檔")
m4.metric("A級以上", f"{int((df.total_score >= 80).sum())} 檔")
st.markdown(f'<div class="mobile-note">最新交易日：{latest_label}｜最新快照：TWSE / TPEx 官方 OpenAPI｜技術歷史：Yahoo Finance</div>', unsafe_allow_html=True)

# Main mobile navigation.
tab_top, tab_radar, tab_risk, tab_stock, tab_data = st.tabs(["🏆 Top 10", "🚀 飆股", "⚠️ 風險", "🔎 個股", "📦 資料"])

top = df.head(top_n).copy()

with tab_top:
    st.subheader("今日 Top 選股")
    # Card view is substantially easier to scan on phones than a 15-column table.
    for i, (_, r) in enumerate(top.iterrows(), start=1):
        tags = []
        if bool(r.get("break20", False)): tags.append("20日突破")
        if bool(r.get("break60", False)): tags.append("60日突破")
        if float(r.get("vol_ratio", 0) or 0) >= 1.5: tags.append(f"量比 {r.vol_ratio:.1f}")
        if float(r.get("foreign_net", 0) or 0) > 0: tags.append("外資買超")
        if float(r.get("trust_net", 0) or 0) > 0: tags.append("投信買超")
        tag_text = " · ".join(tags[:4]) if tags else "趨勢 / 動能綜合入選"
        st.markdown(
            f"""
<div class="stock-card">
 <div class="stock-head">
  <div><div class="stock-name">#{i}　{r['name']}</div><div class="stock-code">{r.code} · {r.market} · 收盤 {r.close:.2f}</div></div>
  <div style="text-align:right"><div class="stock-score">{r.total_score:.0f}</div><div class="stock-code">{r.grade}級</div></div>
 </div>
 <div class="stock-tags">{tag_text}</div>
 <div class="stock-tags">趨勢 {r.trend_score:.0f}/20　動能 {r.momentum_score:.0f}/20　量價 {r.volume_score:.0f}/15　爆發 {r.breakout_score:.0f}/100</div>
</div>
""",
            unsafe_allow_html=True,
        )

with tab_radar:
    st.subheader("🚀 飆股雷達")
    radar = df.sort_values(["breakout_score", "total_score"], ascending=False).head(10).copy()
    fig = px.bar(
        radar.sort_values("breakout_score"),
        x="breakout_score",
        y="name",
        orientation="h",
        hover_data=["code", "total_score", "ma20_bias", "vol_ratio"],
        labels={"breakout_score": "爆發分", "name": "股票"},
    )
    fig.update_layout(height=430, margin=dict(l=5, r=5, t=5, b=5), showlegend=False)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    for _, r in radar.head(5).iterrows():
        state = []
        if r.break20: state.append("突破20日")
        if r.break60: state.append("突破60日")
        if r.vol_ratio >= 1.5: state.append(f"放量 {r.vol_ratio:.1f}×")
        st.markdown(f"**{r.code} {r['name']}**｜爆發 {r.breakout_score:.0f}｜總分 {r.total_score:.0f}　" + " · ".join(state))

with tab_risk:
    st.subheader("⚠️ 過熱 / 風險雷達")
    risk = df[(df.risk_score < 0) | (df.rsi14 >= 75) | (df.ma20_bias >= cfg.warn_ma20_bias)].copy()
    risk = risk.sort_values(["risk_score", "ma20_bias"], ascending=[True, False]).head(12)
    if risk.empty:
        st.success("目前篩選池沒有明顯過熱警戒。")
    else:
        for _, r in risk.iterrows():
            reason = str(r.get("risk_reasons", "")) or "過熱條件觸發"
            st.markdown(
                f'<div class="stock-card"><div class="stock-head"><div><div class="stock-name">{r.code} {r["name"]}</div><div class="stock-code">總分 {r.total_score:.0f} · RSI {r.rsi14:.0f} · MA20乖離 {r.ma20_bias:.1f}%</div></div><div class="stock-score risk">{r.risk_score:.0f}</div></div><div class="stock-tags risk">{reason}</div></div>',
                unsafe_allow_html=True,
            )

with tab_stock:
    st.subheader("🔎 個股詳細分析")
    labels = [f"{r.code} {r['name']}｜{r.total_score:.0f}分" for _, r in top.iterrows()]
    choice = st.selectbox("選擇 Top 股票", labels)
    r = top.iloc[labels.index(choice)]

    a, b = st.columns(2)
    a.metric("綜合評分", f"{r.total_score:.0f}/100", r.grade)
    b.metric("爆發分", f"{r.breakout_score:.0f}/100")
    c, d = st.columns(2)
    c.metric("交易型態", f"{r.trade_type} 型")
    d.metric("ATR14", f"{r.atr14:.2f}", f"{r.atr_pct:.1f}%")
    st.info(explain(r))

    scores = pd.DataFrame({
        "模組": ["市場", "趨勢", "動能", "量價", "籌碼", "突破", "風險"],
        "分數": [r.market_score_component, r.trend_score, r.momentum_score, r.volume_score, r.institutional_score, r.breakout_score_component, r.risk_score],
    })
    fig2 = px.bar(scores, x="模組", y="分數", text="分數")
    fig2.update_layout(height=320, margin=dict(l=5, r=5, t=5, b=5), showlegend=False)
    st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

    p1, p2 = st.columns(2)
    p1.metric("收盤價", f"{r.close:.2f}")
    p2.metric("MA20", f"{r.ma20:.2f}")
    p3, p4 = st.columns(2)
    p3.metric("停損 2×ATR", f"{r.stop_loss:.2f}")
    p4.metric("移動停利啟動", f"{r.trail_trigger:.2f}")

    sigs = []
    if r.break20: sigs.append("✅ 突破20日高點")
    if r.break60: sigs.append("✅ 突破60日高點")
    if r.vol_ratio >= 1.5: sigs.append(f"✅ 量比 {r.vol_ratio:.1f}")
    if r.foreign_net > 0: sigs.append("✅ 外資當日買超")
    if r.trust_net > 0: sigs.append("✅ 投信當日買超")
    if r.rsi14 >= 80: sigs.append("⚠️ RSI 過熱")
    if r.ma20_bias >= cfg.warn_ma20_bias: sigs.append("⚠️ 月線乖離偏高")
    st.markdown("**訊號摘要**")
    st.write("　".join(sigs) if sigs else "目前沒有額外觸發訊號。")

with tab_data:
    st.subheader("📦 資料與匯出")
    show_cols = ["code", "name", "market", "close", "trade_value", "total_score", "grade", "trend_score", "momentum_score", "volume_score", "institutional_score", "breakout_score", "ma20_bias", "rsi14", "vol_ratio"]
    show = top[show_cols].copy()
    show["trade_value"] = show["trade_value"] / 100_000_000
    show.columns = ["代號", "名稱", "市場", "收盤", "成交額(億)", "總分", "等級", "趨勢", "動能", "量價", "籌碼", "爆發分", "MA20乖離%", "RSI", "量比"]
    st.dataframe(show, use_container_width=True, hide_index=True)
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ 匯出完整評分 CSV",
        csv,
        file_name=f"tw_stock_alpha_radar_{latest_label}.csv",
        mime="text/csv",
        use_container_width=True,
    )
    with st.expander("資料來源與限制"):
        st.markdown(
            """
- 最新上市行情：TWSE OpenAPI `STOCK_DAY_ALL`。
- 最新上櫃行情：TPEx OpenAPI `tpex_mainboard_daily_close_quotes`。
- 上市法人：TWSE T86；上櫃法人：TPEx 三大法人 OpenAPI。
- 歷史技術指標：Yahoo Finance `.TW` / `.TWO`，計算 MA、RSI、MACD、ATR、量比與 20/60 日突破。
- V2.1 法人仍是「當日」訊號；5/20 日法人累積留待 V3 建立每日資料庫後完成。
- 分數是篩選模型，不是報酬保證或投資建議。
"""
        )

st.caption("V2.1 Mobile · 將部署網址加入手機主畫面，即可像 App 一樣快速開啟。")
