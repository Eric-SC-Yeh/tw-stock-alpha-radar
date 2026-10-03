"""以原始選股引擎建立日期可追溯的 V2.3 盤後快照。"""

from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import Config, build_screen  # noqa: E402

OUTPUT = ROOT / "data" / "latest-selection.json"
FIELDS = [
    "date", "code", "name", "market", "close", "trade_value", "total_score",
    "grade", "breakout_score", "trend_score", "momentum_score", "volume_score",
    "institutional_score", "breakout_score_component", "market_score_component",
    "risk_score", "risk_reasons", "ma20_bias", "rsi14", "vol_ratio", "atr14",
    "atr_pct", "ma20", "stop_loss", "trail_trigger", "trade_type", "break20",
    "break60", "foreign_net", "trust_net", "dealer_net", "source_latest",
    "inst_source", "inst_date", "history_date",
]


def clean(value):
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if math.isfinite(value) else None
    if pd.isna(value):
        return None
    return value


def main() -> int:
    config = Config(top_liquid_per_market=100)
    frame, market, errors = build_screen(config)
    if frame.empty or len(frame) < 10:
        raise RuntimeError(f"選股結果不足，保留舊快照。資料來源訊息：{errors}")
    previous = json.loads(OUTPUT.read_text(encoding="utf-8")) if OUTPUT.exists() else {}
    dates = pd.to_datetime(frame["date"], errors="coerce").dropna()
    if dates.empty:
        raise RuntimeError("找不到有效交易日期，保留舊快照。")
    latest_date = dates.max().strftime("%Y-%m-%d")
    frame = frame[frame["date"] == latest_date].copy()
    if len(frame) < 10:
        raise RuntimeError("最新交易日的股票不足 10 檔，保留舊快照。")
    coverage = sorted(set(frame["market"]))
    full_coverage = {"TWSE", "TPEx"}.issubset(coverage)
    if not full_coverage and previous.get("status") == "ready":
        raise RuntimeError(f"最新交易日上市或上櫃資料缺漏，保留既有完整快照。資料來源訊息：{errors}")

    missing = sorted(set(FIELDS) - set(frame.columns))
    if missing:
        raise RuntimeError(f"選股引擎缺少欄位：{', '.join(missing)}")
    stocks = [{field: clean(row[field]) for field in FIELDS} for row in frame.to_dict("records")]
    content = {
        "schema_version": 2,
        "status": "ready" if full_coverage and not errors else "partial",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "trading_date": latest_date,
        "coverage": coverage,
        "config": {
            "min_trade_value": config.min_trade_value,
            "max_ma20_bias": config.max_ma20_bias,
            "warn_ma20_bias": config.warn_ma20_bias,
            "top_liquid_per_market": config.top_liquid_per_market,
        },
        "market": {
            "regime": market.get("regime", "Unknown"),
            "market_score": market.get("market_score", 0),
            "source_market": market.get("source_market", "Unknown"),
            "history_date": market.get("history_date"),
        },
        "errors": errors,
        "stocks": stocks,
    }
    if previous:
        prior_date = previous.get("trading_date")
        if prior_date and prior_date > latest_date:
            raise RuntimeError("來源日期早於現有快照，保留舊快照。")
        comparable_old = {k: v for k, v in previous.items() if k != "generated_at"}
        comparable_new = {k: v for k, v in content.items() if k != "generated_at"}
        if comparable_old == comparable_new:
            print(f"{latest_date} 快照未變更。")
            return 0

    payload = json.dumps(content, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    print(f"已建立 {latest_date} 快照：{len(stocks)} 檔，來源訊息 {len(errors)} 則。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
