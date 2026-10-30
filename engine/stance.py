# -*- coding: utf-8 -*-
"""v2 立场分析：读 judged.jsonl，按三个口径聚合舆论热点中的立场分布。

三个口径（必须分开报，不得合并成单一结论）：
1. count_share   条数占比
2. weight_share  互动加权占比（likes + comments）
3. top_share     头部内容（Top N，默认 50）的立场分布

判定字段（题目名写死为这三个，选项由 profile 定义）：
- stance              choice: pro_cn / pro_tr / neutral / spectator / irrelevant
- stance_intensity    score 0-9
- stance_confidence   score 0-9

aggregate(rows, cfg) 是纯函数，不读写文件，便于测试。
"""
import argparse
import json
import os

STANCES = ("pro_cn", "pro_tr", "neutral", "spectator")
EXCLUDED_STANCES = ("irrelevant",)
DEFAULT_FIELDS = {
    "stance": "stance",
    "intensity": "stance_intensity",
    "confidence": "stance_confidence",
}
DISCLAIMER = "本结论只代表该平台该时间窗内可见样本，不代表全网民意。"

STANCE_DISPLAY = {
    "pro_cn": "支持中国一方（pro_cn）",
    "pro_tr": "支持土耳其一方（pro_tr）",
    "neutral": "中立（neutral）",
    "spectator": "旁观（spectator）",
}


def _num(value):
    """把可能缺失、为空或非数字的互动字段安全地转成 0。"""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _answer(row, field):
    jev = row.get("jev")
    if not isinstance(jev, dict):
        return None
    return jev.get(field)


def _as_choice(answer):
    if isinstance(answer, str):
        return answer.strip()
    if isinstance(answer, dict):
        for key in ("choice", "value", "answer", "label", "option", "stance"):
            value = answer.get(key)
            if value not in (None, ""):
                return str(value).strip()
    return None


def _as_score(answer):
    if isinstance(answer, bool):
        return None
    if isinstance(answer, (int, float)):
        return float(answer)
    if isinstance(answer, dict):
        for key in ("score", "value", "rating"):
            value = answer.get(key)
            if value not in (None, ""):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
    if isinstance(answer, str):
        try:
            return float(answer.strip())
        except ValueError:
            return None
    return None


def _settings(cfg):
    settings = cfg.get("settings") or {}
    return {
        "confidence_min": float(settings.get("confidence_min", 5)),
        "author_cap": int(settings.get("author_cap", 5)),
        "top_n": int(settings.get("top_n", 50)),
    }


def _fields(cfg):
    configured = cfg.get("fields") or {}
    return {key: configured.get(key, default) for key, default in DEFAULT_FIELDS.items()}


def _interaction(row):
    likes = _num(row.get("likes"))
    comments = _num(row.get("comments", row.get("comment")))
    return likes + comments


def _author_key(record):
    author = record.get("author")
    if author is None or str(author).strip() == "":
        # 匿名条目不能互相折叠成同一个“作者”。
        return "__anonymous__%d" % record["_index"]
    return str(author).strip()


def _records(rows, fields, confidence_min):
    """拆出有效样本、低置信度样本和各类排除计数。"""
    eligible, low = [], []
    excluded = {"missing_stance": 0, "irrelevant": 0, "invalid_stance": 0}

    for index, row in enumerate(rows):
        stance = _as_choice(_answer(row, fields["stance"]))
        if not stance:
            excluded["missing_stance"] += 1
            continue
        if stance in EXCLUDED_STANCES:
            excluded["irrelevant"] += 1
            continue
        if stance not in STANCES:
            excluded["invalid_stance"] += 1
            continue

        confidence = _as_score(_answer(row, fields["confidence"]))
        record = {
            "_index": index,
            "row": row,
            "stance": stance,
            "confidence": confidence,
            "intensity": _as_score(_answer(row, fields["intensity"])),
            "interaction": _interaction(row),
            "author": row.get("author"),
            "_low": confidence is None or confidence < confidence_min,
        }
        eligible.append(record)
        if record["_low"]:
            low.append(record)

    return eligible, low, excluded


