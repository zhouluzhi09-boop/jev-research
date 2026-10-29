# -*- coding: utf-8 -*-
import copy
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from select_topics import filter_rank, gate_require, score_dims  # noqa: E402

GATE_DIMS = ("information_density", "copyability", "structure_clarity", "differentiation")


def load():
    with open(os.path.join(ROOT, "profiles", "public-xhs.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    with open(os.path.join(HERE, "fixtures", "sample.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(l) for l in f if l.strip()]
    return cfg, rows


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.cfg, self.rows = load()
        self.shortlist, self.rejected, self.pending, self.fallback = filter_rank(self.rows, self.cfg)

    def test_counts(self):
        self.assertEqual(len(self.shortlist), 2)
        self.assertEqual(len(self.pending), 1)
        self.assertEqual(len(self.rejected), 7)
        self.assertEqual(len(self.fallback), 0)

    def test_resonance_is_scored_but_not_gated(self):
        self.assertIn("emotional_resonance", score_dims(self.cfg))
        self.assertNotIn("emotional_resonance", gate_require(self.cfg))

    def test_low_resonance_still_passes_if_other_dims_ok(self):
        ids = [x["id"] for x in self.shortlist]
        self.assertIn("n10", ids)
        n10 = [x for x in self.shortlist if x["id"] == "n10"][0]
        self.assertEqual(n10["scores"]["emotional_resonance"], 4)
        for d in GATE_DIMS:
            self.assertGreaterEqual(n10["scores"][d], 7)

    def test_gate_requires_every_dim(self):
        ids = {r["id"]: r for r in self.rejected}
        for rid, dim in (("n2", "information_density"), ("n6", "structure_clarity"),
                         ("n7", "copyability"), ("n8", "differentiation"),
                         ("n9", "structure_clarity")):
            self.assertEqual(ids[rid]["reason"], "gate_require")
            self.assertIn(dim, ids[rid]["failed"])

    def test_missing_collects_goes_pending_not_dropped(self):
        self.assertEqual(self.pending[0]["id"], "n3")
        self.assertEqual(self.pending[0]["reason"], "unverifiable")

    def test_metric_gate(self):
        ids = {r["id"]: r for r in self.rejected}
        self.assertEqual(ids["n4"]["reason"], "gate_metric")
        self.assertEqual(ids["n5"]["reason"], "gate_metric")

    def test_average_score_cannot_replace_threshold(self):
        avg = sum(v["score"] for v in self.rows[1]["jev"].values()) / 5
        self.assertGreaterEqual(avg, 7)
        self.assertEqual(
            self.rejected[[r["id"] for r in self.rejected].index("n2")]["reason"],
            "gate_require",
        )

    def test_resonance_affects_ranking(self):
        ranking = [x["id"] for x in self.shortlist]
        self.assertEqual(ranking[0], "n1")
        self.assertEqual(ranking[1], "n10")

    def test_fallback_only_when_nothing_passes(self):
        cfg = copy.deepcopy(self.cfg)
        for q in cfg["gate"]["require"]:
            cfg["gate"]["require"][q]["score"] = ">=9"
        shortlist, rejected, pending, fallback = filter_rank(self.rows, cfg)
        self.assertEqual(len(shortlist), 0)
        self.assertGreaterEqual(len(fallback), 3)
        self.assertLessEqual(len(fallback), 5)
        for item in fallback:
            self.assertTrue(item["fallback"])
            self.assertEqual(item["reason"], "fallback_low_score")
            self.assertTrue(item["failed"])

    def test_fallback_can_be_disabled(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["fallback"] = {"enabled": False}
        for q in cfg["gate"]["require"]:
            cfg["gate"]["require"][q]["score"] = ">=9"
        shortlist, rejected, pending, fallback = filter_rank(self.rows, cfg)
        self.assertEqual(len(fallback), 0)

    def test_gate_is_config_driven(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["gate"]["require"] = {"structure_clarity": {"score": ">=8"}}
        shortlist, rejected, pending, fallback = filter_rank(self.rows, cfg)
        self.assertEqual(len(shortlist), 5)
        for item in shortlist:
            self.assertGreaterEqual(item["scores"]["structure_clarity"], 8)


if __name__ == "__main__":
    unittest.main(verbosity=2)
