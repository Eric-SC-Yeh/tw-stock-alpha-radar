from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

TWSE_QUOTES = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
TPEX_QUOTES = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
TWSE_T86 = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_INST = "https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading"
TWSE_INDEX_HISTORY = "https://www.twse.com.tw/indicesReport/MI_5MINS_HIST"
FINMIND_DATA = "https://api.finmindtrade.com/api/v4/data"
TWSE_DAILY_REPORT = "https://www.twse.com.tw/exchangeReport/MI_INDEX"
TPEX_DAILY_REPORT = "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php"

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
    s = str(s).strip().replace("/", "").replace("-", "").replace("年", "").replace("月", "").replace("日", "")
    if len(s) == 7 and s.isdigit():
        return f"{int(s[:3])+1911:04d}-{s[3:5]}-{s[5:7]}"
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return str(s)


def valid_date(value: object) -> Optional[str]:
    """只接受來源明確提供的有效交易日期。"""
    try:
        parsed = roc_to_iso(str(value))
        return datetime.strptime(parsed, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError):
        return None


def get_json(url: str, params=None, timeout=20, attempts=4):
    for attempt in range(attempts):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError, requests.exceptions.ChunkedEncodingError) as exc:
            status = exc.response.status_code if isinstance(exc, requests.HTTPError) and exc.response is not None else None
            if attempt == attempts - 1 or (status is not None and status not in {429, 500, 502, 503, 504, 520}):
                raise
            time.sleep(2 ** attempt)


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


def fetch_twse_dated_snapshot(date: str) -> pd.DataFrame:
    """OpenAPI 尚未更新時，以證交所指定日期的每日收盤行情補位。"""
    date = valid_date(date)
    if date is None:
        return pd.DataFrame()
    payload = get_json(TWSE_DAILY_REPORT, params={
        "response": "json", "date": date.replace("-", ""), "type": "ALLBUT0999",
    }, timeout=12, attempts=2)
    if (not isinstance(payload, dict) or payload.get("stat") != "OK" or
            valid_date(payload.get("date")) != date):
        return pd.DataFrame()
    table = next((table for table in payload.get("tables", [])
                  if "每日收盤行情" in str(table.get("title", "")) and
                  {"證券代號", "證券名稱", "開盤價", "最高價", "最低價", "收盤價", "成交股數", "成交金額"}.issubset(table.get("fields", []))), None)
    if not table:
        return pd.DataFrame()
    out = []
    for row in table.get("data", []):
        item = dict(zip(table["fields"], row))
        code = str(item.get("證券代號", "")).strip()
        if not re.fullmatch(r"\d{4}", code):
            continue
        difference = _num(item.get("漲跌價差"))
        sign_text = re.sub(r"<[^>]+>", "", str(item.get("漲跌(+/-)", ""))).strip()
        change = (-difference if "-" in sign_text else difference) if pd.notna(difference) and sign_text in {"+", "-"} else np.nan
        out.append({
            "date": date, "market": "TWSE", "code": code,
            "name": str(item.get("證券名稱", "")).strip(),
            "open": _num(item.get("開盤價")), "high": _num(item.get("最高價")),
            "low": _num(item.get("最低價")), "close": _num(item.get("收盤價")),
            "volume": _num(item.get("成交股數"), 0),
            "trade_value": _num(item.get("成交金額"), 0),
            "change": change, "transactions": _num(item.get("成交筆數"), 0),
            "ticker": f"{code}.TW", "source_latest": "TWSE 指定日期收盤報表",
        })
    return pd.DataFrame(out) if len(out) >= 100 else pd.DataFrame()


def fetch_tpex_dated_snapshot(date: str) -> pd.DataFrame:
    """OpenAPI 尚未更新時，以櫃買中心指定日期的上櫃行情補位。"""
    date = valid_date(date)
    if date is None:
        return pd.DataFrame()
    roc_date = f"{int(date[:4])-1911}/{date[5:7]}/{date[8:10]}"
    payload = get_json(TPEX_DAILY_REPORT, params={
        "l": "zh-tw", "o": "json", "d": roc_date,
    }, timeout=12, attempts=2)
    if (not isinstance(payload, dict) or payload.get("stat") != "ok" or
            valid_date(payload.get("date")) != date):
        return pd.DataFrame()
    table = next((table for table in payload.get("tables", [])
                  if table.get("title") == "上櫃股票行情" and
                  {"代號", "名稱", "開盤", "最高", "最低", "收盤", "成交股數", "成交金額(元)"}.issubset(table.get("fields", []))), None)
    if not table:
        return pd.DataFrame()
    out = []
    for row in table.get("data", []):
        item = dict(zip(table["fields"], row))
        code = str(item.get("代號", "")).strip()
        if not re.fullmatch(r"\d{4}", code):
            continue
        out.append({
            "date": date, "market": "TPEx", "code": code,
            "name": str(item.get("名稱", "")).strip(),
            "open": _num(item.get("開盤")), "high": _num(item.get("最高")),
            "low": _num(item.get("最低")), "close": _num(item.get("收盤")),
            "volume": _num(item.get("成交股數"), 0),
            "trade_value": _num(item.get("成交金額(元)"), 0),
            "change": _num(item.get("漲跌")), "transactions": _num(item.get("成交筆數"), 0),
            "ticker": f"{code}.TWO", "source_latest": "TPEx 指定日期收盤報表",
        })
    return pd.DataFrame(out) if len(out) >= 100 else pd.DataFrame()


