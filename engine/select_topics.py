# -*- coding: utf-8 -*-
"""小红书调研筛选：内容四维（全部 >=7）+ 数据门槛（赞 / 收藏比）。"""
import argparse
import json
import os

DIMS = ["information_density", "copyability", "structure_clarity", "differentiation"]
MIN_DIM = 7


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


def filter_rank(rows, cfg):
    metrics = cfg.get("metrics", {})
    min_likes = float(metrics.get("min_likes", 500))
    min_ratio = float(metrics.get("min_collect_ratio", 0.15))

    shortlist, rejected, pending = [], [], []

    for r in rows:
        if not isinstance(r.get("jev"), dict):
            continue

        likes = r.get("likes")
        collects = r.get("collects")

        if likes in (None, "") or collects in (None, ""):
            item = brief(r)
            item["reason"] = "unverifiable"
            pending.append(item)
            continue

        likes = float(likes)
        collects = float(collects)

        if likes < min_likes:
            item = brief(r)
            item["reason"] = "gate_metric"
            item["actual"] = {"likes": likes, "min_likes": min_likes}
            rejected.append(item)
            continue

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

        scores = {d: g(r, d, "score", 0) for d in DIMS}
        failed = [d for d in DIMS if scores[d] < MIN_DIM]
        if failed:
            item = brief(r)
            item["reason"] = "gate_require"
            item["failed"] = failed
            item["scores"] = scores
            rejected.append(item)
            continue

        item = brief(r)
        item["score"] = round(sum(scores.values()) / len(DIMS), 2)
        item["scores"] = scores
        shortlist.append(item)

    shortlist.sort(key=lambda x: (-x["score"], -(x.get("likes") or 0)))
    return shortlist, rejected, pending


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()

    cfg = json.load(open(a.config, encoding="utf-8"))
    src = os.path.join(a.out_dir, "judged.jsonl")
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]

    shortlist, rejected, pending = filter_rank(rows, cfg)
    top = shortlist[: a.top]

    os.makedirs(a.out_dir, exist_ok=True)
    json.dump(top, open(os.path.join(a.out_dir, "shortlist.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(rejected, open(os.path.join(a.out_dir, "shortlist_rejected.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump(pending, open(os.path.join(a.out_dir, "pending_review.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print(f"入 Top {len(top)} / 淘汰 {len(rejected)} / 待核 {len(pending)}")


if __name__ == "__main__":
    main()
