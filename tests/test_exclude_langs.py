# -*- coding: utf-8 -*-
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from thirdparty import aggregate  # noqa: E402


def row(i, lang, lean, score=8, likes=10):
    return {
        "id": i, "lang": lang, "likes": likes, "comments": 0,
        "jev": {
            "third_party_lean": {"choice": lean},
            "tone": {"choice": "serious"},
            "stance_confidence": {"score": score},
        },
    }


CFG = {"settings": {"exclude_langs": ["zh", "tr"], "sample_min": 1}}


class ExcludeLangTest(unittest.TestCase):
    def test_zh_and_tr_are_dropped(self):
        rows = [row("a", "en", "pro_cn"), row("b", "zh", "pro_cn"),
                row("c", "tr", "pro_tr"), row("d", "de", "pro_tr")]
        r = aggregate(rows, CFG)
        self.assertEqual(r["totals"]["input_rows"], 4)
        self.assertEqual(r["totals"]["effective"], 2)
        self.assertEqual(r["totals"]["excluded_lang"], 2)

    def test_missing_lang_is_kept(self):
        rows = [row("a", None, "pro_cn"), row("b", "zh", "pro_cn")]
        r = aggregate(rows, CFG)
        self.assertEqual(r["totals"]["effective"], 1)
        self.assertEqual(r["totals"]["excluded_lang"], 1)

    def test_exclude_list_is_configurable(self):
        cfg = {"settings": {"exclude_langs": ["en"], "sample_min": 1}}
        rows = [row("a", "en", "pro_cn"), row("b", "fr", "pro_cn")]
        r = aggregate(rows, cfg)
        self.assertEqual(r["totals"]["effective"], 1)
        self.assertEqual(r["totals"]["excluded_lang"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
