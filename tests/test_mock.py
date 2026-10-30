# -*- coding: utf-8 -*-
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "engine"))

from mock import aggregate  # noqa: E402


def row(i, lang, target, likes=10, conf=8):
    return {
        "id": i, "lang": lang, "likes": likes, "comments": 0,
        "jev": {
            "mock_target": {"choice": target},
            "stance_confidence": {"score": conf},
        },
    }


class MockTest(unittest.TestCase):
    def test_zh_and_tr_excluded(self):
        rows = [row("a", "en", "mocks_tr", 10), row("b", "zh", "mocks_tr", 999),
                row("c", "tr", "mocks_cn", 888)]
        r = aggregate(rows)
        self.assertEqual(r["counts"]["mocks_tr"], 1)
        self.assertEqual(r["interactions"]["mocks_tr"], 10)
        self.assertEqual(r["counts"]["mocks_cn"], 0)

    def test_spectator_is_separate(self):
        rows = [row("a", "en", "spectator", 5), row("b", "en", "mocks_cn", 3)]
        r = aggregate(rows)
        self.assertEqual(r["counts"]["spectator"], 1)
        self.assertEqual(r["counts"]["mocks_cn"], 1)

    def test_leader_ignores_spectator(self):
        rows = [row("a", "en", "spectator", 1000), row("b", "en", "mocks_tr", 2)]
        r = aggregate(rows)
        self.assertEqual(r["most_mocked_by_interaction"], "mocks_tr")

    def test_low_confidence_skipped(self):
        rows = [row("a", "en", "mocks_tr", 10, conf=2), row("b", "en", "mocks_cn", 4)]
        r = aggregate(rows)
        self.assertEqual(r["total_samples"], 1)
        self.assertEqual(r["skipped"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
