# jev-research

> 不是帮你抓，是帮你判。

把「扫话题 → 找选题 → 判价值」做成可复现的流程：采集只负责拿数据，判断标准写死在契约里，代码算数字，LLM 只写解读。

默认支持小红书（浏览器采集，需自己登录）。X 适配器不在此仓库。

## 快速开始

```bash
pip install -r requirements.txt
playwright install chromium
python adapters/xhs_browser.py --keyword "AI" --scrolls 3 --out runs/ai/tweets.jsonl
python engine/judge.py runs/ai/tweets.jsonl --config profiles/public-xhs.json --out-dir runs/ai
python engine/select_topics.py --config profiles/public-xhs.json --out-dir runs/ai
```

## 判定契约

内容四维全部 ≥7 才算有价值：

| 维度 | 判什么 |
|---|---|
| information_density | 有没有具体信息（数据、步骤、案例） |
| copyability | 读者能不能照着做 |
| structure_clarity | 能不能拆出钩子/主体/收尾 |
| differentiation | 形式或角度是否罕见 |

数据门槛由代码判：点赞 ≥ 500，收藏/点赞 ≥ 0.15。数据缺失标 `unverifiable`，进 `pending_review.json`，不淘汰。

## 免责声明

仅供个人研究使用。请遵守平台条款，不抓取个人信息，不用于数据售卖。页面结构变更会导致采集失效。
