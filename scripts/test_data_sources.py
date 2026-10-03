"""Regression checks for official market snapshots and Yahoo column shapes."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
import requests

import build_snapshot
import engine


class DataSourceTests(unittest.TestCase):
    def test_retries_transient_502(self):
        failed = Mock(status_code=502)
        failed.raise_for_status.side_effect = requests.HTTPError(response=failed)
        succeeded = Mock()
        succeeded.json.return_value = [{"Date": "1151002"}]
        with patch.object(engine.requests, "get", side_effect=[failed, succeeded]) as get, \
             patch.object(engine.time, "sleep") as sleep:
            self.assertEqual(engine.get_json("https://example.test/quotes"), [{"Date": "1151002"}])
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_does_not_retry_client_error(self):
        failed = Mock(status_code=404)
        failed.raise_for_status.side_effect = requests.HTTPError(response=failed)
        with patch.object(engine.requests, "get", return_value=failed) as get, \
             patch.object(engine.time, "sleep") as sleep:
            with self.assertRaises(requests.HTTPError):
                engine.get_json("https://example.test/missing")
        get.assert_called_once()
        sleep.assert_not_called()

    def test_retries_truncated_response(self):
        succeeded = Mock()
        succeeded.json.return_value = []
        with patch.object(engine.requests, "get", side_effect=[requests.exceptions.ChunkedEncodingError(), succeeded]) as get, \
             patch.object(engine.time, "sleep") as sleep:
            self.assertEqual(engine.get_json("https://example.test/quotes"), [])
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_yahoo_price_first_multiindex(self):
        columns = pd.MultiIndex.from_tuples([("Close", "^TWII"), ("Volume", "^TWII")])
        frame = pd.DataFrame([[100.0, 2000]], columns=columns, index=pd.to_datetime(["2026-10-02"]))
        normalized = engine._normalize_hist(frame)
        self.assertEqual(normalized["Close"].iloc[0], 100.0)

    def test_date_parser_accepts_roc_and_rejects_unknown(self):
        self.assertEqual(engine.valid_date("115年10月02日"), "2026-10-02")
        self.assertEqual(engine.valid_date("20261002"), "2026-10-02")
        self.assertIsNone(engine.valid_date(""))

    def test_tpex_institutional_date_is_not_inferred(self):
        rows = [{"SecuritiesCompanyCode": "1234", "ForeignNet": "100", "InvestmentTrustNet": "0", "DealerNet": "-50"}]
        with patch.object(engine, "get_json", return_value=rows):
            result = engine.fetch_tpex_institutional()
        self.assertIsNone(result.iloc[0]["inst_date"])

    def test_tpex_institutional_does_not_fabricate_missing_components(self):
        rows = [{"SecuritiesCompanyCode": "1234", "Date": "1151002", "ForeignNet": "100"}]
        with patch.object(engine, "get_json", return_value=rows):
            self.assertTrue(engine.fetch_tpex_institutional().empty)

    def test_twse_institutional_rejects_wrong_response_date(self):
        rows = {"date": "20261001", "fields": ["證券代號"], "data": [["1234"]]}
        with patch.object(engine, "get_json", return_value=rows):
            self.assertTrue(engine.fetch_twse_institutional("20261002").empty)

    def test_stale_history_is_excluded_before_scoring(self):
        quotes = pd.DataFrame([
            {"date": "2026-10-02", "market": "TWSE", "ticker": "1234.TW", "trade_value": 2_000_000_000},
            {"date": "2026-10-01", "market": "TPEx", "ticker": "5678.TWO", "trade_value": 2_000_000_000},
        ])
        with patch.object(engine, "fetch_market_snapshot", return_value=(quotes, [])), \
             patch.object(engine, "enrich_institutional", side_effect=lambda value: value), \
             patch.object(engine, "download_history", return_value={"1234.TW": pd.DataFrame()}), \
             patch.object(engine, "calc_indicators", return_value={"history_date": "2026-10-01"}), \
             patch.object(engine, "market_regime", return_value={}):
            frame, _, errors = engine.build_screen(engine.Config())
        self.assertTrue(frame.empty)
        self.assertTrue(any("TPEx 行情日期較舊" in error for error in errors))
        self.assertTrue(any("技術歷史日期" in error for error in errors))

    def test_rsi_handles_gain_only_and_flat_prices(self):
        up = engine.rsi(pd.Series(range(20))).iloc[-1]
        flat = engine.rsi(pd.Series([100] * 20)).iloc[-1]
        self.assertEqual(up, 100)
        self.assertEqual(flat, 50)

    def test_same_day_history_produces_a_ranked_stock(self):
        dates = pd.bdate_range(end="2026-10-02", periods=130)
        closes = pd.Series([100 + i * 0.2 for i in range(130)], index=dates)
        history = pd.DataFrame({
            "Open": closes - 0.2, "High": closes + 0.5,
            "Low": closes - 0.5, "Close": closes, "Volume": 2_000_000,
        })
        quotes = pd.DataFrame([{
            "date": "2026-10-02", "market": "TWSE", "ticker": "1234.TW",
            "code": "1234", "name": "測試", "close": closes.iloc[-1],
            "trade_value": 2_000_000_000, "source_latest": "TWSE OpenAPI",
        }])
        def with_institutional(value):
            return value.assign(foreign_net=0, trust_net=0, dealer_net=0,
                                inst_source="TWSE T86", inst_date="2026-10-02")
        with patch.object(engine, "fetch_market_snapshot", return_value=(quotes, [])), \
             patch.object(engine, "enrich_institutional", side_effect=with_institutional), \
             patch.object(engine, "download_history", return_value={"1234.TW": history}), \
             patch.object(engine, "market_regime", return_value={"regime": "Bull", "market_score": 80, "history_date": "2026-10-02"}):
            frame, _, errors = engine.build_screen(engine.Config())
        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["history_date"], "2026-10-02")
        self.assertEqual(errors, [])

    def test_coverage_is_checked_after_latest_date_filter(self):
        rows = []
        for index in range(10):
            row = {field: None for field in build_snapshot.FIELDS}
            row.update(date="2026-10-02", code=str(1000 + index), market="TWSE")
            rows.append(row)
        older = {field: None for field in build_snapshot.FIELDS}
        older.update(date="2026-10-01", code="1234", market="TPEx")
        rows.append(older)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "selection.json"
            with patch.object(build_snapshot, "OUTPUT", output), \
                 patch.object(build_snapshot, "build_screen", return_value=(pd.DataFrame(rows), {}, [])):
                self.assertEqual(build_snapshot.main(), 0)
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["coverage"], ["TWSE"])
        self.assertEqual(len(result["stocks"]), 10)


if __name__ == "__main__":
    unittest.main()
