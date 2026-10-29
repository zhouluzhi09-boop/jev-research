# -*- coding: utf-8 -*-
"""Jev 判断层：读归一化 JSONL，L0 过滤后调 Jev 四维打标。"""
import argparse
import json
import os
import sys

sys.path.insert(0, r"D:\dshworkspace\jev-win\core")


def l0(row, cfg):
    eng = cfg.get("engagement", {})
    likes_min = eng.get("likes_min", 0)
    likes = row.get("likes")
    if likes is not None and likes < likes_min:
        return False, "low_engagement"

    text = (row.get("title") or "") + " " + (row.get("text") or "")
    bl = cfg.get("blacklist", {})
    for w in bl.get("zh", []) + bl.get("en", []):
        if w and w.lower() in text.lower():
            return False, f"blacklist:{w}"
    return True, "ok"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--config", required=True)
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()

    cfg = json.load(open(a.config, encoding="utf-8"))
    from jev_client import ask

    rows = [json.loads(l) for l in open(a.src, encoding="utf-8") if l.strip()]
    os.makedirs(a.out_dir, exist_ok=True)

    judged_path = os.path.join(a.out_dir, "judged.jsonl")
    rejected_path = os.path.join(a.out_dir, "rejected.jsonl")
    ok = 0
    cost = 0.0

    with open(judged_path, "w", encoding="utf-8") as jf, \
            open(rejected_path, "w", encoding="utf-8") as rf:
        for row in rows:
            keep, reason = l0(row, cfg)
            if not keep:
                row["l0"] = reason
                rf.write(json.dumps(row, ensure_ascii=False) + "\n")
                continue

            payload = {"tweet": (row.get("title") or "") + "\n" + (row.get("text") or "")}
            try:
                resp = ask(payload, cfg["jev_questions"], timeout=30)
                row["jev"] = resp.get("answers", {})
                cost += resp.get("usage", {}).get("cost", 0)
                ok += 1
            except Exception as e:
                row["jev_error"] = str(e)[:200]
            jf.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"判断 {ok}/{len(rows)}，成本 {cost:.4f} 美元")


if __name__ == "__main__":
    main()
