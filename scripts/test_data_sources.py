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

    def test_dated_market_report_rejects_wrong_date(self):
        twse = {"stat": "OK", "date": "20261006", "tables": []}
        tpex = {"stat": "ok", "date": "20261006", "tables": []}
        with patch.object(engine, "get_json", return_value=twse):
            self.assertTrue(engine.fetch_twse_dated_snapshot("2026-10-07").empty)
        with patch.object(engine, "get_json", return_value=tpex):
            self.assertTrue(engine.fetch_tpex_dated_snapshot("2026-10-07").empty)

    def test_dated_report_completes_stale_market_without_mixing_dates(self):
        twse = pd.DataFrame([{"date": "2026-10-07", "market": "TWSE"}])
        stale_tpex = pd.DataFrame([{"date": "2026-10-06", "market": "TPEx"}])
        dated_tpex = pd.DataFrame([{"date": "2026-10-07", "market": "TPEx"}])
        with patch.object(engine, "fetch_twse_snapshot", return_value=twse), \
             patch.object(engine, "fetch_tpex_snapshot", return_value=stale_tpex), \
             patch.object(engine, "fetch_tpex_dated_snapshot", return_value=dated_tpex), \
             patch.object(engine, "_dated_candidates", return_value=[]):
            frame, errors = engine.fetch_market_snapshot()
        self.assertEqual(set(frame["date"]), {"2026-10-07"})
        self.assertEqual(set(frame["market"]), {"TWSE", "TPEx"})
        self.assertEqual(errors, [])

    def test_newer_dated_reports_replace_both_older_openapi_markets(self):
        old_twse = pd.DataFrame([{"date": "2026-10-06", "market": "TWSE"}])
        old_tpex = pd.DataFrame([{"date": "2026-10-06", "market": "TPEx"}])
        new_twse = pd.DataFrame([{"date": "2026-10-07", "market": "TWSE"}])
        new_tpex = pd.DataFrame([{"date": "2026-10-07", "market": "TPEx"}])
        with patch.object(engine, "fetch_twse_snapshot", return_value=old_twse), \
             patch.object(engine, "fetch_tpex_snapshot", return_value=old_tpex), \
             patch.object(engine, "fetch_twse_dated_snapshot", return_value=new_twse), \
             patch.object(engine, "fetch_tpex_dated_snapshot", return_value=new_tpex), \
             patch.object(engine, "_dated_candidates", return_value=["2026-10-07"]):
            frame, errors = engine.fetch_market_snapshot()
        self.assertEqual(set(frame["date"]), {"2026-10-07"})
        self.assertEqual(set(frame["market"]), {"TWSE", "TPEx"})
        self.assertEqual(errors, [])

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
             patch.object(engine, "fetch_finmind_history", return_value=pd.DataFrame()), \
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

    def test_future_yahoo_row_is_excluded_from_official_day_scoring(self):
        dates = pd.bdate_range(end="2026-10-02", periods=130)
        closes = pd.Series([100 + i * 0.2 for i in range(130)], index=dates)
        history = pd.DataFrame({
            "Open": closes - 0.2, "High": closes + 0.5,
            "Low": closes - 0.5, "Close": closes, "Volume": 2_000_000,
        })
        history.loc[pd.Timestamp("2026-10-05")] = [200, 201, 199, 200, 2_000_000]
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

    def test_market_regime_uses_official_snapshot_date(self):
        dates = pd.bdate_range(end="2026-10-05", periods=130)
        closes = pd.Series([100 + i * 0.2 for i in range(130)], index=dates)
        history = pd.DataFrame({
            "Open": closes - 0.2, "High": closes + 0.5,
            "Low": closes - 0.5, "Close": closes, "Volume": 2_000_000,
        })
        with patch.object(engine, "fetch_twse_index_history", return_value=pd.DataFrame()), \
             patch.object(engine.yf, "download", return_value=history):
            result = engine.market_regime("2026-10-02")
        self.assertEqual(result["history_date"], "2026-10-02")
        self.assertNotEqual(result["regime"], "Unknown")

    def test_official_daily_bar_completes_one_day_yahoo_lag(self):
        dates = pd.bdate_range(end="2026-10-06", periods=130)
        history = pd.DataFrame({"Open": 99.0, "High": 102.0, "Low": 98.0,
                                "Close": 100.0, "Volume": 2000000}, index=dates)
        quote = pd.Series({"date": "2026-10-07", "ticker": "1234.TW",
                           "open": 101, "high": 103, "low": 100,
                           "close": 102, "volume": 3000000, "change": 2})
        with patch.object(engine, "fetch_finmind_history") as finmind:
            completed, source = engine.complete_history(history, quote)
        self.assertEqual(source, "Yahoo Finance + 官方當日行情")
        self.assertEqual(completed.index[-1], pd.Timestamp("2026-10-07"))
        self.assertEqual(completed.iloc[-1]["Close"], 102)
        finmind.assert_not_called()

    def test_long_gap_uses_validated_finmind_history(self):
        dates = pd.bdate_range(end="2026-10-02", periods=130)
        history = pd.DataFrame({"Open": 99.0, "High": 102.0, "Low": 98.0,
                                "Close": 100.0, "Volume": 2000000}, index=dates)
        backup = history.copy()
        backup.loc[pd.Timestamp("2026-10-05")] = [99, 102, 98, 100, 2000000]
        backup.loc[pd.Timestamp("2026-10-06")] = [99, 102, 98, 100, 2000000]
        backup.loc[pd.Timestamp("2026-10-07")] = [101, 103, 100, 102, 3000000]
        quote = pd.Series({"date": "2026-10-07", "ticker": "1234.TW",
                           "open": 101, "high": 103, "low": 100,
                           "close": 102, "volume": 3000000, "change": 2})
        with patch.object(engine, "fetch_finmind_history", return_value=backup):
            completed, source = engine.complete_history(history, quote)
        self.assertEqual(source, "FinMind TaiwanStockPrice")
        self.assertEqual(completed.index[-1], pd.Timestamp("2026-10-07"))

    def test_finmind_rejects_wrong_stock_and_invalid_bars(self):
        payload = {"status": 200, "data": [
            {"date": "2026-10-07", "stock_id": "5678", "open": 100,
             "max": 101, "min": 99, "close": 100, "Trading_Volume": 2000000},
        ]}
        with patch.object(engine, "get_json", return_value=payload):
            result = engine.fetch_finmind_history("1234.TW", "2026-10-01", "2026-10-07")
        self.assertTrue(result.empty)

    def test_official_index_monthly_rows_are_date_checked(self):
        payload = {"stat": "OK", "fields": ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"],
                   "data": [["115/10/07", "20,000", "20,100", "19,900", "20,050"],
                            ["115/10/08", "20,000", "20,100", "19,900", "20,050"]]}
        with patch.object(engine, "get_json", return_value=payload):
            result = engine.fetch_twse_index_history("2026-10-07")
        self.assertEqual(list(result.index), [pd.Timestamp("2026-10-07")])
        self.assertEqual(result.iloc[0]["Close"], 20050)

    def test_official_index_is_preferred_over_yahoo(self):
        dates = pd.bdate_range(end="2026-10-07", periods=130)
        history = pd.DataFrame({"Open": 100.0, "High": 102.0, "Low": 99.0,
                                "Close": 101.0, "Volume": float("nan")}, index=dates)
        with patch.object(engine, "fetch_twse_index_history", return_value=history), \
             patch.object(engine.yf, "download") as yahoo:
            result = engine.market_regime("2026-10-07")
        self.assertEqual(result["source_market"], "TWSE 加權指數歷史資料")
        yahoo.assert_not_called()

    def test_short_same_day_yahoo_history_uses_finmind(self):
        history = pd.DataFrame({"Open": [100], "High": [102], "Low": [99],
                                "Close": [101], "Volume": [2000000]},
                               index=pd.to_datetime(["2026-10-07"]))
        quote = pd.Series({"date": "2026-10-07", "ticker": "1234.TW", "close": 101})
        backup = pd.concat([history] * 65)
        backup.index = pd.bdate_range(end="2026-10-07", periods=65)
        with patch.object(engine, "fetch_finmind_history", return_value=backup):
            _, source = engine.complete_history(history, quote)
        self.assertEqual(source, "FinMind TaiwanStockPrice")

    def test_incomplete_latest_date_does_not_replace_snapshot(self):
        rows = []
        for index in range(10):
            row = {field: None for field in build_snapshot.FIELDS}
            row.update(date="2026-10-02", code=str(1000 + index), market="TWSE")
            rows.append(row)
        older = {field: None for field in build_snapshot.FIELDS}
        older.update(date="2026-10-01", code="1234", market="TPEx")
        rows.append(older)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as temp_dir:
            output = Path(temp_dir) / "selection.json"
            previous = {"status": "partial", "coverage": ["TWSE", "TPEx"], "trading_date": "2026-10-01"}
            output.write_text(json.dumps(previous), encoding="utf-8")
            with patch.object(build_snapshot, "OUTPUT", output), \
                 patch.object(build_snapshot, "build_screen", return_value=(pd.DataFrame(rows), {}, [])):
                with self.assertRaisesRegex(RuntimeError, "上市或上櫃資料缺漏"):
                    build_snapshot.main()
            result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result, previous)

    def test_history_download_retries_without_parallel_workers(self):
        dates = pd.to_datetime(["2026-10-01", "2026-10-02"])
        history = pd.DataFrame({"Close": [100.0, 101.0]}, index=dates)
        with patch.object(engine.yf, "download", side_effect=[RuntimeError("database is locked"), history]) as download, \
             patch.object(engine.time, "sleep") as sleep:
            result = engine.download_history(["1234.TW"])
        self.assertEqual(download.call_count, 2)
        self.assertTrue(all(call.kwargs["threads"] is False for call in download.call_args_list))
        self.assertEqual(result["1234.TW"]["Close"].iloc[-1], 101.0)
        sleep.assert_any_call(1)

    def test_history_download_retries_tickers_omitted_without_error(self):
        dates = pd.to_datetime(["2026-10-01", "2026-10-02"])
        first = pd.DataFrame(
            [[100.0], [101.0]], index=dates,
            columns=pd.MultiIndex.from_tuples([("1234.TW", "Close")]),
        )
        second = pd.DataFrame({"Close": [50.0, 51.0]}, index=dates)
        with patch.object(engine.yf, "download", side_effect=[first, second]) as download, \
             patch.object(engine.time, "sleep"):
            result = engine.download_history(["1234.TW", "5678.TWO"])
        self.assertEqual(download.call_count, 2)
        self.assertEqual(download.call_args_list[1].args[0], ["5678.TWO"])
        self.assertEqual(set(result), {"1234.TW", "5678.TWO"})


if __name__ == "__main__":
    unittest.main()