def _dated_candidates(latest_date: Optional[str]) -> List[str]:
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    last_possible = now.date() if now.hour >= 18 else now.date() - timedelta(days=1)
    start = last_possible - timedelta(days=7)
    if latest_date:
        start = max(start, datetime.strptime(latest_date, "%Y-%m-%d").date() + timedelta(days=1))
    if start > last_possible:
        return []
    return [day.date().isoformat() for day in pd.bdate_range(start, last_possible)][-5:][::-1]


def fetch_market_snapshot() -> Tuple[pd.DataFrame, List[str]]:
    frames, errors = {}, []
    for label, fn in [("TWSE", fetch_twse_snapshot), ("TPEx", fetch_tpex_snapshot)]:
        try:
            df = fn()
            if not df.empty:
                frames[label] = df
            else:
                errors.append(f"{label} 回傳空資料")
        except Exception as e:
            errors.append(f"{label} 最新行情抓取失敗：{e}")
    valid_dates = [date for df in frames.values()
                   if (date := valid_date(df["date"].iloc[0])) is not None]
    latest = max(valid_dates, default=None)
    if latest:
        # 某一市場的 OpenAPI 較舊時，先嘗試補齊另一市場已有的交易日。
        for label, fetcher in [("TWSE", fetch_twse_dated_snapshot), ("TPEx", fetch_tpex_dated_snapshot)]:
            current = frames.get(label)
            if current is not None and valid_date(current["date"].iloc[0]) == latest:
                continue
            try:
                replacement = fetcher(latest)
                if not replacement.empty:
                    frames[label] = replacement
                    errors = [error for error in errors if not error.startswith(f"{label} ")]
            except requests.RequestException:
                pass
    # 兩個最新介面都晚於實際盤後資料時，以指定日期報表找較新且雙市場齊全的交易日。
    for candidate in _dated_candidates(latest):
        try:
            twse = fetch_twse_dated_snapshot(candidate)
            tpex = fetch_tpex_dated_snapshot(candidate)
        except requests.RequestException:
            continue
        if not twse.empty and not tpex.empty:
            frames = {"TWSE": twse, "TPEx": tpex}
            errors = []
            break
    if not frames:
        return pd.DataFrame(), errors
    return pd.concat(frames.values(), ignore_index=True), errors


def fetch_twse_institutional(date_yyyymmdd: str) -> pd.DataFrame:
    try:
        data = get_json(TWSE_T86, params={"date": date_yyyymmdd, "selectType": "ALL", "response": "json"})
        source_date = valid_date(data.get("date", ""))
        if source_date != valid_date(date_yyyymmdd):
            return pd.DataFrame()
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
        if not all([fnet, inet, dnet]):
            return pd.DataFrame()
        out = pd.DataFrame({"code": df[code_col].astype(str).str.strip()})
        out["foreign_net"] = df[fnet].map(_num)
        out["trust_net"] = df[inet].map(_num)
        out["dealer_net"] = df[dnet].map(_num)
        out = out.dropna(subset=["foreign_net", "trust_net", "dealer_net"])
        out["inst_source"] = "TWSE T86"
        out["inst_date"] = source_date
        return out
    except Exception:
        return pd.DataFrame()


