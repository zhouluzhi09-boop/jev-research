---
name: jev-research
description: 小红书话题调研——按写死的判定契约筛出「有价值」的笔记，产出对标清单与噪声分析。触发词：调研、扫话题、找对标、找选题、内容分析。
---

# Jev Research（小红书）

> 不是帮你抓，是帮你判。抓取是商品，判定标准才是壁垒。

## 判定契约（写死，不可用总分替代）

一条笔记算「有价值」，必须同时满足：

| 维度 | 判什么 | 过线 |
|---|---|---|
| `information_density` | 有没有具体信息（数据、步骤、案例） | ≥7 |
| `copyability` | 读者能不能照着做 | ≥7 |
| `structure_clarity` | 能不能拆出钩子/主体/收尾，主体有无编号 | ≥7 |
| `differentiation` | 形式或角度是否罕见 | ≥7 |

数据门槛由代码判，不交给模型：

- `likes ≥ metrics.min_likes`（默认 500）
- `collects / likes ≥ metrics.min_collect_ratio`（默认 0.15）
- 任一指标缺失 → 标 `unverifiable`，进 `pending_review.json`，**不淘汰**

公开版不做受众匹配、主题限制、合规否决。

## 入口分流

| 档位 | 用户表现 | 动作 |
|---|---|---|
| 明确 | 给了话题或关键词 | 直接五问，出 profile |
| 有方向 | 只有大方向 | 在该方向扩 5 个候选话题，等用户选序号 |
| 没方向 | 「不知道写什么」 | 跨方向给 5-8 个候选，等用户选序号 |

候选写入 `00-Inbox/话题候选_<日期>.md`；用户选定后才生成 profile。

## 五问 intake

1. 扫什么话题、什么关键词？
2. 找什么（选题 / 对标 / 观点）？
3. 什么算噪声（黑名单词、最低点赞）？
4. 什么算有价值（四维是否都要 ≥7，还是放宽某一维）？
5. 跑多少条（采集上限、详情页上限、最终取几条）？

答案映射到 `profiles/<name>.json`。

## 四步流程

```bash
python adapters/xhs_browser.py --keyword "AI" --scrolls 3 --limit 30 --out runs/ai/notes.jsonl
python engine/judge.py runs/ai/notes.jsonl --config profiles/public-xhs.json --out-dir runs/ai
python engine/select_topics.py --config profiles/public-xhs.json --out-dir runs/ai --top 20
# 第 4 步：按 templates/ 写 报告.md 与 噪声.md
```

## 采集方式：脚本优先，agent 兜底

| 方式 | 速度 | 说明 |
|---|---|---|
| `adapters/xhs_browser.py`（Playwright 脚本） | 30 条 / 约 1 分钟 | 默认路径 |
| agent 直接驱动浏览器 | 20 条 / 约 10 分钟（仅卡片） | 只在脚本跑不起来时用 |

实测：agent 采集有九成时间花在模型回合延迟上，真正的采集动作只要半分钟。进详情读收藏更慢，10 分钟大约只能覆盖 5-8 条。

**结论**：采集交给脚本，模型只负责 intake、判断和写报告。agent 采集仅作应急兜底，不进入推荐路径。

## 无合格样本时：降级入选

如果没有任何一条通过四维闸门，不要输出空报告。按 `fallback` 配置（默认 `min_items: 3`、`max_items: 5`）从落选者里按四维均分取前几条，写进 `shortlist_fallback.json`，并标记 `fallback: true`、`reason: fallback_low_score`、`failed`（哪几维没过）。

报告中必须单独说明：这是降级推荐，不是合格样本，并写清每条差在哪一维。把降级当正常入选写，等于放弃契约。

## 维度是正交的

`copyability`（可复制）和 `emotional_resonance`（情绪共鸣）是两把不同的尺子：一条内容可以既可复制又有共鸣，也可以只有其一。两个维度都打分，由 `gate.require` 决定这次用哪几个，不要互相替代。

## 产出契约

```
runs/<话题>_<日期>/
├── notes.jsonl              # 采集原始（归一化）
├── judged.jsonl             # 四维打分
├── rejected.jsonl           # L0 拒（低赞、黑名单）
├── shortlist.json           # 四维全过 + 数据达标
├── shortlist_rejected.json  # 淘汰 + 原因（gate_metric / gate_require）
├── pending_review.json      # 数据缺失，待人工
├── 报告.md
└── 噪声.md
```

规则：报告里的数字必须能在 JSON 里逐项对上，不许手填。

## 免责声明

仅供个人研究。请遵守平台条款，不抓取个人信息，不用于数据售卖。页面结构变更会导致采集失效。
