# -*- coding: utf-8 -*-
"""v2.1 A 链路：只分析英语推文，回答「外部第三方世界怎么看」。

判定字段（题目名写死，选项由 profile 定义）：
- third_party_lean   choice: pro_cn / pro_tr / neutral / both_negative / irrelevant
- tone               choice: mocking / serious / spectator
- stance_confidence  score 0-9

聚合只回答第三方视角，不与中文/土文主张（B 链路 engine/claims.py）合并。
三个口径（条数 / 互动 / 头部）必须分开报。

aggregate(rows, cfg) 是纯函数，不读写文件，便于测试。
"""
import argparse
import json
import os

# ---------------------------------------------------------------------------
# 阈值常量：所有门槛集中在这里，profile 可覆盖，但不要在逻辑里散落魔法数字。
# ---------------------------------------------------------------------------
CONFIDENCE_MIN = 5          # stance_confidence < 5 -> low_confidence，不计入
SAMPLE_MIN = 50             # 有效样本 < 50 -> 只报分布，不给倾向档位
CLEAR_THRESHOLD = 0.65      # 领先方 >= 65% -> clear
SLIGHT_THRESHOLD = 0.55     # 55% <= 领先方 < 65% -> slight；< 55% -> none
SINGLE_POST_SHARE = 0.40    # 领先方 Top1 帖子互动 / 该立场总互动 >= 40% -> 单条驱动
TOP_N = 50                  # 头部口径默认取互动降序前 N 条
EXCLUDE_LANGS = ("zh", "tr")  # 当事人语言，不计入第三方池

LEANS = ("pro_cn", "pro_tr", "neutral", "both_negative")
EXCLUDED_LEANS = ("irrelevant",)
TONES = ("mocking", "serious", "spectator")

DEFAULT_FIELDS = {
    "lean": "third_party_lean",
    "tone": "tone",
    "confidence": "stance_confidence",
}

DISCLAIMER = (
    "免责声明：本结论只代表该平台该时间窗内可见的多语种第三方样本（已剔除中文/土耳其语），"
    "不代表第三方世界或全网民意，也不能与中文/土文链路结论合并。"
)

LEAN_DISPLAY = {
    "pro_cn": "支持中国一方（pro_cn）",
    "pro_tr": "支持土耳其一方（pro_tr）",
    "neutral": "中立（neutral）",
    "both_negative": "双方皆负面（both_negative）",
}


def _num(value):
    """把缺失、空串或非数字的互动字段安全地转成 0。"""
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
        for key in ("choice", "value", "answer", "label", "option", "lean"):
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
        "confidence_min": float(settings.get("confidence_min", CONFIDENCE_MIN)),
        "sample_min": int(settings.get("sample_min", SAMPLE_MIN)),
        "top_n": int(settings.get("top_n", TOP_N)),
        "clear_threshold": float(
            settings.get("clear_threshold", CLEAR_THRESHOLD)
        ),
        "slight_threshold": float(
            settings.get("slight_threshold", SLIGHT_THRESHOLD)
        ),
        "single_post_share": float(
            settings.get("single_post_share", SINGLE_POST_SHARE)
        ),
        "exclude_langs": [
            str(x).lower()
            for x in settings.get("exclude_langs", list(EXCLUDE_LANGS))
        ],
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


def _brief(record):
    row = record["row"]
    return {
        "id": row.get("id"),
        "author": row.get("author"),
        "lean": record["lean"],
        "tone": record["tone"],
        "confidence": record["confidence"],
        "likes": row.get("likes"),
        "comments": row.get("comments", row.get("comment")),
        "interaction": record["interaction"],
        "url": row.get("url"),
    }


def _records(rows, fields, confidence_min, exclude_langs=()):
    """拆出有效样本、低置信度样本和各类排除计数。

    规则 1：只统计 lean 存在且 != irrelevant 的条目。
    规则 2：confidence < confidence_min 的条目进 low_confidence，不计入。
    """
    eligible, low = [], []
    excluded = {"missing_lean": 0, "irrelevant": 0, "invalid_lean": 0, "excluded_lang": 0}
    excluded_set = {str(x).lower() for x in (exclude_langs or ())}

    for index, row in enumerate(rows):
        lang = str(row.get("lang") or "").strip().lower()
        if lang and lang in excluded_set:
            excluded["excluded_lang"] += 1
            continue
        lean = _as_choice(_answer(row, fields["lean"]))
        if not lean:
            excluded["missing_lean"] += 1
            continue
        if lean in EXCLUDED_LEANS:
            excluded["irrelevant"] += 1
            continue
        if lean not in LEANS:
            excluded["invalid_lean"] += 1
            continue

        confidence = _as_score(_answer(row, fields["confidence"]))
        record = {
            "_index": index,
            "row": row,
            "lean": lean,
            "confidence": confidence,
            "tone": _as_choice(_answer(row, fields["tone"])),
            "interaction": _interaction(row),
            "_low": confidence is None or confidence < confidence_min,
        }
        eligible.append(record)
        if record["_low"]:
            low.append(record)

    effective = [record for record in eligible if not record["_low"]]
    return eligible, effective, low, excluded


