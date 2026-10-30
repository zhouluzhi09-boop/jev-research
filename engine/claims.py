# -*- coding: utf-8 -*-
"""v2.1 B 链路：中文 / 土耳其语各自的高流量主张。

Jev 只做分类打分；一句话主张 claim_text 由外部 LLM 写入顶层字段。
缺 claim_text 或 claim_type 的条目不参与聚合，单独计入 missing_claim_text。

判定字段：
- claim_type   choice: history / genes / culture / economy / morality / mockery / other
- claim_stance choice: pro_cn / pro_tr / neutral

聚合规则：
1. 按 (claim_stance, claim_type) 分组；
2. 组内相同 claim_text 至少出现 MIN_REPEAT 次才算「观点」，否则计入 one_off；
3. 每个观点输出帖子数、总互动、Top1 帖子 id/url；
4. 按 pro_cn / pro_tr 分节，各节内按总互动降序取 Top TOP_N。

本链路的结论不与英语第三方链路（engine/thirdparty.py）合并。
aggregate(rows, cfg) 是纯函数，不读写文件。
"""
import argparse
import json
import os

# ---------------------------------------------------------------------------
# 阈值常量
# ---------------------------------------------------------------------------
MIN_REPEAT = 2       # 相同 claim_text 至少出现 2 次才算一个「观点」
TOP_N = 10           # 每个 stance 输出互动降序 Top 10

CLAIM_TYPES = (
    "history",
    "genes",
    "culture",
    "economy",
    "morality",
    "mockery",
    "other",
)
CLAIM_STANCES = ("pro_cn", "pro_tr", "neutral")
SECTION_STANCES = ("pro_cn", "pro_tr")

DEFAULT_FIELDS = {
    "type": "claim_type",
    "stance": "claim_stance",
}

STANCE_DISPLAY = {
    "pro_cn": "支持中国一方（pro_cn）",
    "pro_tr": "支持土耳其一方（pro_tr）",
    "neutral": "中立（neutral）",
}

DISCLAIMER = (
    "本报告只统计该平台该时间窗内可见样本中的重复主张；"
    "claim_text 由外部 LLM 写入，Jev 只负责分类打分。"
)


def _num(value):
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
        for key in ("choice", "value", "answer", "label", "option"):
            value = answer.get(key)
            if value not in (None, ""):
                return str(value).strip()
    return None


def _settings(cfg):
    settings = cfg.get("settings") or {}
    return {
        "min_repeat": int(settings.get("min_repeat", MIN_REPEAT)),
        "top_n": int(settings.get("top_n", TOP_N)),
    }


def _fields(cfg):
    configured = cfg.get("fields") or {}
    return {
        key: configured.get(key, default) for key, default in DEFAULT_FIELDS.items()
    }


def _interaction(row):
    likes = _num(row.get("likes"))
    comments = _num(row.get("comments", row.get("comment")))
    return likes + comments


def _claim_text(row):
    """claim_text 必须是顶层非空字符串；外部 LLM 不写就视为缺失。"""
    value = row.get("claim_text")
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _records(rows, fields):
    """过滤并拆出可聚合条目，同时统计缺失/非法原因。"""
    entries = []
    totals = {
        "input_rows": len(rows),
        "used": 0,
        "missing_claim_text": 0,   # 含缺 claim_type 的条目
        "missing_claim_stance": 0,
        "invalid_claim_type": 0,
        "invalid_claim_stance": 0,
    }

    for index, row in enumerate(rows):
        text = _claim_text(row)
        claim_type = _as_choice(_answer(row, fields["type"]))
        if text is None or claim_type is None:
            totals["missing_claim_text"] += 1
            continue
        if claim_type not in CLAIM_TYPES:
            totals["invalid_claim_type"] += 1
            continue

        stance = _as_choice(_answer(row, fields["stance"]))
        if stance is None:
            totals["missing_claim_stance"] += 1
            continue
        if stance not in CLAIM_STANCES:
            totals["invalid_claim_stance"] += 1
            continue

        entries.append({
            "_index": index,
            "row": row,
            "claim_text": text,
            "claim_type": claim_type,
            "claim_stance": stance,
            "interaction": _interaction(row),
        })

    totals["used"] = len(entries)
    return entries, totals


def _post_brief(entry):
    row = entry["row"]
    return {
        "id": row.get("id"),
        "url": row.get("url"),
        "author": row.get("author"),
        "likes": row.get("likes"),
        "comments": row.get("comments", row.get("comment")),
        "interaction": entry["interaction"],
    }


def _claim_item(text, posts, min_repeat):
    """把同一 claim_text 的帖子合成一个观点或 one_off。"""
    top = max(posts, key=lambda entry: (entry["interaction"], -entry["_index"]))
    return {
        "claim_text": text,
        "post_count": len(posts),
        "total_interaction": sum(entry["interaction"] for entry in posts),
        "top_post": _post_brief(top),
        "is_opinion": len(posts) >= min_repeat,
    }


def _sort_items(items):
    return sorted(
        items, key=lambda item: (-item["total_interaction"], item["claim_text"])
    )


