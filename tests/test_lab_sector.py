"""lab/sector.py (Phase G) and the optional alert.py 'sector strong' hook. Offline."""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from _load import ROOT

sys.path.insert(0, os.path.join(ROOT, "lab"))
import alert  # noqa: E402
import sector  # noqa: E402


def series(closes):
    d0 = dt.date(2026, 6, 1)
    return [dict(day=(d0 + dt.timedelta(days=k)).isoformat(), m=555, o=c, h=c, l=c, c=c, v=1)
            for k, c in enumerate(closes)]


IDX = series([100.0] * 40 + [110.0])            # index +10% on the last day


class TestSector(unittest.TestCase):
    def test_sector_csv_covers_nifty100(self):
        import lab
        sec = sector.load_sectors()
        self.assertEqual(set(lab.nifty100()) - set(sec), set())
        self.assertEqual(sec["TCS"], "Information Technology")

    def test_relative_strength(self):
        daily = {"UP": series([50.0] * 40 + [60.0]), "FLAT": series([50.0] * 41)}
        rows, n = sector.rs_rows(daily, IDX, {"UP": "A", "FLAT": "B"})
        r = dict((x["symbol"], x) for x in rows)
        self.assertEqual(n["r1w"], 10.0)
        self.assertEqual(r["UP"]["rs1w"], 10.0)                 # +20% vs +10%
        self.assertEqual(r["FLAT"]["rs1m"], -10.0)
        self.assertEqual(r["UP"]["sector"], "A")

    def test_missing_day_uses_last_close(self):
        D = [b for b in series([50.0] * 40 + [55.0]) if b["day"] != IDX[-6]["day"]]
        rows, _ = sector.rs_rows({"X": D}, IDX, {})
        self.assertEqual(rows[0]["r1w"], 10.0)
        self.assertEqual(rows[0]["sector"], "Other")

    def test_rank_and_hook(self):
        rows = [dict(symbol="A1", sector="IT", rs1m=5, rs1w=1), dict(symbol="A2", sector="IT", rs1m=3, rs1w=1),
                dict(symbol="B1", sector="Bank", rs1m=-2, rs1w=4), dict(symbol="C1", sector="Metal", rs1m=1, rs1w=0)]
        rank = sector.sector_rank(rows)
        self.assertEqual([x["sector"] for x in rank], ["IT", "Metal", "Bank"])
        self.assertEqual((rank[0]["rs1m"], rank[0]["n"], rank[0]["rank"]), (4.0, 2, 1))
        sec = {"A1": "IT", "B1": "Bank", "C1": "Metal"}
        self.assertTrue(sector.is_sector_strong("a1", rank, sec, top=1))
        self.assertFalse(sector.is_sector_strong("C1", rank, sec, top=1))
        hits = [dict(symbol="A1"), dict(symbol="B1"), dict(symbol="C1")]
        self.assertEqual([h["symbol"] for h in sector.filter_picks(hits, rank, sec, top=2)], ["A1", "C1"])

    def test_breadth(self):
        up = series([float(k) for k in range(1, 61)])
        down = series([float(k) for k in range(60, 0, -1)])
        b = sector.breadth({"U": up, "D": down, "short": series([1.0] * 10)})
        self.assertEqual((b["stocks"], b["above_ema20"], b["above_ema50"]), (2, 50.0, 50.0))
        self.assertEqual((b["advances"], b["declines"], b["ad_ratio"]), (1, 1, 1.0))

    def test_today_rank_cached_once_a_day(self):
        calls = []

        def builder():
            calls.append(1)
            return dict(rank=[dict(sector="IT")])
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "s.json")
            self.assertEqual(sector.today_rank(f, "2026-11-05", builder), [dict(sector="IT")])
            sector.today_rank(f, "2026-11-05", builder)
            self.assertEqual(len(calls), 1)
            sector.today_rank(f, "2026-11-06", builder)
            self.assertEqual(len(calls), 2)
            self.assertEqual(json.load(open(f))["built"], "2026-11-06")

    def test_text_has_disclaimer(self):
        doc = dict(day="d", nifty=dict(r1w=1.0, r1m=2.0), rank=[], rows=[],
                   breadth=dict(stocks=0, above_ema20=0, above_ema50=0, advances=0, declines=0, unchanged=0))
        self.assertIn("not investment advice", sector.text(doc))


class TestAlertHook(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(alert.SECTOR_STRONG)
        self.assertEqual(alert.MAX_PER_DAY, int(os.environ.get("MAX_PER_DAY", "2")))

    def test_hook_filters_and_steps_aside_on_error(self):
        rank = [dict(sector="Information Technology")]
        hits = [dict(symbol="TCS"), dict(symbol="SBIN")]
        self.assertEqual(alert.sector_filter(hits, rank), [dict(symbol="TCS")])
        with mock.patch.object(sector, "today_rank", side_effect=OSError("offline")):
            self.assertEqual(alert.sector_filter(hits), hits)


if __name__ == "__main__":
    unittest.main()