def fetch_tpex_institutional() -> pd.DataFrame:
    try:
        rows = get_json(TPEX_INST)
        if not isinstance(rows, list) or not rows:
            return pd.DataFrame()
        def pick(d, aliases, default=None):
            for a in aliases:
                if a in d:
                    return d[a]
            return default
        def net(d, aliases, marker):
            value = pick(d, aliases)
            if value is None:
                matches = [v for k, v in d.items() if marker(k) and ("Difference" in k or "NetBuySell" in k)]
                value = matches[0] if len(matches) == 1 else None
            return _num(value)
        out = []
        for r in rows:
            code = str(pick(r, ["SecuritiesCompanyCode", "Code", "SecuritiesCode"], "")).strip()
            if not re.fullmatch(r"\d{4}", code):
                continue
            foreign = net(r, ["ForeignInvestorsDifference", "ForeignInvestorsNetBuySell", "ForeignNet"], lambda k: "Foreign" in k and "Dealer" not in k)
            trust = net(r, ["InvestmentTrustDifference", "InvestmentTrustNetBuySell", "InvestmentTrustNet"], lambda k: "Trust" in k)
            dealer = net(r, ["DealerDifference", "DealerNetBuySell", "DealerNet"], lambda k: "Dealer" in k and "Foreign" not in k)
            if any(pd.isna(v) for v in [foreign, trust, dealer]):
                continue
            out.append({
                "code": code,
                "inst_date": valid_date(pick(r, ["Date", "date", "TradingDate"], "")),
                "foreign_net": foreign,
                "trust_net": trust,
                "dealer_net": dealer,
                "inst_source": "TPEx OpenAPI",
            })
        return pd.DataFrame(out)
    except Exception:
        return pd.DataFrame()


def enrich_institutional(snapshot: pd.DataFrame) -> pd.DataFrame:
    if snapshot.empty:
        return snapshot
    latest_date = valid_date(snapshot["date"].iloc[0])
    date_str = latest_date.replace("-", "") if latest_date else ""
    tw = fetch_twse_institutional(date_str) if date_str else pd.DataFrame()
    tp = fetch_tpex_institutional()
    if not tp.empty:
        tp = tp[tp["inst_date"] == latest_date].copy()
    inst = pd.concat([x for x in [tw, tp] if not x.empty], ignore_index=True) if (not tw.empty or not tp.empty) else pd.DataFrame()
    out = snapshot.copy()
    if inst.empty:
        out["foreign_net"] = 0.0
        out["trust_net"] = 0.0
        out["dealer_net"] = 0.0
        out["inst_source"] = "Unavailable"
        out["inst_date"] = None
        return out
    out = out.merge(inst, on="code", how="left")
    for c in ["foreign_net", "trust_net", "dealer_net"]:
        out[c] = out[c].fillna(0)
    out["inst_source"] = out["inst_source"].fillna("Unavailable")
    out["inst_date"] = out["inst_date"].where(out["inst_source"] != "Unavailable", None)
    return out


def download_history(tickers: List[str], period="9mo") -> Dict[str, pd.DataFrame]:
    if not tickers:
        return {}
    result = {}
    chunk = 40
    for i in range(0, len(tickers), chunk):
        part = tickers[i:i+chunk]
        remaining = part
        for attempt in range(2):
            if attempt:
                time.sleep(1)
            try:
                # yfinance 的平行下載會共用快取資料庫；在排程環境曾發生 database is locked。
                raw = yf.download(remaining, period=period, interval="1d", auto_adjust=False, group_by="ticker", threads=False, progress=False, timeout=30)
            except Exception:
                continue
            if len(remaining) == 1:
                t = remaining[0]
                df = raw.copy()
                if not df.empty:
                    normalized = _normalize_hist(df)
                    if not normalized.empty:
                        result[t] = normalized
            else:
                for t in remaining:
                    try:
                        df = raw[t].copy()
                    except Exception:
                        continue
                    if not df.empty:
                        normalized = _normalize_hist(df)
                        if not normalized.empty:
                            result[t] = normalized
            remaining = [t for t in part if t not in result]
            if not remaining:
                break
        time.sleep(0.25)
    return result


def _normalize_hist(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    if isinstance(d.columns, pd.MultiIndex):
        level = next((i for i in range(d.columns.nlevels)
                      if "Close" in set(d.columns.get_level_values(i))), None)
        if level is None:
            return pd.DataFrame()
        d.columns = d.columns.get_level_values(level)
    d.columns = [str(c).title() for c in d.columns]
    if "Close" not in d.columns:
        return pd.DataFrame()
    keep = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in d.columns]
    d = d[keep].dropna(subset=["Close"])
    d.index = pd.to_datetime(d.index).tz_localize(None)
    return d


def _valid_ohlcv(row: pd.Series) -> bool:
    values = [_num(row.get(key)) for key in ("Open", "High", "Low", "Close", "Volume")]
    if any(pd.isna(value) for value in values):
        return False
    opening, high, low, close, volume = values
    return low > 0 and volume > 0 and low <= min(opening, close) <= max(opening, close) <= high


