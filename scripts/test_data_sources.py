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

    def test_yahoo_price_first_multiindex(self):
        columns = pd.MultiIndex.from_tuples([("Close", "^TWII"), ("Volume", "^TWII")])
        frame = pd.DataFrame([[100.0, 2000]], columns=columns, index=pd.to_datetime(["2026-10-02"]))
        normalized = engine._normalize_hist(frame)
        self.assertEqual(normalized["Close"].iloc[0], 100.0)

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
