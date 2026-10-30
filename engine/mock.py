# -*- coding: utf-8 -*-
"""v2.3 玩梗战况：谁在被嘲、谁被嘲得更多、传得更广。

与 thirdparty.py 的立场口径分开：玩梗帖即使被判 neutral/irrelevant，
只要 mock_target 命中，就进入本统计。
"""
import argparse
import json
import os

TARGETS = ("mocks_cn", "mocks_tr", "mocks_both", "spectator")
MOCKED = ("mocks_cn", "mocks_tr", "mocks_both")
LABEL = {
    "mocks_cn": "嘲讽中国",
    "mocks_tr": "嘲讽土耳其",
    "mocks_both": "两边一起嘲",
    "spectator": "纯看戏（无靶子）",
}
MIN_CONF = 5
EXCLUDE_LANGS = ("zh", "tr")  # 当事人语言，不计入第三方玩梗统计


def _choice(row, field):
    val = (row.get("jev") or {}).get(field)
    if isinstance(val, dict):
        return val.get("choice")
    return val if isinstance(val, str) else None


def _score(row, field):
    val = (row.get("jev") or {}).get(field)
    if isinstance(val, dict):
        val = val.get("score")
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _interaction(row):
    def num(v):
        try:
            return float(v or 0)
        except (TypeError, ValueError):
            return 0.0
    return num(row.get("likes")) + num(row.get("comments"))


def aggregate(rows):
    counts = {t: 0 for t in TARGETS}
    inter = {t: 0.0 for t in TARGETS}
    skipped = 0

    for row in rows:
        lang = str(row.get("lang") or "").strip().lower()
        if lang and lang in EXCLUDE_LANGS:
            skipped += 1
            continue
        target = _choice(row, "mock_target")
        conf = _score(row, "stance_confidence")
        if target not in TARGETS:
            skipped += 1
            continue
        if conf is not None and conf < MIN_CONF:
            skipped += 1
            continue
        counts[target] += 1
        inter[target] += _interaction(row)

    total_n = sum(counts.values())
    total_i = sum(inter.values())
    shares = {t: (counts[t] / total_n if total_n else 0.0) for t in TARGETS}
    ishares = {t: (inter[t] / total_i if total_i else 0.0) for t in TARGETS}
    leader = max(MOCKED, key=lambda t: (inter[t], counts[t])) if total_n else None

    return {
        "counts": counts,
        "interactions": inter,
        "shares": shares,
        "interaction_shares": ishares,
        "total_samples": total_n,
        "total_interaction": total_i,
        "skipped": skipped,
        "most_mocked_by_interaction": leader,
        "note": "被嘲更多的一方在玩梗战里处于下风；本统计与立场口径分开，不与 pro_cn/pro_tr 合并。",
    }


def render(result):
    lines = [
        "# 玩梗战况（v2.3）",
        "",
        "> 仅统计 mock_target 命中且置信度达标的第三方帖子；与立场口径分开，不能并入 pro_cn/pro_tr。",
        "",
        "| 靶子 | 条数 | 条数占比 | 互动量 | 互动占比 |",
        "|---|---:|---:|---:|---:|",
    ]
    for t in TARGETS:
        lines.append("| %s | %d | %.1f%% | %.0f | %.1f%% |" % (
            LABEL[t], result["counts"][t], result["shares"][t] * 100,
            result["interactions"][t], result["interaction_shares"][t] * 100))
    lines += [
        "",
        "- 样本：%d 条（跳过 %d 条：无靶子或低置信）" % (
            result["total_samples"], result["skipped"]),
        "",
    ]
    lead = result["most_mocked_by_interaction"]
    if lead:
        lines.append("**按互动加权，被嘲最多的是：%s** —— 该方在玩梗战里处于下风。" % LABEL[lead])
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    src = os.path.join(a.out_dir, "judged.jsonl")
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    result = aggregate(rows)
    with open(os.path.join(a.out_dir, "mock_report.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    with open(os.path.join(a.out_dir, "mock_report.md"), "w", encoding="utf-8") as f:
        f.write(render(result))
    print("mock report -> %s" % a.out_dir)


if __name__ == "__main__":
    main()