def fetch_finmind_history(ticker: str, start: str, end: str) -> pd.DataFrame:
    """僅供 Yahoo 缺漏時使用；與官方行情相同，採未還原的日價格。"""
    code = ticker.split(".")[0]
    if not re.fullmatch(r"\d{4}", code):
        return pd.DataFrame()
    payload = get_json(FINMIND_DATA, params={
        "dataset": "TaiwanStockPrice", "data_id": code,
        "start_date": start, "end_date": end,
    }, timeout=12, attempts=1)
    if not isinstance(payload, dict) or payload.get("status") != 200:
        return pd.DataFrame()
    rows = payload.get("data", [])
    required = {"date", "stock_id", "open", "max", "min", "close", "Trading_Volume"}
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    frame = frame[frame["stock_id"].astype(str) == code].copy()
    frame["date"] = frame["date"].map(valid_date)
    frame = frame[frame["date"].between(start, end)].copy()
    if frame.empty or frame["date"].duplicated().any():
        return pd.DataFrame()
    frame = frame.rename(columns={
        "open": "Open", "max": "High", "min": "Low",
        "close": "Close", "Trading_Volume": "Volume",
    }).set_index("date")
    for column in ("Open", "High", "Low", "Close", "Volume"):
        frame[column] = frame[column].map(_num)
    frame = frame[["Open", "High", "Low", "Close", "Volume"]]
    if not frame.apply(_valid_ohlcv, axis=1).all():
        return pd.DataFrame()
    frame.index = pd.to_datetime(frame.index)
    return frame.sort_index()


def complete_history(history: Optional[pd.DataFrame], quote: pd.Series) -> Tuple[pd.DataFrame, str]:
    """先用同日官方 OHLCV 補末筆；缺口較長才向 FinMind 補歷史。"""
    target = valid_date(quote.get("date"))
    if target is None:
        return pd.DataFrame(), "Unavailable"
    day = pd.Timestamp(target)
    existing = history.copy() if history is not None else pd.DataFrame()
    if not existing.empty:
        existing = existing.loc[existing.index <= day].sort_index()
    if len(existing) >= 65 and existing.index[-1] == day:
        return existing, "Yahoo Finance"

    official = pd.Series({
        "Open": quote.get("open"), "High": quote.get("high"),
        "Low": quote.get("low"), "Close": quote.get("close"),
        "Volume": quote.get("volume"),
    })
    if _valid_ohlcv(official) and len(existing) >= 64:
        previous_day = existing.index[-1]
        # 僅在缺少下一個平日的日線時補末筆；較長缺口交給歷史來源。
        if len(pd.bdate_range(previous_day, day)) == 2:
            change = _num(quote.get("change"))
            previous_close = _num(existing.iloc[-1].get("Close"))
            implied_previous = _num(quote.get("close")) - change
            # 除權息等價格口徑不一致時，不將兩個來源直接接合。
            if pd.isna(change) or (previous_close > 0 and implied_previous > 0 and
                                   abs(previous_close / implied_previous - 1) <= 0.02):
                appended = existing.copy()
                appended.loc[day, ["Open", "High", "Low", "Close", "Volume"]] = official
                return appended, "Yahoo Finance + 官方當日行情"

    start = (day - pd.DateOffset(months=9)).date().isoformat()
    try:
        replacement = fetch_finmind_history(str(quote.get("ticker")), start, target)
    except (requests.RequestException, ValueError):
        replacement = pd.DataFrame()
    if len(replacement) >= 65 and replacement.index[-1] == day:
        official_close = _num(quote.get("close"))
        if official_close > 0 and abs(replacement.iloc[-1]["Close"] / official_close - 1) <= 0.02:
            return replacement, "FinMind TaiwanStockPrice"
    return existing, "Yahoo Finance (日期未補齊)" if not existing.empty else "Unavailable"


