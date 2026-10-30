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

import claims  # noqa: E402
from claims import aggregate, render_markdown  # noqa: E402


def load():
    with open(os.path.join(ROOT, "profiles", "claims-zh-tr.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    with open(os.path.join(HERE, "fixtures", "claims_sample.jsonl"), encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return cfg, rows


def find(items, text):
    matches = [item for item in items if item["claim_text"] == text]
    return matches[0] if matches else None


class ClaimsAggregateTest(unittest.TestCase):
    def setUp(self):
        self.cfg, self.rows = load()
        self.result = aggregate(self.rows, self.cfg)

    def test_missing_claim_text_and_type_are_counted(self):
        # c13 缺 claim_text，c14 缺 claim_type，c15 空白 claim_text。
        self.assertEqual(self.result["missing_claim_text"], 3)
        self.assertEqual(self.result["totals"]["missing_claim_text"], 3)
        self.assertEqual(self.result["totals"]["used"], 16)
        self.assertEqual(self.result["totals"]["input_rows"], 19)

    def test_single_occurrence_goes_to_one_off(self):
        text = "泛突厥主义是历史发明"
        item = find(self.result["one_off"], text)
        self.assertIsNotNone(item)
        self.assertEqual(item["post_count"], 1)
        self.assertEqual(item["total_interaction"], 350)
        self.assertIsNone(find(self.result["opinions"], text))

    def test_two_occurrences_become_an_opinion(self):
        text = "突厥基因更接近中亚"
        item = find(self.result["opinions"], text)
        self.assertIsNotNone(item)
        self.assertEqual(item["claim_stance"], "pro_tr")
        self.assertEqual(item["claim_type"], "genes")
        self.assertEqual(item["post_count"], 2)
        self.assertEqual(item["total_interaction"], 430)  # c4 250 + c5 180
        self.assertEqual(item["top_post"]["id"], "c4")
        self.assertEqual(item["top_post"]["url"], "https://example.com/c4")
        self.assertIsNone(find(self.result["one_off"], text))

    def test_three_occurrences_aggregate_counts_and_interaction(self):
        text = "长城是为了防御北方游牧"
        item = find(self.result["opinions"], text)
        self.assertIsNotNone(item)
        self.assertEqual(item["post_count"], 3)
        self.assertEqual(item["total_interaction"], 280)  # 120 + 90 + 70
        self.assertEqual(item["top_post"]["id"], "c1")

    def test_group_totals_include_opinions_and_one_off(self):
        group = [
            g for g in self.result["groups"]
            if g["claim_stance"] == "pro_cn" and g["claim_type"] == "history"
        ][0]
        self.assertEqual(group["post_count"], 4)          # 3 + c8
        self.assertEqual(group["total_interaction"], 630)  # 280 + 350
        self.assertEqual(len(group["opinions"]), 1)
        self.assertEqual(group["opinions"][0]["total_interaction"], 280)
        self.assertEqual(len(group["one_off"]), 1)
        self.assertEqual(group["one_off"][0]["total_interaction"], 350)

    def test_top10_is_sorted_by_interaction_within_stance(self):
        pro_cn = self.result["top10"]["pro_cn"]
        self.assertEqual(
            [item["claim_text"] for item in pro_cn],
            ["新疆文化保护很好", "长城是为了防御北方游牧"],
        )
        self.assertEqual(
            [item["total_interaction"] for item in pro_cn], [720, 280]
        )
        pro_tr = self.result["top10"]["pro_tr"]
        self.assertEqual([item["claim_text"] for item in pro_tr], ["突厥基因更接近中亚"])
        self.assertEqual(set(self.result["top10"]), {"pro_cn", "pro_tr"})

    def test_neutral_is_kept_in_groups_but_not_in_sections(self):
        neutral = self.result["by_stance"]["neutral"]
        self.assertEqual(len(neutral), 1)
        self.assertEqual(neutral[0]["post_count"], 1)
        self.assertNotIn("neutral", self.result["top10"])

    def test_markdown_has_two_stance_sections(self):
        markdown = render_markdown(self.result)
        self.assertIn("## 支持中国一方（pro_cn）", markdown)
        self.assertIn("## 支持土耳其一方（pro_tr）", markdown)
        self.assertNotIn("## 中立（neutral）", markdown)
        self.assertIn("新疆文化保护很好", markdown)

    def test_cli_writes_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "judged.jsonl"), "w", encoding="utf-8") as f:
                for row in self.rows:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            argv = [
                "claims.py",
                "--config", os.path.join(ROOT, "profiles", "claims-zh-tr.json"),
                "--out-dir", tmp,
            ]
            with mock.patch.object(sys, "argv", argv):
                claims.main()

            json_path = os.path.join(tmp, "claims_report.json")
            markdown_path = os.path.join(tmp, "claims_report.md")
            self.assertTrue(os.path.exists(json_path))
            self.assertTrue(os.path.exists(markdown_path))
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["missing_claim_text"], 3)
            self.assertEqual(len(data["opinions"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
