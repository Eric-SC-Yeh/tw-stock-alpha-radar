from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd
import requests
import yfinance as yf

TWSE_QUOTES = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_QUOTES = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TWSE_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_INST = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"

UA = {"User-Agent": "Mozilla/5.0 TW-Stock-Alpha-Radar/2.0"}


@dataclass
class Config:
    min_trade_value: float = 1_000_000_000
    max_ma20_bias: float = 15.0
    warn_ma20_bias: float = 10.0
    history_days: int = 180
    top_liquid_per_market: int = 180
    top_n: int = 10


def _num(x, default=np.nan):
    if x is None:
        return default
    s = str(x).strip().replace(",", "").replace("+", "")
    if s in {"", "--", "---", "-", "N/A", "nan", "None"}:
        return default
    try:
        return float(s)
    except Exception:
        return default


def _int(x, default=0):
    v = _num(x, np.nan)
    return default if pd.isna(v) else int(v)


def roc_to_iso(s: str) -> str:
    s = str(s).strip().replace("/", "")
    if len(s) == 7 and s.isdigit():
        return f"{int(s[:3])+1911:04d}-{s[3:5]}-{s[5:7]}"
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(s)


def get_json(url: str, params=None, timeout=20):
    r = requests.get(url, params=params, headers=UA, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_twse_snapshot() -> pd.DataFrame:
    rows = get_json(TWSE_QUOTES)
    out = []
    for r in rows:
        code = str(r.get("Code", "")).strip()
        name = str(r.get("Name", "")).strip()
        if not re.fullmatch(r"\d{4}", code):
            continue
        close = _num(r.get("ClosingPrice"))
        trade_value = _num(r.get("TradeValue"), 0)
        out.append({
            "date": roc_to_iso(r.get("Date", "")),
            "market": "TWSE",
            "code": code,
            "name": name,
            "open": _num(r.get("OpeningPrice")),
            "high": _num(r.get("HighestPrice")),
            "low": _num(r.get("LowestPrice")),
            "close": close,
            "volume": _num(r.get("TradeVolume"), 0),
            "trade_value": trade_value,
            "change": _num(r.get("Change"), 0),
            "transactions": _num(r.get("Transaction"), 0),
            "ticker": f"{code}.TW",
            "source_latest": "TWSE OpenAPI",
        })
    return pd.DataFrame(out)


def fetch_tpex_snapshot() -> pd.DataFrame:
    rows = get_json(TPEX_QUOTES)
    out = []
    for r in rows:
        code = str(r.get("SecuritiesCompanyCode", r.get("Code", ""))).strip()
        name = str(r.get("CompanyName", r.get("Name", ""))).strip()
        if not re.fullmatch(r"\d{4}", code):
            continue
        close = _num(r.get("Close", r.get("ClosingPrice")))
        volume = _num(r.get("TradingShares", r.get("TradeVolume")), 0)
        trade_value = _num(r.get("TransactionAmount", r.get("TradeValue")), np.nan)
        if pd.isna(trade_value) and not pd.isna(close):
            trade_value = close * volume
        out.append({
            "date": roc_to_iso(r.get("Date", "")),
            "market": "TPEx",
            "code": code,
            "name": name,
            "open": _num(r.get("Open", r.get("OpeningPrice"))),
            "high": _num(r.get("High", r.get("HighestPrice"))),
            "low": _num(r.get("Low", r.get("LowestPrice"))),
            "close": close,
            "volume": volume,
            "trade_value": trade_value,
            "change": _num(r.get("Change"), 0),
            "transactions": _num(r.get("TransactionNumber", r.get("Transaction")), 0),
            "ticker": f"{code}.TWO",
            "source_latest": "TPEx OpenAPI",
        })
    return pd.DataFrame(out)


def fetch_market_snapshot() -> Tuple[pd.DataFrame, List[str]]:
    frames, errors = [], []
    for label, fn in [("TWSE", fetch_twse_snapshot), ("TPEx", fetch_tpex_snapshot)]:
        try:
            df = fn()
            if not df.empty:
                frames.append(df)
            else:
                errors.append(f"{label} 回傳空資料")
        except Exception as e:
            errors.append(f"{label} 最新行情抓取失敗：{e}")
    if not frames:
        return pd.DataFrame(), errors
    return pd.concat(frames, ignore_index=True), errors


def fetch_twse_institutional(date_yyyymmdd: str) -> pd.DataFrame:
    try:
        data = get_json(TWSE_T86, params={"date": date_yyyymmdd, "selectType": "ALL", "response": "json"})
        fields = data.get("fields", [])
        rows = data.get("data", [])
        if not fields or not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=fields)
        code_col = next((c for c in df.columns if "證券代號" in c), None)
        if not code_col:
            return pd.DataFrame()
        def findcol(keys):
            for c in df.columns:
                if all(k in c for k in keys):
                    return c
            return None
        fnet = findcol(["外陸資買賣超"])
        inet = findcol(["投信買賣超"])
        dnet = findcol(["自營商買賣超"])
        out = pd.DataFrame({"code": df[code_col].astype(str).str.strip()})
        out["foreign_net"] = df[fnet].map(_num) if fnet else 0
        out["trust_net"] = df[inet].map(_num) if inet else 0
        out["dealer_net"] = df[dnet].map(_num) if dnet else 0
        out["inst_source"] = "TWSE T86"
        return out
    except Exception:
        return pd.DataFrame()