def fetch_twse_index_history(as_of_date: str) -> pd.DataFrame:
    """證交所按月公布加權指數開高低收；不以來源缺漏的日期推定行情。"""
    end = pd.Timestamp(as_of_date)
    start = end - pd.DateOffset(months=9)
    months = pd.date_range(start.replace(day=1), end.replace(day=1), freq="MS")
    frames = []
    for month in months:
        try:
            payload = get_json(TWSE_INDEX_HISTORY, params={
                "date": month.strftime("%Y%m%d"), "response": "json",
            }, timeout=10, attempts=2)
        except requests.RequestException:
            continue
        if not isinstance(payload, dict) or payload.get("stat") != "OK":
            continue
        fields = payload.get("fields", [])
        rows = payload.get("data", [])
        required = ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"]
        if not all(field in fields for field in required):
            continue
        for row in rows:
            values = dict(zip(fields, row))
            date = valid_date(values.get("日期"))
            if not date or not start.date().isoformat() <= date <= as_of_date:
                continue
            item = {"date": date, "Open": _num(values["開盤指數"]),
                    "High": _num(values["最高指數"]), "Low": _num(values["最低指數"]),
                    "Close": _num(values["收盤指數"])}
            if all(pd.notna(item[key]) and item[key] > 0 for key in ("Open", "High", "Low", "Close")):
                frames.append(item)
    if not frames:
        return pd.DataFrame()
    frame = pd.DataFrame(frames).drop_duplicates("date").set_index("date").sort_index()
    frame["Volume"] = np.nan  # 大盤評分不使用成交量，避免杜撰數值。
    frame.index = pd.to_datetime(frame.index)
    return frame


def rsi(close: pd.Series, n=14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = -delta.clip(upper=0).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    result = 100 - (100 / (1 + rs))
    result = result.mask((loss == 0) & (gain > 0), 100)
    return result.mask((loss == 0) & (gain == 0), 50)


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
        "history_date": d.index[-1].date().isoformat(),
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


def market_regime(as_of_date: Optional[str] = None) -> Dict[str, object]:
    try:
        df = fetch_twse_index_history(as_of_date) if as_of_date else pd.DataFrame()
        source = "TWSE 加權指數歷史資料"
        if len(df) < 65 or (as_of_date and df.index[-1] != pd.Timestamp(as_of_date)):
            df = yf.download("^TWII", period="9mo", interval="1d", progress=False, auto_adjust=False, timeout=20)
            df = _normalize_hist(df)
            if as_of_date:
                df = df.loc[df.index <= pd.Timestamp(as_of_date)]
            source = "Yahoo Finance (^TWII)；TWSE 歷史資料未齊"
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
        return {"regime": regime, "market_score": int(points), **ind, "source_market": source}
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

    snapshot = snapshot.copy()
    snapshot["date"] = snapshot["date"].map(valid_date)
    snapshot = snapshot[snapshot["date"].notna()]
    if snapshot.empty:
        return snapshot, market_regime(), errors + ["官方行情缺少有效日期"]
    latest_date = snapshot["date"].max()
    stale_markets = sorted(set(snapshot.loc[snapshot["date"] != latest_date, "market"]))
    if stale_markets:
        errors.append(f"{'、'.join(stale_markets)} 行情日期較舊，未納入 {latest_date} 排名")
    snapshot = snapshot[snapshot["date"] == latest_date].copy()

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
    stale_history = 0
    for _, r in liquid.iterrows():
        history, history_source = complete_history(hist.get(r.ticker), r)
        ind = calc_indicators(history)
        if ind is None:
            continue
        if ind["history_date"] != r["date"]:
            stale_history += 1
            continue
        ind_rows.append({"ticker": r.ticker, "source_history": history_source, **ind})
    if stale_history:
        errors.append(f"{stale_history} 檔技術歷史日期與官方行情不一致，已排除")
    inds = pd.DataFrame(ind_rows)
    if inds.empty:
        errors.append("歷史行情下載不足，無法計算技術指標")
        return pd.DataFrame(), market_regime(), errors

    df = liquid.merge(inds, on="ticker", how="inner")
    # 價格口徑明顯不同時，不將官方收盤價與 Yahoo 指標混算。
    gap = (df["hist_close"] / df["close"] - 1).abs()
    mismatched = gap.gt(0.02) | df["close"].isna() | df["close"].le(0)
    if mismatched.any():
        errors.append(f"{int(mismatched.sum())} 檔官方與技術歷史收盤價差超過 2% 或價格缺漏，已排除")
        df = df[~mismatched].copy()
    df = df[df["ma20_bias"].notna()].copy()
    df["excluded_overheat"] = df["ma20_bias"] > config.max_ma20_bias

    market = market_regime(latest_date)
    if market.get("history_date") != latest_date:
        errors.append("大盤指標日期與官方行情不一致，市場模式暫不採用")
        market = {"regime": "Unknown", "market_score": 0, "source_market": market.get("source_market", "Unavailable"), "history_date": market.get("history_date")}
    missing_inst = int((df["inst_source"] == "Unavailable").sum())
    if missing_inst:
        errors.append(f"{missing_inst} 檔法人資料缺漏或日期未驗證，籌碼分數按 0 計")
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