def _leader(shares):
    """并列时按 LEANS 固定顺序取第一个，保证结果可复现。"""
    if not any(shares[lean] > 0 for lean in LEANS):
        return None
    return max(LEANS, key=lambda lean: (shares[lean], -LEANS.index(lean)))


def _band(share, settings):
    if share >= settings["clear_threshold"]:
        return "clear"
    if share >= settings["slight_threshold"]:
        return "slight"
    return "none"


def _conclusion(leader, share, band, effective, settings):
    if effective < settings["sample_min"]:
        return "样本不足，仅报分布"
    if leader is None or band == "none":
        return "无明显倾向"
    word = "明显领先" if band == "clear" else "小幅领先"
    return "外部第三方样本中，%s%s（声量占比 %.1f%%）。" % (
        LEAN_DISPLAY.get(leader, leader),
        word,
        share * 100,
    )


def _single_post_driven(effective, leader, settings):
    """领先方 Top1 帖子互动占该立场总互动 >= single_post_share 即命中。"""
    if leader is None:
        return False, None
    records = [record for record in effective if record["lean"] == leader]
    if not records:
        return False, None
    total = sum(record["interaction"] for record in records)
    top = max(records, key=lambda record: (record["interaction"], -record["_index"]))
    if total <= 0:
        return False, None
    driven = top["interaction"] / total >= settings["single_post_share"]
    return driven, top if driven else None


