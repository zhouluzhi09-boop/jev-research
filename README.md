# jev-research

> 不是帮你抓，是帮你判。

把「扫话题 → 找对标/选题 → 判价值」做成可复现的流程：采集只负责拿数据，判断标准写死在契约里，代码算数字，LLM 只写解读。

当前版本只支持小红书（浏览器采集，需要自己登录一次）。X 适配器不在本仓库。

## 安装

```bash
pip install -r requirements.txt
playwright install chromium
```

## 快速开始

```bash
# 1. 采集（首次会打开浏览器，请手动登录小红书）
python adapters/xhs_browser.py --keyword "AI" --scrolls 3 --limit 30 --out runs/ai/notes.jsonl

# 2. 判断（调用 Jev，需要 OPENROUTER_API_KEY）
python engine/judge.py runs/ai/notes.jsonl --config profiles/public-xhs.json --out-dir runs/ai

# 3. 筛选
python engine/select_topics.py --config profiles/public-xhs.json --out-dir runs/ai --top 20

# 4. 写报告：按 templates/ 下的模板
```

## v2 立场分析

v1 只判内容质量，不判立场；v2 在同一份 `judged.jsonl` 上做舆论热点立场聚合，回答「哪一方占优」，但必须拆成三个口径分别报：

| 口径 | 算法 |
|---|---|
| 条数占比 `count_share` | 各立场条数 / 有效条数 |
| 互动加权占比 `weight_share` | 各立场 `likes + comments` 之和 / 总互动 |
| 头部分布 `top_share` | 按互动降序取 Top N（默认 50）的立场分布 |

口径细节：

- `stance == irrelevant`、缺失 stance 的条目不参与统计。
- `stance_confidence < confidence_min`（默认 5）单独进 `low_confidence`，不计入主口径。
- 同一 `author` 出现超过 `author_cap`（默认 5）条时只计 1 条，并列入 `suspect_authors`。

```bash
python engine/stance.py --config profiles/stance-xhs.json --out-dir runs/<事件>/
```

产出 `stance_report.json` 与 `stance_report.md`。结论只写「声量领先方 / 互动领先方 / 头部领先方」，三个口径不一致时明确标注「三个口径结论不一致」；报告必须带一句：

> 本结论只代表该平台该时间窗内可见样本，不代表全网民意。

## v2.1 双链路

v2 把中/土/第三方混在一个 stance 引擎里，方法不对。v2.1 拆成两条互不合并的链路：

- **A 链路（第三方）**：只采英语推文，回答「外部世界怎么看」。
- **B 链路（双方主张）**：中文 / 土耳其语各自的高流量主张，回答「他们各自在说什么」。

```bash
# A 链路：只采英语（profiles/thirdparty-en.json 中 quota.zh = 0）
python engine/thirdparty.py --config profiles/thirdparty-en.json --out-dir runs/<事件>/

# B 链路：中文 + 土耳其语（土耳其语放 en 桶）
python engine/claims.py --config profiles/claims-zh-tr.json --out-dir runs/<事件>/
```

产出 `thirdparty_report.json/.md` 与 `claims_report.json/.md`。两条链路的结论**不许合并**：

- 有效样本 < 50 条时，A 链路只报分布，`lean_band = unknown`。
- 领先方 ≥65% 为 `clear`，55%-65% 为 `slight`，<55% 为 `none`（无明显倾向）。
- 领先方 Top1 帖子互动占该立场总互动 ≥40% 时标记 `single_post_driven`。
- B 链路中同一 `claim_text` 至少出现 2 次才算「观点」，否则计入 `one_off`。

## 判定契约

内容四维全部 ≥7 才算有价值：

| 维度 | 判什么 |
|---|---|
| `information_density` | 有没有具体信息（数据、步骤、案例） |
| `copyability` | 读者能不能照着做 |
| `structure_clarity` | 能不能拆出钩子/主体/收尾 |
| `differentiation` | 形式或角度是否罕见 |

数据门槛由代码判：点赞 ≥ 500，收藏/点赞 ≥ 0.15。数据缺失标 `unverifiable`，进 `pending_review.json`，不淘汰。

## 产出

- `shortlist.json`：入选清单
- `shortlist_rejected.json`：淘汰 + 原因
- `pending_review.json`：数据缺失待人工
- `报告.md` / `噪声.md`：由 LLM 依据 JSON 写

## 自定义

复制 `profiles/public-xhs.json` 改关键词、阈值和权重即可。四维题目也可替换，但「全维 ≥7」的判定结构不要改。

## 已知限制

- 依赖页面结构，小红书改版会导致采集失效。
- 收藏数需要打开详情页读取，速度较慢，且部分页面可能读不到。
- 详情页必须从搜索结果点击进入；直接访问笔记 URL 会返回 404（缺少 xsec_token）。
- 性能参考：脚本采集 30 条约 1 分钟；用 agent 直接操作浏览器约 10 分钟只能拿 20 张卡片，请优先用脚本。
- 不支持自动登录，首次需人工扫码。

## 免责声明

仅供个人研究使用。请遵守平台条款，不抓取个人信息，不用于数据售卖。

## License

MIT