def _fold_authors(eligible, high_confidence, cap):
    """同一作者超过 cap 条时只保留主口径中的第一条，并返回疑似水军账号。

    判定基于全部有效样本（含低置信度），折叠只作用于进入主口径的高置信度样本。
    """
    eligible_totals, high_totals = {}, {}
    for record in eligible:
        key = _author_key(record)
        eligible_totals[key] = eligible_totals.get(key, 0) + 1
    for record in high_confidence:
        key = _author_key(record)
        high_totals[key] = high_totals.get(key, 0) + 1

    suspects = {
        key: total
        for key, total in eligible_totals.items()
        if total > cap and not key.startswith("__anonymous__")
    }

    kept, seen, collapsed = [], set(), {}
    for record in high_confidence:
        key = _author_key(record)
        if key in suspects:
            if key in seen:
                collapsed[key] = collapsed.get(key, 0) + 1
                continue
            seen.add(key)
        kept.append(record)

    suspect_list = []
    for key in sorted(suspects, key=lambda name: (-suspects[name], name)):
        suspect_list.append({
            "author": key,
            "occurrences": suspects[key],
            "kept": 1 if high_totals.get(key, 0) else 0,
            "collapsed": collapsed.get(key, 0),
        })

    return kept, suspect_list


def _leader(shares):
    """并列时按 STANCES 的固定顺序取第一个，保证结果可复现。"""
    if not any(shares[stance] > 0 for stance in STANCES):
        return None
    return max(STANCES, key=lambda stance: (shares[stance], -STANCES.index(stance)))


def _brief(record):
    row = record["row"]
    return {
        "id": row.get("id"),
        "author": row.get("author"),
        "stance": record["stance"],
        "confidence": record["confidence"],
        "intensity": record["intensity"],
        "likes": row.get("likes"),
        "comments": row.get("comments", row.get("comment")),
        "interaction": record["interaction"],
        "url": row.get("url"),
    }


def _conclusion_text(leaders, consistent):
    count = leaders["count"] or "无"
    weight = leaders["weight"] or "无"
    top = leaders["top"] or "无"
    body = (
        "声量领先方：%s；互动领先方：%s；头部领先方：%s。"
        % (count, weight, top)
    )
    if consistent:
        return body
    return "三个口径结论不一致：" + body


def aggregate(rows, cfg):
    """按三个口径聚合立场，返回可直接 JSON 序列化的结构化结果。"""
    settings = _settings(cfg)
    fields = _fields(cfg)

    eligible, low, excluded = _records(rows, fields, settings["confidence_min"])
    high_confidence = [record for record in eligible if not record["_low"]]
    effective, suspect_authors = _fold_authors(
        eligible, high_confidence, settings["author_cap"]
    )

    counts = {stance: 0 for stance in STANCES}
    interactions = {stance: 0.0 for stance in STANCES}
    intensity_sum = {stance: 0.0 for stance in STANCES}
    intensity_n = {stance: 0 for stance in STANCES}

    for record in effective:
        stance = record["stance"]
        counts[stance] += 1
        interactions[stance] += record["interaction"]
        if record["intensity"] is not None:
            intensity_sum[stance] += record["intensity"]
            intensity_n[stance] += 1

    effective_count = len(effective)
    total_interaction = sum(interactions.values())

    count_share = {
        stance: (counts[stance] / effective_count if effective_count else 0.0)
        for stance in STANCES
    }
    weight_share = {
        stance: (interactions[stance] / total_interaction if total_interaction else 0.0)
        for stance in STANCES
    }

    # 头部口径：按互动降序，互动并列时保持输入顺序。
    ordered = sorted(effective, key=lambda record: (-record["interaction"], record["_index"]))
    top_records = ordered[: max(0, settings["top_n"])]
    top_counts = {stance: 0 for stance in STANCES}
    for record in top_records:
        top_counts[record["stance"]] += 1
    top_total = len(top_records)
    top_share = {
        stance: (top_counts[stance] / top_total if top_total else 0.0)
        for stance in STANCES
    }

    leaders = {
        "count": _leader(count_share),
        "weight": _leader(weight_share),
        "top": _leader(top_share),
    }
    consistent = len(set(leaders.values())) == 1
    conclusion = _conclusion_text(leaders, consistent)

    top_items = []
    for rank, record in enumerate(top_records, 1):
        item = _brief(record)
        item["rank"] = rank
        top_items.append(item)

    avg_intensity = {
        stance: (
            round(intensity_sum[stance] / intensity_n[stance], 2)
            if intensity_n[stance]
            else None
        )
        for stance in STANCES
    }

    return {
        "source": cfg.get("source"),
        "platform": cfg.get("platform"),
        "settings": settings,
        "fields": fields,
        "totals": {
            "input_rows": len(rows),
            "eligible": len(eligible),
            "effective": effective_count,
            "low_confidence": len(low),
            "missing_stance": excluded["missing_stance"],
            "irrelevant": excluded["irrelevant"],
            "invalid_stance": excluded["invalid_stance"],
        },
        "counts": counts,
        "count_share": count_share,
        "interactions": interactions,
        "total_interaction": total_interaction,
        "weight_share": weight_share,
        "top_n": settings["top_n"],
        "top_considered": top_total,
        "top_counts": top_counts,
        "top_share": top_share,
        "avg_intensity": avg_intensity,
        "low_confidence": [_brief(record) for record in low],
        "suspect_authors": suspect_authors,
        "top_items": top_items,
        "leaders": leaders,
        "consistent": consistent,
        "conclusion": conclusion,
        "disclaimer": DISCLAIMER,
    }