def aggregate(rows, cfg):
    """按三个口径聚合第三方立场，返回可直接 JSON 序列化的结构化结果。"""
    settings = _settings(cfg)
    fields = _fields(cfg)

    _eligible, effective, low, excluded = _records(
        rows, fields, settings["confidence_min"], settings["exclude_langs"]
    )

    counts = {lean: 0 for lean in LEANS}
    interactions = {lean: 0.0 for lean in LEANS}
    for record in effective:
        counts[record["lean"]] += 1
        interactions[record["lean"]] += record["interaction"]

    effective_count = len(effective)
    total_interaction = sum(interactions.values())

    count_share = {
        lean: (counts[lean] / effective_count if effective_count else 0.0)
        for lean in LEANS
    }
    weight_share = {
        lean: (interactions[lean] / total_interaction if total_interaction else 0.0)
        for lean in LEANS
    }

    # 头部口径：按互动降序；互动并列时保持输入顺序。
    ordered = sorted(
        effective, key=lambda record: (-record["interaction"], record["_index"])
    )
    top_records = ordered[: max(0, settings["top_n"])]
    top_counts = {lean: 0 for lean in LEANS}
    for record in top_records:
        top_counts[record["lean"]] += 1
    top_total = len(top_records)
    top_share = {
        lean: (top_counts[lean] / top_total if top_total else 0.0)
        for lean in LEANS
    }

    leaders = {
        "count": _leader(count_share),
        "weight": _leader(weight_share),
        "top": _leader(top_share),
    }
    consistent = len(set(leaders.values())) == 1

    # 倾向档位以声量口径（count_share）的领先方为准；这是本链路的固定口径。
    count_leader = leaders["count"]
    if effective_count < settings["sample_min"] or count_leader is None:
        lean_band = "unknown"
    else:
        lean_band = _band(count_share[count_leader], settings)

    driven, driven_post = _single_post_driven(
        effective, count_leader, settings
    )

    tone_counts = {tone: 0 for tone in TONES}
    tone_counts["unknown"] = 0
    for record in effective:
        tone = record["tone"]
        tone_counts[tone if tone in TONES else "unknown"] += 1

    leader_share = (
        count_share[count_leader] if count_leader is not None else 0.0
    )
    conclusion = _conclusion(
        count_leader, leader_share, lean_band, effective_count, settings
    )

    top_items = []
    for rank, record in enumerate(top_records, 1):
        item = _brief(record)
        item["rank"] = rank
        top_items.append(item)

    return {
        "source": cfg.get("source"),
        "platform": cfg.get("platform"),
        "settings": settings,
        "fields": fields,
        "totals": {
            "input_rows": len(rows),
            "eligible": len(effective) + len(low),
            "effective": effective_count,
            "low_confidence": len(low),
            "missing_lean": excluded["missing_lean"],
            "irrelevant": excluded["irrelevant"],
            "invalid_lean": excluded["invalid_lean"],
            "excluded_lang": excluded.get("excluded_lang", 0),
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
        "tone_counts": tone_counts,
        "leaders": leaders,
        "consistent": consistent,
        "lean_band": lean_band,
        "single_post_driven": driven,
        "single_post": _brief(driven_post) if driven_post else None,
        "conclusion": conclusion,
        "low_confidence": [_brief(record) for record in low],
        "top_items": top_items,
        "disclaimer": DISCLAIMER,
    }


def _pct(value):
    return "%.1f%%" % (value * 100)


def render_markdown(result):
    """把 aggregate 的结果渲染成报告；所有数字都直接来自 result。"""
    totals = result["totals"]
    lines = [
        "> " + result["disclaimer"],
        "",
        "# 第三方视角（多语种）立场分析",
        "",
        "## 结论",
        "",
        result["conclusion"],
        "",
    ]

    if result["lean_band"] != "unknown":
        lines.extend([
            "- 倾向档位：%s（以声量口径的领先方为准）" % result["lean_band"],
            "- 有效样本：%d（门槛 %d 条）"
            % (totals["effective"], result["settings"]["sample_min"]),
            "",
        ])
    else:
        lines.extend([
            "- 有效样本：%d，低于门槛 %d 条，只报分布，不给倾向档位。"
            % (totals["effective"], result["settings"]["sample_min"]),
            "",
        ])

    if not result["consistent"]:
        lines.extend([
            "三个口径给出的领先方不同，请分别解读，不要合并成单一结论。",
            "",
        ])

    if result["single_post_driven"] and result["single_post"]:
        post = result["single_post"]
        lines.extend([
            "**单条驱动**：%s 的 Top1 帖子（id=%s，互动 %s）占该立场总互动 "
            "%.1f%%，达到 %.0f%% 阈值，该立场结论主要由这一条驱动。"
            % (
                LEAN_DISPLAY.get(post["lean"], post["lean"]),
                post["id"],
                round(post["interaction"], 2),
                (post["interaction"] / result["interactions"][post["lean"]]) * 100
                if result["interactions"][post["lean"]]
                else 0.0,
                result["settings"]["single_post_share"] * 100,
            ),
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
    for lean in LEANS:
        lines.append(
            "| %s | %d | %s | %s | %s | %d | %s |"
            % (
                LEAN_DISPLAY[lean],
                result["counts"][lean],
                _pct(result["count_share"][lean]),
                round(result["interactions"][lean], 2),
                _pct(result["weight_share"][lean]),
                result["top_counts"][lean],
                _pct(result["top_share"][lean]),
            )
        )

    lines.extend([
        "",
        "领先方：声量口径 %s；互动口径 %s；头部口径 %s。"
        % (
            result["leaders"]["count"] or "无",
            result["leaders"]["weight"] or "无",
            result["leaders"]["top"] or "无",
        ),
        "",
        "## 数据口径",
        "",
        "- 输入条目：%d" % totals["input_rows"],
        "- 有效样本（高置信度）：%d" % totals["effective"],
        "- 低置信度（未计入）：%d" % totals["low_confidence"],
        "- irrelevant（未计入）：%d" % totals["irrelevant"],
        "- 缺失 third_party_lean（未计入）：%d" % totals["missing_lean"],
        "- 非法 third_party_lean（未计入）：%d" % totals["invalid_lean"],
        "",
        "## tone 分布（有效样本）",
        "",
        "| tone | 条数 |",
        "|---|---:|",
    ])
    for tone, count in result["tone_counts"].items():
        lines.append("| %s | %d |" % (tone, count))

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
                    item["lean"],
                    item["confidence"],
                    round(item["interaction"], 2),
                )
            )
    else:
        lines.append("无。")

    lines.extend(["", "## 头部内容（按互动降序）", ""])
    if result["top_items"]:
        lines.extend([
            "| 排名 | id | 账号 | 立场 | tone | 互动量 |",
            "|---:|---|---|---|---|---:|",
        ])
        for item in result["top_items"]:
            lines.append(
                "| %d | %s | %s | %s | %s | %s |"
                % (
                    item["rank"],
                    item["id"],
                    item["author"],
                    item["lean"],
                    item["tone"],
                    round(item["interaction"], 2),
                )
            )
    else:
        lines.append("无有效样本。")

    lines.extend(["", "---", "", result["disclaimer"], ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="v2.1 A 链路：英语第三方立场分析")
    parser.add_argument("--config", required=True, help="thirdparty profile 路径")
    parser.add_argument("--out-dir", required=True, help="包含 judged.jsonl 的运行目录")
    args = parser.parse_args()

    with open(args.config, encoding="utf-8") as handle:
        cfg = json.load(handle)

    src = os.path.join(args.out_dir, "judged.jsonl")
    with open(src, encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle if line.strip()]

    result = aggregate(rows, cfg)
    os.makedirs(args.out_dir, exist_ok=True)

    json_path = os.path.join(args.out_dir, "thirdparty_report.json")
    markdown_path = os.path.join(args.out_dir, "thirdparty_report.md")
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=1)
    with open(markdown_path, "w", encoding="utf-8") as handle:
        handle.write(render_markdown(result))

    print(
        "有效样本 %d / 输入 %d；置信度不足 %d；档位 %s；%s"
        % (
            result["totals"]["effective"],
            result["totals"]["input_rows"],
            result["totals"]["low_confidence"],
            result["lean_band"],
            result["conclusion"],
        )
    )


if __name__ == "__main__":
    main()