def _groups(entries, min_repeat):
    """按 (stance, type) 分组，组内再按 claim_text 合并。"""
    buckets = {}
    for entry in entries:
        key = (entry["claim_stance"], entry["claim_type"])
        buckets.setdefault(key, []).append(entry)

    groups = []
    for (stance, claim_type), items in buckets.items():
        by_text, order = {}, []
        for entry in items:
            if entry["claim_text"] not in by_text:
                by_text[entry["claim_text"]] = []
                order.append(entry["claim_text"])
            by_text[entry["claim_text"]].append(entry)

        opinions, one_off = [], []
        for text in order:
            item = _claim_item(text, by_text[text], min_repeat)
            if item["is_opinion"]:
                opinions.append(item)
            else:
                one_off.append(item)

        groups.append({
            "claim_stance": stance,
            "claim_type": claim_type,
            "post_count": len(items),
            "total_interaction": sum(entry["interaction"] for entry in items),
            "opinions": _sort_items(opinions),
            "one_off": _sort_items(one_off),
        })

    stance_order = {stance: index for index, stance in enumerate(CLAIM_STANCES)}
    type_order = {
        claim_type: index for index, claim_type in enumerate(CLAIM_TYPES)
    }
    groups.sort(
        key=lambda group: (
            stance_order.get(group["claim_stance"], len(stance_order)),
            -group["total_interaction"],
            type_order.get(group["claim_type"], len(type_order)),
        )
    )
    return groups


def _flat(items, key):
    """从 groups 中摊平 opinions / one_off，并补上分组信息。"""
    flat = []
    for group in items:
        for item in group[key]:
            row = dict(item)
            row.pop("is_opinion", None)
            row["claim_stance"] = group["claim_stance"]
            row["claim_type"] = group["claim_type"]
            flat.append(row)
    return flat


def aggregate(rows, cfg):
    """聚合重复主张，返回可直接 JSON 序列化的结构化结果。"""
    settings = _settings(cfg)
    fields = _fields(cfg)

    entries, totals = _records(rows, fields)
    groups = _groups(entries, settings["min_repeat"])

    opinions = _flat(groups, "opinions")
    one_off = _flat(groups, "one_off")

    top10 = {}
    for stance in SECTION_STANCES:
        ranked = [item for item in opinions if item["claim_stance"] == stance]
        ranked.sort(key=lambda item: -item["total_interaction"])
        top10[stance] = ranked[: max(0, settings["top_n"])]

    by_stance = {}
    for stance in CLAIM_STANCES:
        by_stance[stance] = [
            group for group in groups if group["claim_stance"] == stance
        ]

    return {
        "source": cfg.get("source"),
        "platform": cfg.get("platform"),
        "settings": settings,
        "fields": fields,
        "totals": totals,
        "missing_claim_text": totals["missing_claim_text"],
        "groups": groups,
        "by_stance": by_stance,
        "opinions": opinions,
        "one_off": one_off,
        "top10": top10,
        "disclaimer": DISCLAIMER,
    }


def render_markdown(result):
    """按 pro_cn / pro_tr 两节渲染报告。"""
    totals = result["totals"]
    lines = [
        "# 中土双方主张分析（B 链路）",
        "",
        "> " + result["disclaimer"],
        "",
        "## 数据口径",
        "",
        "- 输入条目：%d" % totals["input_rows"],
        "- 参与聚合：%d" % totals["used"],
        "- 缺 claim_text / claim_type（未聚合）：%d"
        % totals["missing_claim_text"],
        "- 缺 claim_stance（未聚合）：%d" % totals["missing_claim_stance"],
        "- 非法 claim_type（未聚合）：%d" % totals["invalid_claim_type"],
        "- neutral（仅记录，不进入两节对比）：%d 条"
        % sum(group["post_count"] for group in result["by_stance"]["neutral"]),
        "",
        "规则：同一 claim_text 至少出现 %d 次才算一个观点，只出现 1 次的计入 "
        "one_off，不当作观点。" % result["settings"]["min_repeat"],
        "",
        "> 本链路结论只描述中文/土文各自在说什么，不得与英语第三方链路合并。",
        "",
    ]

    for stance in SECTION_STANCES:
        items = result["top10"][stance]
        lines.extend([
            "## %s" % STANCE_DISPLAY[stance],
            "",
        ])
        if items:
            lines.extend([
                "| 排名 | 主张 | 类型 | 帖子数 | 总互动 | 举例（id / url） |",
                "|---:|---|---|---:|---:|---|",
            ])
            for rank, item in enumerate(items, 1):
                top = item["top_post"]
                lines.append(
                    "| %d | %s | %s | %d | %s | %s / %s |"
                    % (
                        rank,
                        item["claim_text"],
                        item["claim_type"],
                        item["post_count"],
                        round(item["total_interaction"], 2),
                        top["id"],
                        top["url"],
                    )
                )
        else:
            lines.append("无重复出现的主张（可能样本不足）。")

        one_off_count = sum(
            1
            for group in result["by_stance"][stance]
            for item in group["one_off"]
        )
        lines.extend([
            "",
            "one_off（同一主张只出现 1 次，未计入观点）：%d 组。" % one_off_count,
            "",
        ])

    lines.extend(["", "---", "", result["disclaimer"], ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="v2.1 B 链路：中/土双方主张分析")
    parser.add_argument("--config", required=True, help="claims profile 路径")
    parser.add_argument("--out-dir", required=True, help="包含 judged.jsonl 的运行目录")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as handle:
        cfg = json.load(handle)

    src = os.path.join(args.out_dir, "judged.jsonl")
    with open(src, encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]

    result = aggregate(rows, cfg)
    os.makedirs(args.out_dir, exist_ok=True)

    json_path = os.path.join(args.out_dir, "claims_report.json")
    markdown_path = os.path.join(args.out_dir, "claims_report.md")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    with open(markdown_path, "w", encoding="utf-8") as handle:
        handle.write(render_markdown(result))

    print(
        "参与聚合 %d / 输入 %d；缺 claim_text %d；观点 %d；one_off %d"
        % (
            result["totals"]["used"],
            result["totals"]["input_rows"],
            result["missing_claim_text"],
            len(result["opinions"]),
            len(result["one_off"]),
        )
    )


if __name__ == "__main__":
    main()