def fetch_tpex_institutional() -> pd.DataFrame:
    try:
        rows = get_json(TPEX_INST)
        if not isinstance(rows, list) or not rows:
            return pd.DataFrame()
        def pick(d, aliases, default=0):
            for a in aliases:
                if a in d:
                    return d[a]
            return default
        out = []
        for r in rows:
            code = str(pick(r, ["SecuritiesCompanyCode", "Code", "SecuritiesCode"], "")).strip()
            if not re.fullmatch(r"\d{4}", code):
                continue
            out.append({
                "code": code,
                "foreign_net": _num(pick(r, ["ForeignInvestorsDifference", "ForeignInvestorsNetBuySell", "ForeignNet"], 0), 0),
                "trust_net": _num(pick(r, ["InvestmentTrustDifference", "InvestmentTrustNetBuySell", "InvestmentTrustNet"], 0), 0),
                "dealer_net": _num(pick(r, ["DealerDifference", "DealerNetBuySell", "DealerNet"], 0), 0),
                "inst_source": "TPEx OpenAPI",
            })
        return pd.DataFrame(out)
    except Exception:
        return pd.DataFrame()


def enrich_institutional(snapshot: pd.DataFrame) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot
    latest_date = pd.to_datetime(snapshot["date"], errors="coerce").max()
    date_str = latest_date.strftime("%Y%m%d") if pd.notna(latest_date) else datetime.now().strftime("%Y%m%d")
    tw = fetch_twse_institutional(date_str)
    tp = fetch_tpex_institutional()
    inst = pd.concat([x for x in [tw, tp] if not x.empty], ignore_index=True) if (not tw.empty or not tp.empty) else pd.DataFrame()
    out = snapshot.copy()
    if inst.empty:
        out["foreign_net"] = 0.0
        out["trust_net"] = 0.0
        out["dealer_net"] = 0.0
        out["inst_source"] = "Unavailable"
        return out
    out = out.merge(inst, on="code", how="left")
    for c in ["foreign_net", "trust_net", "dealer_net"]:
        out[c] = out[c].fillna(0)
    out["inst_source"] = out["inst_source"].fillna("Unavailable")
    return out


def download_history(tickers: List[str], period="9mo") -> Dict[str, pd.DataFrame]:
    if not tickers:
        return {}
    result = {}
    chunk = 40
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i+chunk]
        try:
            raw = yf.download(part, period=period, interval="1d", auto_adjust=False, group_by="ticker", threads=True, progress=False, timeout=30)
        except Exception:
            continue
        if len(part) == 1:
            t = part[0]
            df = raw.copy()
            if not df.empty:
                result[t] = _normalize_hist(df)
        else:
            for t in part:
                try:
                    df = raw[t].copy()
                except Exception:
                    continue
                if not df.empty:
                    result[t] = _normalize_hist(df)
        time.sleep(0.25)
    return result


