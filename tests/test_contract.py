# -*- coding: utf-8 -*-
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from select_topics import DIMS, filter_rank  # noqa: E402


def load():
    cfg = json.load(open(os.path.join(ROOT, "profiles", "public-xhs.json"), encoding="utf-8"))
    rows = [json.loads(l) for l in open(os.path.join(HERE, "fixtures", "sample.jsonl"), encoding="utf-8") if l.strip()]
    return cfg, rows


class ContractTest(unittest.TestCase):
    def setUp(self):
        self.cfg, self.rows = load()
        self.shortlist, self.rejected, self.pending = filter_rank(self.rows, self.cfg)

    def test_counts(self):
        self.assertEqual(len(self.shortlist), 1)
        self.assertEqual(len(self.pending), 1)
        self.assertEqual(len(self.rejected), 4)

    def test_only_all_dims_pass(self):
        self.assertEqual(self.shortlist[0]["id"], "n1")
        for item in self.shortlist:
            for d in DIMS:
                self.assertGreaterEqual(item["scores"][d], 7, d)

    def test_missing_collects_goes_pending_not_dropped(self):
        self.assertEqual(self.pending[0]["id"], "n3")
        self.assertEqual(self.pending[0]["reason"], "unverifiable")

    def test_metric_gate(self):
        ids = {r["id"]: r for r in self.rejected}
        self.assertEqual(ids["n4"]["reason"], "gate_metric")
        self.assertEqual(ids["n5"]["reason"], "gate_metric")

    def test_content_gate_requires_every_dim(self):
        ids = {r["id"]: r for r in self.rejected}
        self.assertEqual(ids["n2"]["reason"], "gate_require")
        self.assertIn("information_density", ids["n2"]["failed"])
        self.assertEqual(ids["n6"]["reason"], "gate_require")
        self.assertIn("structure_clarity", ids["n6"]["failed"])

    def test_average_score_cannot_replace_threshold(self):
        # n2 平均 7.5，但单项 6，必须被淘汰
        avg = sum(v["score"] for v in self.rows[1]["jev"].values()) / 4
        self.assertGreaterEqual(avg, 7)
        self.assertEqual(self.rejected[[r["id"] for r in self.rejected].index("n2")]["reason"],
                         "gate_require")


if __name__ == "__main__":
    unittest.main(verbosity=2)
