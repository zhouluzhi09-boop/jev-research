# -*- coding: utf-8 -*-
import copy
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "engine"))

import stance  # noqa: E402
from stance import STANCES, aggregate, render_markdown  # noqa: E402


def load():
    with open(os.path.join(ROOT, "profiles", "stance-xhs.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    with open(os.path.join(HERE, "fixtures", "stance_sample.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return cfg, rows


class StanceAggregateTest(unittest.TestCase):
    def setUp(self):
        self.cfg, self.rows = load()
        self.result = aggregate(self.rows, self.cfg)

    def test_shares_sum_to_one(self):
        for key in ("count_share", "weight_share", "top_share"):
            self.assertAlmostEqual(sum(self.result[key].values()), 1.0, places=9, msg=key)

    def test_share_keys_are_valid_stances_only(self):
        for key in ("count_share", "weight_share", "top_share"):
            self.assertEqual(set(self.result[key]), set(STANCES))
            self.assertNotIn("irrelevant", self.result[key])

    def test_irrelevant_and_missing_are_excluded(self):
        self.assertEqual(self.result["totals"]["irrelevant"], 1)
        self.assertEqual(self.result["totals"]["missing_stance"], 1)
        self.assertEqual(self.result["totals"]["effective"], 4)
        # r11 的 99999 点赞不得进入互动总额
        self.assertAlmostEqual(self.result["total_interaction"], 3910.0)

    def test_low_confidence_is_separate(self):
        low = self.result["low_confidence"]
        self.assertEqual(len(low), 1)
        self.assertEqual(low[0]["id"], "r4")
        self.assertEqual(low[0]["stance"], "pro_cn")
        self.assertEqual(low[0]["confidence"], 3)
        # r4 被剔除后 pro_cn 只剩 r1；若漏算会变成 2
        self.assertEqual(self.result["counts"]["pro_cn"], 1)

    def test_suspect_author_folded(self):
        suspects = {item["author"]: item for item in self.result["suspect_authors"]}
        self.assertIn("spam_a", suspects)
        self.assertEqual(suspects["spam_a"]["occurrences"], 7)
        self.assertEqual(suspects["spam_a"]["collapsed"], 5)
        self.assertEqual(suspects["spam_a"]["kept"], 1)

    def test_author_cap_is_config_driven(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["settings"]["author_cap"] = 100
        result = aggregate(self.rows, cfg)
        self.assertEqual(result["suspect_authors"], [])
        self.assertEqual(result["totals"]["effective"], 9)
        self.assertEqual(result["counts"]["pro_cn"], 3)
        self.assertEqual(result["counts"]["pro_tr"], 3)

    def test_top_n_limits_head(self):
        cfg = copy.deepcopy(self.cfg)
        cfg["settings"]["top_n"] = 2
        result = aggregate(self.rows, cfg)
        self.assertEqual(result["top_n"], 2)
        self.assertEqual(result["top_considered"], 2)
        # 互动前二：r10(spectator, 1400)、r1(pro_cn, 1100)
        self.assertEqual(result["top_counts"]["spectator"], 1)
        self.assertEqual(result["top_counts"]["pro_cn"], 1)
        self.assertAlmostEqual(sum(result["top_share"].values()), 1.0, places=9)

    def test_conclusion_consistent(self):
        self.assertTrue(self.result["consistent"])
        self.assertEqual(self.result["top_n"], 50)
        self.assertEqual(self.result["top_considered"], 4)
        self.assertEqual(
            self.result["leaders"],
            {"count": "neutral", "weight": "neutral", "top": "neutral"},
        )
        for label in ("声量领先方", "互动领先方", "头部领先方"):
            self.assertIn(label, self.result["conclusion"])
        self.assertNotIn("三个口径结论不一致", self.result["conclusion"])
        self.assertNotIn("赢", self.result["conclusion"])

    def test_conclusion_inconsistent(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            if row.get("author") == "user_d":
                row["likes"] = 100000
        cfg = copy.deepcopy(self.cfg)
        cfg["settings"]["top_n"] = 1
        result = aggregate(rows, cfg)
        self.assertFalse(result["consistent"])
        self.assertEqual(result["leaders"]["count"], "neutral")
        self.assertEqual(result["leaders"]["weight"], "spectator")
        self.assertEqual(result["leaders"]["top"], "spectator")
        self.assertIn("三个口径结论不一致", result["conclusion"])

    def test_markdown_has_disclaimer_and_labels(self):
        markdown = render_markdown(self.result)
        self.assertIn("本结论只代表该平台该时间窗内可见样本，不代表全网民意", markdown)
        for label in ("声量领先方", "互动领先方", "头部领先方"):
            self.assertIn(label, markdown)
        self.assertNotIn("赢", markdown)

    def test_cli_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "judged.jsonl"), "w", encoding="utf-8") as f:
                for row in self.rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            argv = [
                "stance.py",
                "--config", os.path.join(ROOT, "profiles", "stance-xhs.json"),
                "--out-dir", tmp,
            ]
            with mock.patch.object(sys, "argv", argv):
                stance.main()

            json_path = os.path.join(tmp, "stance_report.json")
            markdown_path = os.path.join(tmp, "stance_report.md")
            self.assertTrue(os.path.exists(json_path))
            self.assertTrue(os.path.exists(markdown_path))
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["totals"]["effective"], 4)
            self.assertEqual(data["leaders"]["count"], "neutral")


if __name__ == "__main__":
    unittest.main(verbosity=2)
