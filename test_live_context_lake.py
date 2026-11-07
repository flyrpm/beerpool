"""Tests for the live-only layer (live.py), context flags (context.py) and the data lake (lake.py).
None of these touch the files pinned by the ronnie-v1 baseline."""
import gzip
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import beerpool as bp
import context
import lake
import live

BOARD = json.loads((Path(__file__).parent / "board.example.json").read_text())
NOW = datetime.fromisoformat(BOARD["now"])
CFG = bp.Config.legacy()


class LiveGuard(unittest.TestCase):
    def test_no_fallback_when_engine_has_a_card(self):
        fb, notes = live.guard(BOARD, NOW, CFG)
        self.assertEqual(fb, [])
        self.assertEqual(notes, [])

    def test_fallback_when_everything_is_flagged(self):
        b = json.loads(json.dumps(BOARD))
        for g in b["games"]:
            notes = g.setdefault("notes", {})
            for side in (g["home"], g["away"], "OVER", "UNDER"):
                notes.setdefault(side, {}).setdefault("tags", []).append("qb_uncertain")
        cands, _ = bp.build_candidates(b, NOW, [], CFG)
        self.assertEqual(bp.build_card(cands, cfg=CFG)[0], [])     # frozen engine: empty
        fb, notes = live.guard(b, NOW, CFG)
        self.assertEqual(len({c.game for c in fb}), len(fb))        # distinct games
        self.assertGreaterEqual(len(fb), 2)
        self.assertIn("THIN", notes[0])
        self.assertNotIn("DAL", {c.side for c in fb})               # Dallas rule still holds

    def test_fallback_card_orders_by_probability(self):
        cands, _ = bp.build_candidates(BOARD, NOW, [], CFG)
        fb = live.fallback_card(cands)
        ps = [c.p for c in fb]
        self.assertEqual(fb[0].p, max(c.p for c in cands))
        self.assertTrue(all(ps[i] >= ps[i + 1] for i in range(len(ps) - 1)))


class ContextFlags(unittest.TestCase):
    SUMMARY = {
        "predictor": {"homeTeam": {"gameProjection": "82.2"}},
        "gameInfo": {"venue": {"indoor": False},
                     "weather": {"temperature": 41, "gust": 22, "precipitation": 10}},
        "injuries": [{"team": {"abbreviation": "MIN"},
                      "injuries": [{"athlete": {"displayName": "Starter QB", "position": {"abbreviation": "QB"}},
                                    "status": "Out"},
                                   {"athlete": {"displayName": "Some WR", "position": {"abbreviation": "WR"}},
                                    "status": "Out"}]}],
        "header": {"competitions": [{"competitors": [
            {"team": {"location": "Minnesota", "name": "Vikings", "abbreviation": "MIN"}},
            {"team": {"location": "Buffalo", "name": "Bills", "abbreviation": "BUF"}}]}]},
        "news": {"articles": [{"headline": "Vikings QB ruled out for Monday", "description": ""},
                              {"headline": "Browns QB out of concussion protocol", "description": ""},
                              {"headline": "Bills win streak continues", "description": ""}]},
    }

    def test_fpi_margin_is_symmetric_and_monotone(self):
        self.assertAlmostEqual(context.fpi_margin(50, "NFL"), 0.0, places=6)
        self.assertAlmostEqual(context.fpi_margin(70, "CFB"), -context.fpi_margin(30, "CFB"), places=6)
        self.assertGreater(context.fpi_margin(80, "CFB"), context.fpi_margin(60, "CFB"))

    def test_fpi_flag_marks_big_disagreement(self):
        # Away dog getting +7.5; FPI makes home ~15 pt favourite -> dislikes our side.
        f = context.fpi_flag(self.SUMMARY, "CFB", side_is_home=False, side_market_line=7.5)
        self.assertIn("dislikes our side", f)
        g = context.fpi_flag(self.SUMMARY, "CFB", side_is_home=True, side_market_line=-15.0)
        self.assertNotIn("**", g)

    def test_weather_and_qb_flags(self):
        self.assertIn("weather can matter", context.weather_flag(self.SUMMARY))
        indoor = dict(self.SUMMARY, gameInfo={"venue": {"indoor": True}})
        self.assertEqual(context.weather_flag(indoor), "indoor")
        qb = context.qb_flags(self.SUMMARY)
        self.assertEqual(len(qb), 1)
        self.assertIn("MIN QB Starter QB: Out", qb[0])

    def test_news_only_for_this_games_teams(self):
        news = context.news_flags(self.SUMMARY)
        self.assertEqual(news, ["news: Vikings QB ruled out for Monday"])