def _normalize_hist(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(-1)
    d.columns = [str(c).title() for c in d.columns]
    keep = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in d.columns]
    d = d[keep].dropna(subset=["Close"])
    d.index = pd.to_datetime(d.index).tz_localize(None)
    return d


def rsi(close: pd.Series, n=14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = -delta.clip(upper=0).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def atr(df: pd.DataFrame, n=14) -> pd.Series:
    prev = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev).abs(),
        (df["Low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def macd(close: pd.Series):
    fast = close.ewm(span=12, adjust=False).mean()
    slow = close.ewm(span=26, adjust=False).mean()
    m = fast - slow
    sig = m.ewm(span=9, adjust=False).mean()
    hist = m - sig
    return m, sig, hist


def calc_indicators(df: pd.DataFrame) -> Optional[Dict[str, float]]:
    if df is None or len(df) < 65:
        return None
    d = df.copy().tail(180)
    c = d["Close"]
    for n in [5, 20, 60, 120]:
        d[f"MA{n}"] = c.rolling(n).mean()
    d["RSI14"] = rsi(c, 14)
    m, sig, hist = macd(c)
    d["MACD"] = m
    d["MACD_SIGNAL"] = sig
    d["MACD_HIST"] = hist
    d["ATR14"] = atr(d, 14)
    d["VOL5"] = d["Volume"].rolling(5).mean()
    d["VOL20"] = d["Volume"].rolling(20).mean()
    x = d.iloc[-1]
    prev20 = d["Close"].iloc[:-1].tail(20)
    prev60 = d["Close"].iloc[:-1].tail(60)
    ret5 = (c.iloc[-1] / c.iloc[-6] - 1) * 100 if len(c) >= 6 else np.nan
    ret20 = (c.iloc[-1] / c.iloc[-21] - 1) * 100 if len(c) >= 21 else np.nan
    ma20_bias = (c.iloc[-1] / x["MA20"] - 1) * 100 if pd.notna(x["MA20"]) else np.nan
    vol_ratio = x["Volume"] / x["VOL20"] if pd.notna(x["VOL20"]) and x["VOL20"] > 0 else np.nan
    atr_pct = x["ATR14"] / c.iloc[-1] * 100 if pd.notna(x["ATR14"]) and c.iloc[-1] else np.nan
    return {
        "hist_close": float(c.iloc[-1]),
        "ma5": float(x["MA5"]) if pd.notna(x["MA5"]) else np.nan,
        "ma20": float(x["MA20"]) if pd.notna(x["MA20"]) else np.nan,
        "ma60": float(x["MA60"]) if pd.notna(x["MA60"]) else np.nan,
        "ma120": float(x["MA120"]) if pd.notna(x["MA120"]) else np.nan,
        "rsi14": float(x["RSI14"]) if pd.notna(x["RSI14"]) else np.nan,
        "macd": float(x["MACD"]) if pd.notna(x["MACD"]) else np.nan,
        "macd_signal": float(x["MACD_SIGNAL"]) if pd.notna(x["MACD_SIGNAL"]) else np.nan,
        "macd_hist": float(x["MACD_HIST"]) if pd.notna(x["MACD_HIST"]) else np.nan,
        "atr14": float(x["ATR14"]) if pd.notna(x["ATR14"]) else np.nan,
        "atr_pct": float(atr_pct) if pd.notna(atr_pct) else np.nan,
        "ret5": float(ret5),
        "ret20": float(ret20),
        "ma20_bias": float(ma20_bias),
        "vol_ratio": float(vol_ratio) if pd.notna(vol_ratio) else np.nan,
        "break20": bool(c.iloc[-1] > prev20.max()) if len(prev20) else False,
        "break60": bool(c.iloc[-1] > prev60.max()) if len(prev60) else False,
    }


def market_regime() -> Dict[str, object]:
    try:
        df = yf.download("^TWII", period="9mo", interval="1d", progress=False, auto_adjust=False, timeout=20)
        df = _normalize_hist(df)
        if len(df) < 65:
            raise ValueError("TAIEX history insufficient")
        ind = calc_indicators(df)
        close = ind["hist_close"]
        points = 0
        points += 25 if close > ind["ma20"] else 0
        points += 25 if ind["ma20"] > ind["ma60"] else 0
        points += 20 if ind["ret20"] > 0 else 0
        points += 15 if 45 <= ind["rsi14"] <= 75 else (8 if ind["rsi14"] > 75 else 0)
        points += 15 if ind["macd"] > ind["macd_signal"] else 0
        regime = "Bull" if points >= 70 else ("Neutral" if points >= 45 else "Bear")
        return {"regime": regime, "market_score": int(points), **ind, "source_market": "Yahoo Finance (^TWII)"}
    except Exception as e:
        return {"regime": "Unknown", "market_score": 0, "source_market": f"Unavailable: {e}"}


def _clip(v, lo, hi):
    return max(lo, min(hi, v))


def score_row(row: pd.Series, regime: str, config: Config) -> Dict[str, object]:
    # Market 15
    market_map = {"Bull": 15, "Neutral": 9, "Bear": 3, "Unknown": 7}
    market = market_map.get(regime, 7)

    # Trend 20
    trend = 0
    trend += 4 if row.close > row.ma5 else 0
    trend += 4 if row.close > row.ma20 else 0
    trend += 4 if row.close > row.ma60 else 0
    trend += 4 if row.ma5 > row.ma20 else 0
    trend += 4 if row.ma20 > row.ma60 else 0

    # Momentum 20
    momentum = 0
    momentum += 5 if row.ret5 > 0 else 0
    momentum += 5 if row.ret20 > 0 else 0
    momentum += 5 if 50 <= row.rsi14 <= 75 else (2 if 45 <= row.rsi14 < 50 else 0)
    momentum += 5 if row.macd > row.macd_signal and row.macd_hist > 0 else 0

    # Volume/price 15
    vp = 0
    vr = row.vol_ratio if pd.notna(row.vol_ratio) else 0
    vp += 6 if vr >= 1.8 else (4 if vr >= 1.3 else (2 if vr >= 1.0 else 0))
    vp += 4 if row.ret5 > 0 and vr >= 1.0 else 0
    vp += 5 if row.break20 and vr >= 1.2 else (3 if row.break20 else 0)

    # Institutional 15: current-day real snapshot, explicitly partial
    inst = 0
    f, t, d = row.foreign_net, row.trust_net, row.dealer_net
    inst += 6 if f > 0 else 0
    inst += 6 if t > 0 else 0
    inst += 3 if d > 0 else 0

    # Breakout 10
    breakout = 0
    breakout += 5 if row.break20 else 0
    breakout += 3 if row.break60 else 0
    breakout += 2 if vr >= 1.5 else 0

    risk = 0
    reasons = []
    if row.ma20_bias >= config.warn_ma20_bias:
        risk -= 5
        reasons.append(f"MA20乖離 {row.ma20_bias:.1f}%")
    if row.rsi14 >= 80:
        risk -= 5
        reasons.append(f"RSI過熱 {row.rsi14:.0f}")
    if row.ret20 >= 30:
        risk -= 3
        reasons.append(f"20日漲幅 {row.ret20:.1f}%")
    if vr >= 4 and row.ret5 < 0:
        risk -= 2
        reasons.append("爆量轉弱")
    risk = max(-15, risk)

    total = _clip(market + trend + momentum + vp + inst + breakout + risk, 0, 100)
    breakout_score = _clip(
        (35 if row.break20 else 0) +
        (20 if row.break60 else 0) +
        min(25, max(0, (vr - 1) * 18)) +
        (10 if t > 0 else 0) +
        (10 if f > 0 else 0) -
        max(0, row.ma20_bias - 8) * 2,
        0, 100,
    )
    grade = "S" if total >= 90 else ("A" if total >= 80 else ("B" if total >= 70 else "Watch"))
    trade_type = "A" if row.atr_pct >= 3.0 else "B"
    stop = row.close - 2 * row.atr14 if pd.notna(row.atr14) else np.nan
    trigger = row.close + (5 if trade_type == "A" else 4) * row.atr14 if pd.notna(row.atr14) else np.nan
    return {
        "market_score_component": market,
        "trend_score": trend,
        "momentum_score": momentum,
        "volume_score": vp,
        "institutional_score": inst,
        "breakout_score_component": breakout,
        "risk_score": risk,
        "total_score": float(total),
        "breakout_score": float(breakout_score),
        "grade": grade,
        "risk_reasons": "、".join(reasons) if reasons else "無明顯過熱",
        "trade_type": trade_type,
        "stop_loss": float(stop) if pd.notna(stop) else np.nan,
        "trail_trigger": float(trigger) if pd.notna(trigger) else np.nan,
    }


def build_screen(config: Config = Config()) -> Tuple[pd.DataFrame, Dict[str, object], List[str]]:
    snapshot, errors = fetch_market_snapshot()
    if snapshot.empty:
        return snapshot, market_regime(), errors

    snapshot = enrich_institutional(snapshot)
    # liquid common stocks only; perform technical download only on the liquid subset
    liquid = snapshot[snapshot["trade_value"].fillna(0) >= config.min_trade_value].copy()
    liquid = (
        liquid.sort_values(["market", "trade_value"], ascending=[True, False])
        .groupby("market", group_keys=False)
        .head(config.top_liquid_per_market)
        .reset_index(drop=True)
    )

    hist = download_history(liquid["ticker"].tolist(), period="9mo")
    ind_rows = []
    for _, r in liquid.iterrows():
        ind = calc_indicators(hist.get(r.ticker))
        if ind is None:
            continue
        ind_rows.append({"ticker": r.ticker, **ind})
    inds = pd.DataFrame(ind_rows)
    if inds.empty:
        errors.append("歷史行情下載不足，無法計算技術指標")
        return pd.DataFrame(), market_regime(), errors

    df = liquid.merge(inds, on="ticker", how="inner")
    # use official latest close as source of truth; history-derived indicators remain from Yahoo
    df["close"] = df["close"].fillna(df["hist_close"])
    df = df[df["ma20_bias"].notna()].copy()
    df["excluded_overheat"] = df["ma20_bias"] > config.max_ma20_bias

    market = market_regime()
    scored = []
    for _, r in df.iterrows():
        if r.excluded_overheat:
            continue
        s = score_row(r, market.get("regime", "Unknown"), config)
        scored.append({**r.to_dict(), **s})
    out = pd.DataFrame(scored)
    if out.empty:
        return out, market, errors

    out["rank"] = out["total_score"].rank(method="first", ascending=False).astype(int)
    out = out.sort_values(["total_score", "breakout_score", "trade_value"], ascending=False).reset_index(drop=True)
    return out, market, errors


def explain(row: pd.Series) -> str:
    strengths = []
    if row.trend_score >= 16:
        strengths.append("均線趨勢完整")
    if row.momentum_score >= 15:
        strengths.append("短中期動能偏強")
    if row.volume_score >= 10:
        strengths.append(f"量價配合（量比 {row.vol_ratio:.1f}）")
    if row.institutional_score >= 9:
        strengths.append("法人當日籌碼偏多")
    if row.break20:
        strengths.append("突破20日高點")
    if row.break60:
        strengths.append("突破60日高點")
    lead = "、".join(strengths[:3]) if strengths else "綜合條件中性偏強"
    return f"入選主因：{lead}。主要風險：{row.risk_reasons}。"
