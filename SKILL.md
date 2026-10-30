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

`copyability`（可复制）和 `emotional_resonance`（情绪共鸣）是两把不同的尺子：一条内容可以既可复制又有共鸣，也可以只有其一。两个维度都打分、都参与加权排序，不要互相替代。默认只把前四维写进 `gate.require`；情绪共鸣不作硬门槛，否则会把「干货但冷」的内容全部挡掉。做娱乐向时，再按 profile 单独把它加成门槛。

## v2 立场分析

v1 只判内容质量（四维 + 数据门槛），不判立场。v2 在 `judged.jsonl` 上追加三个判定字段：

| 字段 | 类型 | 取值 |
|---|---|---|
| `stance` | choice | `pro_cn` / `pro_tr` / `neutral` / `spectator` / `irrelevant` |
| `stance_intensity` | score 0-9 | 立场表达强度 |
| `stance_confidence` | score 0-9 | 判断把握 |

运行：

```bash
python engine/stance.py --config profiles/stance-xhs.json --out-dir runs/<事件>/
```

### 三个口径，必须分开报

| 口径 | 算法 | 回答什么 |
|---|---|---|
| 声量（`count_share`） | 各立场条数 / 有效条数 | 哪一方发帖多 |
| 互动（`weight_share`） | 各立场 `likes + comments` 之和 / 总互动 | 哪一方被更多人看见 |
| 头部（`top_share`） | 按互动降序取 Top N（默认 50）的立场分布 | 头部内容偏向哪一方 |

三条规则：

1. `stance` 缺失或等于 `irrelevant` 的条目不参与任何口径。
2. `stance_confidence < confidence_min`（默认 5）的条目单独进 `low_confidence`，不计入主口径。
3. 同一 `author` 出现超过 `author_cap`（默认 5）条时只计 1 条，折叠的账号与条数写入 `suspect_authors`。

### 结论写法（硬约束）

- 只能写「声量领先方 / 互动领先方 / 头部领先方」。
- 三个口径不一致时，必须明确写「三个口径结论不一致」，分别列出三个领先方。
- **不要写「谁赢了」**，也不要把三个口径合并成一个胜负判断。
- 报告必须带一句：本结论只代表该平台该时间窗内可见样本，不代表全网民意。

产出 `stance_report.json`（可逐项核对）与 `stance_report.md`（给人看）。报告里的每个数字都必须来自 `aggregate()` 的计算结果，不许手填或估算。

## v2.1 双链路（A 第三方 / B 双方主张）

v2 把中立、土耳其、第三方混在一个 stance 引擎里算，方法错了。v2.1 拆成两条独立链路，**结论不许合并**。

### A 链路：英语第三方视角

```bash
python engine/thirdparty.py --config profiles/thirdparty-en.json --out-dir runs/<事件>/
```

- 只采英语推文（profile 中 `quota: {"zh": 0, "en": 200}`），回答「外部世界怎么看」。
- 判定字段：`third_party_lean`（`pro_cn` / `pro_tr` / `neutral` / `both_negative` / `irrelevant`）、`tone`（`mocking` / `serious` / `spectator`）、`stance_confidence`（0-9）。
- `both_negative` 单独成类，不得并入 `neutral`；`irrelevant` 与缺失 lean 不参与统计。
- 三个口径分开报：`count_share`、`weight_share`（likes + comments）、`top_share`（互动降序 Top 50）。
- 阈值：有效样本 **< 50 条**只报分布（`lean_band = unknown`，conclusion 固定为「样本不足，仅报分布」）；领先方 **≥65%** 为 `clear`，**55%-65%** 为 `slight`，**<55%** 为 `none`（写「无明显倾向」）。
- 单条驱动：领先方 Top1 帖子互动 ≥ 该立场总互动 **40%** 时置 `single_post_driven = true`，报告里点名该帖。
- 产出 `thirdparty_report.json` / `.md`；报告开头必须带免责声明。

### B 链路：中文 / 土耳其语双方主张

```bash
python engine/claims.py --config profiles/claims-zh-tr.json --out-dir runs/<事件>/
```

- 分语种采集：中文关键词放 `zh` 桶，土耳其语关键词放 `en` 桶（采集层只有这两个桶）。
- Jev 只做 `claim_type`（`history` / `genes` / `culture` / `economy` / `morality` / `mockery` / `other`）与 `claim_stance`（`pro_cn` / `pro_tr` / `neutral`）分类；一句话主张 `claim_text` 由外部 LLM 写入顶层字段。
- 缺 `claim_text` 或 `claim_type` 的条目不参与聚合，计入 `missing_claim_text`。
- 按 `(claim_stance, claim_type)` 分组；组内同一 `claim_text` **至少出现 2 次**才算「观点」，否则计入 `one_off`。
- 每组输出观点文本、帖子数、总互动、Top1 帖子 id/url；按 `pro_cn` / `pro_tr` 分两节，各节内按总互动降序取 Top 10。
- 产出 `claims_report.json` / `.md`。

### 三条硬约束

1. A 链路只采英文，B 链路分语种；不要把第三方样本混进双方主张。
2. 两条链路的结论不许合并、不许互相引用。
3. 五个阈值（50 条 / 55% / 65% / 40% / ≥2 条）只写在代码常量与 profile 的 `settings` 里，不在逻辑中散落硬编码。

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