def _pct(value):
    return "%.1f%%" % (value * 100)


def render_markdown(result):
    """把 aggregate 的结果渲染成报告；所有数字都直接来自 result。"""
    totals = result["totals"]
    lines = [
        "# 舆论热点立场分析",
        "",
        "> " + result["disclaimer"],
        "",
        "## 结论",
        "",
        result["conclusion"],
        "",
    ]
    if not result["consistent"]:
        lines.extend([
            "三个口径给出的领先方不同，请分别解读，不要合并成单一结论。",
            "",
        ])

    top_considered = result.get("top_considered", result["top_n"])
    lines.extend([
        "## 三口径分布",
        "",
        "| 立场 | 条数 | 条数占比 | 互动量 | 互动加权占比 | Top %d 条数 | Top %d 占比 |"
        % (top_considered, top_considered),
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    for stance in STANCES:
        lines.append(
            "| %s | %d | %s | %s | %s | %d | %s |"
            % (
                STANCE_DISPLAY[stance],
                result["counts"][stance],
                _pct(result["count_share"][stance]),
                round(result["interactions"][stance], 2),
                _pct(result["weight_share"][stance]),
                result["top_counts"][stance],
                _pct(result["top_share"][stance]),
            )
        )

    lines.extend([
        "",
        "## 数据口径",
        "",
        "- 输入条目：%d" % totals["input_rows"],
        "- 有效样本（主口径，已去水军）：%d" % totals["effective"],
        "- 低置信度（未计入主口径）：%d" % totals["low_confidence"],
        "- irrelevant（未计入）：%d" % totals["irrelevant"],
        "- 缺失 stance（未计入）：%d" % totals["missing_stance"],
        "- 非法 stance（未计入）：%d" % totals["invalid_stance"],
        "",
        "## 疑似水军账号",
        "",
    ])
    if result["suspect_authors"]:
        lines.extend([
            "| 账号 | 出现条数 | 保留 | 折叠 |",
            "|---|---:|---:|---:|",
        ])
        for item in result["suspect_authors"]:
            lines.append(
                "| %s | %d | %d | %d |"
                % (item["author"], item["occurrences"], item["kept"], item["collapsed"])
            )
    else:
        lines.append("未发现同一账号超过 author_cap 条的重复发帖。")

    lines.extend(["", "## 低置信度条目", ""])
    if result["low_confidence"]:
        lines.extend([
            "| id | 账号 | 立场 | 置信度 | 互动量 |",
            "|---|---|---|---:|---:|",
        ])
        for item in result["low_confidence"]:
            lines.append(
                "| %s | %s | %s | %s | %s |"
                % (
                    item["id"],
                    item["author"],
                    item["stance"],
                    item["confidence"],
                    round(item["interaction"], 2),
                )
            )
    else:
        lines.append("无。")

    lines.extend(["", "## 头部内容（按互动降序）", ""])
    if result["top_items"]:
        lines.extend([
            "| 排名 | id | 账号 | 立场 | 互动量 |",
            "|---:|---|---|---|---:|",
        ])
        for item in result["top_items"]:
            lines.append(
                "| %d | %s | %s | %s | %s |"
                % (
                    item["rank"],
                    item["id"],
                    item["author"],
                    item["stance"],
                    round(item["interaction"], 2),
                )
            )
    else:
        lines.append("无有效样本。")

    lines.extend(["", "---", "", result["disclaimer"], ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="舆论热点立场分析（三口径）")
    parser.add_argument("--config", required=True, help="stance profile 路径")
    parser.add_argument("--out-dir", required=True, help="包含 judged.jsonl 的运行目录")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as handle:
        cfg = json.load(handle)

    src = os.path.join(args.out_dir, "judged.jsonl")
    with open(src, encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]

    result = aggregate(rows, cfg)
    os.makedirs(args.out_dir, exist_ok=True)

    json_path = os.path.join(args.out_dir, "stance_report.json")
    markdown_path = os.path.join(args.out_dir, "stance_report.md")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    with open(markdown_path, "w", encoding="utf-8") as handle:
        handle.write(render_markdown(result))

    print(
        "有效样本 %d / 输入 %d；低置信 %d；疑似水军 %d；%s"
        % (
            result["totals"]["effective"],
            result["totals"]["input_rows"],
            result["totals"]["low_confidence"],
            len(result["suspect_authors"]),
            result["conclusion"],
        )
    )


if __name__ == "__main__":
    main()
