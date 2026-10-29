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
- 不支持自动登录，首次需人工扫码。

## 免责声明

仅供个人研究使用。请遵守平台条款，不抓取个人信息，不用于数据售卖。

## License

MIT
