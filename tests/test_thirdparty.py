# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "engine"))

import thirdparty  # noqa: E402
from thirdparty import LEANS, aggregate, render_markdown  # noqa: E402


def load():
    with open(os.path.join(ROOT, "profiles", "thirdparty-en.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    with open(os.path.join(HERE, "fixtures", "thirdparty_sample.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return cfg, rows


def make_rows(spec, confidence=8, likes=1, comments=0):
    """按 {lean: 条数} 造有效样本；id 从 g0 递增，便于断言 Top1。"""
    rows = []
    for lean, count in spec.items():
        for _ in range(count):
            index = len(rows)
            rows.append({
                "id": "g%d" % index,
                "platform": "x",
                "lang": "en",
                "author": "author_%d" % index,
                "text": "sample %d" % index,
                "likes": likes,
                "comments": comments,
                "url": "https://example.com/g%d" % index,
                "jev": {
                    "third_party_lean": {"choice": lean},
                    "tone": {"choice": "serious"},
                    "stance_confidence": {"score": confidence},
                },
            })
    return rows


class ThirdPartyAggregateTest(unittest.TestCase):
    def setUp(self):
        self.cfg, self.rows = load()
        self.result = aggregate(self.rows, self.cfg)

    def test_small_sample_only_reports_distribution(self):
        self.assertLess(self.result["totals"]["effective"], 50)
        self.assertEqual(self.result["conclusion"], "样本不足，仅报分布")
        self.assertEqual(self.result["lean_band"], "unknown")

    def test_shares_sum_to_one(self):
        for key in ("count_share", "weight_share", "top_share"):
            self.assertAlmostEqual(sum(self.result[key].values()), 1.0, places=9, msg=key)

    def test_share_keys_are_valid_leans_only(self):
        for key in ("count_share", "weight_share", "top_share"):
            self.assertEqual(set(self.result[key]), set(LEANS))
            self.assertNotIn("irrelevant", self.result[key])

    def test_both_negative_is_its_own_class(self):
        # 3 条 both_negative 不得并入 neutral；neutral 独立为 2 条。
        self.assertEqual(self.result["counts"]["both_negative"], 3)
        self.assertEqual(self.result["counts"]["neutral"], 2)
        self.assertGreater(self.result["count_share"]["both_negative"], 0)
        self.assertEqual(
            sum(self.result["counts"][lean] for lean in LEANS),
            self.result["totals"]["effective"],
        )

    def test_exclusions_and_totals(self):
        totals = self.result["totals"]
        self.assertEqual(totals["input_rows"], 18)
        self.assertEqual(totals["effective"], 13)
        self.assertEqual(totals["low_confidence"], 2)
        self.assertEqual(totals["irrelevant"], 1)
        self.assertEqual(totals["missing_lean"], 1)
        self.assertEqual(totals["invalid_lean"], 1)
        # p13 / p14 / p17 的巨额互动不得进入有效互动总额
        self.assertAlmostEqual(self.result["total_interaction"], 5855.0)

    def test_markdown_starts_with_disclaimer(self):
        markdown = render_markdown(self.result)
        first_line = markdown.splitlines()[0]
        self.assertIn("免责声明", first_line)
        self.assertIn("不代表第三方世界或全网民意", markdown)
        self.assertIn("样本不足", markdown)

    def test_cli_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "judged.jsonl"), "w", encoding="utf-8") as f:
                for row in self.rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            argv = [
                "thirdparty.py",
                "--config", os.path.join(ROOT, "profiles", "thirdparty-en.json"),
                "--out-dir", tmp,
            ]
            with mock.patch.object(sys, "argv", argv):
                thirdparty.main()

            json_path = os.path.join(tmp, "thirdparty_report.json")
            markdown_path = os.path.join(tmp, "thirdparty_report.md")
            self.assertTrue(os.path.exists(json_path))
            self.assertTrue(os.path.exists(markdown_path))
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["lean_band"], "unknown")
            self.assertEqual(data["totals"]["effective"], 13)


class ThirdPartyBandTest(unittest.TestCase):
    def setUp(self):
        self.cfg, _ = load()
        self.cfg["settings"]["top_n"] = 50

    def band(self, spec):
        return aggregate(make_rows(spec), self.cfg)["lean_band"]

    def test_clear_at_70_percent(self):
        self.assertEqual(self.band({"pro_cn": 70, "pro_tr": 30}), "clear")

    def test_slight_at_58_percent(self):
        self.assertEqual(self.band({"pro_cn": 58, "pro_tr": 42}), "slight")

    def test_none_at_52_percent(self):
        result = aggregate(make_rows({"pro_cn": 52, "pro_tr": 48}), self.cfg)
        self.assertEqual(result["lean_band"], "none")
        self.assertEqual(result["conclusion"], "无明显倾向")

    def test_sample_threshold_is_config_driven(self):
        cfg = json.loads(json.dumps(self.cfg))
        cfg["settings"]["sample_min"] = 101
        result = aggregate(make_rows({"pro_cn": 70, "pro_tr": 30}), cfg)
        self.assertEqual(result["lean_band"], "unknown")
        self.assertEqual(result["conclusion"], "样本不足，仅报分布")


class ThirdPartySinglePostTest(unittest.TestCase):
    def setUp(self):
        self.cfg, _ = load()

    def test_single_post_driven_when_top1_reaches_40_percent(self):
        rows = make_rows({"pro_cn": 60, "pro_tr": 40}, likes=0)
        # pro_cn 总互动 = 9 + 11 * 1 = 20，Top1 = 9，正好占 45%。
        rows[0]["likes"] = 9
        for row in rows[1:12]:
            row["likes"] = 1
        result = aggregate(rows, self.cfg)
        self.assertTrue(result["single_post_driven"])
        self.assertIsNotNone(result["single_post"])
        self.assertEqual(result["single_post"]["id"], "g0")
        self.assertEqual(result["single_post"]["lean"], "pro_cn")
        self.assertAlmostEqual(
            result["single_post"]["interaction"]
            / result["interactions"]["pro_cn"],
            0.45,
        )
        self.assertIn("单条驱动", render_markdown(result))

    def test_not_single_post_driven_when_spread_out(self):
        result = aggregate(make_rows({"pro_cn": 60, "pro_tr": 40}), self.cfg)
        self.assertFalse(result["single_post_driven"])
        self.assertIsNone(result["single_post"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