class Lake(unittest.TestCase):
    def test_build_query_layer_from_raw_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "models").mkdir()
            (root / "models" / "teams.json").write_text(json.dumps(
                {"NFL": {"1": {"abbreviation": "BUF", "location": "Buffalo", "name": "Bills",
                               "displayName": "Buffalo Bills"}}}))
            snaps = root / "data" / "snapshots" / "2026-11-07"
            snaps.mkdir(parents=True)
            with gzip.open(snaps / "1415_NFL_x.json.gz", "wt") as f:
                json.dump({"taken_utc": "2026-11-07T14:15:00+00:00",
                           "received_utc": "2026-11-07T14:15:02+00:00", "league": "NFL",
                           "books": ["Open", "bet365"],
                           "rows": [{"market": "spread", "rot": 101, "team": "Bills",
                                     "cells": [{"line": -3.0, "price": -110},
                                               {"line": -2.5, "price": -115}]}]}, f)
            run = root / "runs" / "2026-11-07_0948"
            run.mkdir(parents=True)
            (run / "card.txt").write_text("== CARD ==\n  Pick 1 (5) 37 MRSH +10.5      p=0.600  [note]\n"
                                          "  Pick 2 (5) 55 MICH -12.5      p=0.595\n== SUBMISSION ==\n")
            lk = root / "data" / "lake"
            ctx = lk / "raw" / "context" / "2026-11-07"
            ctx.mkdir(parents=True)
            (ctx / "CFB_401.json").write_text(json.dumps(
                {"fetched_utc": "2026-11-07T15:00:00+00:00",
                 "data": {"predictor": {"homeTeam": {"gameProjection": "82.2"}},
                          "gameInfo": {"weather": {"gust": 5}}}}))
            counts = lake.build(db=str(root / "lake.db"), lake=str(lk), snaps=str(root / "data" / "snapshots"),
                                root=str(root))
            self.assertEqual(counts["teams"], 1)
            self.assertEqual(counts["odds"], 2)
            self.assertEqual(counts["picks"], 2)
            self.assertEqual(counts["context"], 1)
            rows = lake.sql("select game, label, p from picks order by slot", db=str(root / "lake.db"))
            self.assertEqual(rows[1], (37, "MRSH +10.5", 0.6))
            rows = lake.sql("select received_utc from odds limit 1", db=str(root / "lake.db"))
            self.assertEqual(rows[1][0], "2026-11-07T14:15:02+00:00")

    def test_add_refuses_overwrite_and_dedupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = lake.LAKE
            try:
                lake.LAKE = tmp
                src = Path(tmp) / "x.pdf"
                src.write_bytes(b"%PDF-1.4 test")
                first = lake.add_sheet(str(src), 2026, 10)
                self.assertTrue(first.startswith("stored"))
                self.assertTrue(lake.add_sheet(str(src), 2026, 10).startswith("already stored"))
                meta = lake.load_json(next(Path(tmp).rglob("*.meta.json")))
                self.assertEqual(meta["season"], 2026)
                self.assertEqual(len(meta["sha256"]), 64)
            finally:
                lake.LAKE = old


if __name__ == "__main__":
    unittest.main()
