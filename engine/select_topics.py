# -*- coding: utf-8 -*-
"""小红书调研筛选：配置驱动闸门 + 数据门槛 + 加权评分；无合格样本时降级 3-5 条。"""
import argparse
import json
import os
import re

DEFAULT_DIMS = ["information_density", "copyability", "structure_clarity", "differentiation"]
DEFAULT_MIN = 7
SPECIAL_KEYS = {"lightness"}


def g(row, q, k, d=0):
    return row.get("jev", {}).get(q, {}).get(k, d)


def brief(r):
    return {
        "id": r.get("id"),
        "platform": r.get("platform"),
        "title": r.get("title"),
        "author": r.get("author"),
        "likes": r.get("likes"),
        "collects": r.get("collects"),
        "url": r.get("url"),
    }


def compare(val, expr):
    m = re.match(r"^(>=|<=|==|!=|>|<)\s*(-?\d+(?:\.\d+)?)$", str(expr).strip())
    if not m:
        return False
    op, num = m.group(1), float(m.group(2))
    try:
        v = float(val)
    except (TypeError, ValueError):
        v = 0.0
    return {
        ">=": v >= num, "<=": v <= num, "==": v == num,
        "!=": v != num, ">": v > num, "<": v < num,
    }[op]


def gate_require(cfg):
    return (cfg.get("gate") or {}).get("require") or {}


def weights(cfg):
    w = (cfg.get("ranking") or {}).get("weights") or {}
    return {k: float(v) for k, v in w.items() if k not in SPECIAL_KEYS}


def score_dims(cfg):
    dims = set(gate_require(cfg)) | set(weights(cfg))
    return sorted(dims) if dims else list(DEFAULT_DIMS)


def score_of(scores, w):
    if not scores:
        return 0.0
    ws = {k: float(w.get(k, 1.0)) for k in scores}
    total = sum(ws.values()) or 1.0
    return round(sum(scores[k] * ws[k] for k in scores) / total, 2)


def failed_dims(row, cfg):
    gate = cfg.get("gate") or {}
    failed = []
    for q, cond in (gate.get("require") or {}).items():
        for dim, expr in cond.items():
            if not compare(g(row, q, dim, 0), expr):
                failed.append(q)
                break
    for q, cond in (gate.get("forbid") or {}).items():
        for dim, expected in cond.items():
            if g(row, q, dim, "") == expected:
                failed.append(q)
                break
    for q, limit in (gate.get("max_score") or {}).items():
        if g(row, q, "score", 9) > limit:
            failed.append(q)
    if not gate:
        for d in DEFAULT_DIMS:
            if g(row, d, "score", 0) < DEFAULT_MIN:
                failed.append(d)
    return failed


def filter_rank(rows, cfg):
    metrics = cfg.get("metrics", {})
    min_likes = float(metrics.get("min_likes", 500))
    min_ratio = float(metrics.get("min_collect_ratio", 0.15))
    dims = score_dims(cfg)
    w = weights(cfg)

    shortlist, rejected, pending = [], [], []

    for r in rows:
        if not isinstance(r.get("jev"), dict):
            continue

        likes = r.get("likes")
        collects = r.get("collects")

        if likes in (None, ""):
            item = brief(r)
            item["reason"] = "unverifiable"
            pending.append(item)
            continue

        likes = float(likes)
        if likes < min_likes:
            item = brief(r)
            item["reason"] = "gate_metric"
            item["actual"] = {"likes": likes, "min_likes": min_likes}
            rejected.append(item)
            continue

        if collects in (None, ""):
            item = brief(r)
            item["reason"] = "unverifiable"
            pending.append(item)
            continue

        collects = float(collects)
        ratio = collects / likes if likes else 0.0
        if ratio < min_ratio:
            item = brief(r)
            item["reason"] = "gate_metric"
            item["actual"] = {
                "collect_ratio": round(ratio, 3),
                "min_collect_ratio": min_ratio,
            }
            rejected.append(item)
            continue

        scores = {d: g(r, d, "score", 0) for d in dims}
        failed = failed_dims(r, cfg)
        if failed:
            item = brief(r)
            item["reason"] = "gate_require"
            item["failed"] = failed
            item["scores"] = scores
            rejected.append(item)
            continue

        item = brief(r)
        item["score"] = score_of(scores, w)
        item["scores"] = scores
        shortlist.append(item)

    shortlist.sort(key=lambda x: (-x["score"], -(x.get("likes") or 0)))

    fallback = []
    fb = cfg.get("fallback", {})
    if fb.get("enabled", True) and not shortlist:
        fb_max = int(fb.get("max_items", 5))
        cands = [r for r in rejected if r.get("scores")]
        cands.sort(key=lambda r: -score_of(r["scores"], w))
        for r in cands[: max(0, min(fb_max, len(cands)))]:
            item = dict(r)
            item["fallback"] = True
            item["avg_score"] = score_of(r["scores"], w)
            item["reason"] = "fallback_low_score"
            fallback.append(item)

    return shortlist, rejected, pending, fallback


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()

    cfg = json.load(open(a.config, encoding="utf-8"))
    src = os.path.join(a.out_dir, "judged.jsonl")
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]

    shortlist, rejected, pending, fallback = filter_rank(rows, cfg)
    top = shortlist[: a.top]

    os.makedirs(a.out_dir, exist_ok=True)
    for name, data in (
        ("shortlist.json", top),
        ("shortlist_rejected.json", rejected),
        ("pending_review.json", pending),
        ("shortlist_fallback.json", fallback),
    ):
        json.dump(data, open(os.path.join(a.out_dir, name), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)

    print(f"入 Top {len(top)} / 淘汰 {len(rejected)} / 待核 {len(pending)} / 降级 {len(fallback)}")
    if fallback and not top:
        print("本轮无合格样本，已降级推荐 " + str(len(fallback)) + " 条，报告中必须说明降级原因")


if __name__ == "__main__":
    main()
