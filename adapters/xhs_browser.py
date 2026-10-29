# -*- coding: utf-8 -*-
"""小红书浏览器采集（分层：先卡片，再按需进详情）。

仅供个人研究使用：请遵守平台条款，不抓取个人信息，不用于数据售卖。
依赖已登录的浏览器会话；页面改版会导致采集失效。

分层策略：
1. 只抓搜索卡片（标题 / 作者 / 点赞 / 链接），通常 10-20 秒。
2. 仅对「点赞已达门槛」的卡片打开详情读收藏，最多 --detail-limit 条。
3. 点赞未达门槛的卡片不进详情，直接交给 select 的 gate_metric 淘汰。
"""
import argparse
import json
import os
import re
import time

from playwright.sync_api import sync_playwright

SEARCH = ("https://www.xiaohongshu.com/search_result?keyword={kw}"
          "&source=web_search_result_notes&sort=time_descending")

GRAB = """() => Array.from(document.querySelectorAll('section.note-item')).map(el => {
  const a = el.querySelector('a.cover, a[href*="/explore/"]');
  const t = el.querySelector('.footer .title, .title span, .title');
  const au = el.querySelector('.author .name, .author-wrapper .name, .name');
  const lk = el.querySelector('.like-wrapper .count, .count');
  const img = el.querySelector('img');
  return {
    title: (t?.textContent || img?.alt || '').trim(),
    author: (au?.textContent || '').trim(),
    likes: (lk?.textContent || '').trim(),
    href: a?.getAttribute('href') || '',
    cover_text: (img?.alt || '').trim()
  };
})"""

DETAIL = r"""() => {
  const pick = (s) => {
    const e = document.querySelector(s);
    return e ? (e.textContent || '').trim() : null;
  };
  const bar = document.querySelector('.engage-bar');
  const nums = bar ? ((bar.innerText || '').match(/\d+(?:\.\d+)?(?:\u4e07|w)?/g) || []) : [];
  return {
    likes: pick('.like-wrapper .count'),
    collects: pick('.collect-wrapper .count'),
    engage_numbers: nums.slice(0, 5)
  };
}"""


def parse_count(s):
    """把 1.2万 / 3200 解析成整数；无法解析返回 None。"""
    if not s:
        return None
    s = str(s).strip()
    if s in ("赞", "收藏", "评论", ""):
        return None
    m = re.match(r"^([\d.]+)\s*(\u4e07|w)?$", s)
    if not m:
        return None
    v = float(m.group(1))
    if m.group(2):
        v *= 10000
    return int(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyword", required=True)
    ap.add_argument("--scrolls", type=int, default=3)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--detail-limit", type=int, default=15,
                    help="最多打开多少条详情页读收藏")
    ap.add_argument("--min-likes-for-detail", type=int, default=500,
                    help="点赞不到这个数的卡片不打开详情")
    ap.add_argument("--user-data-dir", default=os.path.expanduser("~/.jev/xhs-profile"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    t0 = time.time()

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(a.user_data_dir, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(SEARCH.format(kw=a.keyword), wait_until="domcontentloaded")
        page.wait_for_selector("section.note-item", timeout=15000)
        page.wait_for_timeout(1200)

        for _ in range(a.scrolls):
            page.evaluate("window.scrollBy(0, 4000)")
            page.wait_for_timeout(1500)

        seen, cards = set(), []
        for c in page.evaluate(GRAB):
            href = c.get("href") or ""
            if not href or href in seen:
                continue
            seen.add(href)
            cards.append(c)

        print(f"卡片 {len(cards)} 条，耗时 {time.time() - t0:.0f}s")

        candidates = [c for c in cards[: a.limit]
                      if (parse_count(c.get("likes")) or 0) >= a.min_likes_for_detail]
        candidates = candidates[: a.detail_limit]
        print(f"点赞达标 {len(candidates)} 条，进入详情采集")

        detail_map = {}
        search_url = page.url
        for i, c in enumerate(candidates, 1):
            href = c["href"]
            try:
                page.locator('section.note-item a[href="%s"]' % href).first.click(timeout=6000)
                page.wait_for_selector(".collect-wrapper .count", timeout=6000)
                detail_map[href] = page.evaluate(DETAIL) or {}
            except Exception:
                detail_map[href] = {}
            try:
                page.go_back()
                page.wait_for_selector("section.note-item", timeout=8000)
                page.wait_for_timeout(400)
            except Exception:
                page.goto(search_url, wait_until="domcontentloaded")
                page.wait_for_selector("section.note-item", timeout=10000)
            print(f"  详情 [{i}/{len(candidates)}] {time.time() - t0:.0f}s")

        rows = []
        for c in cards[: a.limit]:
            href = c["href"]
            d = detail_map.get(href, {})
            nums = d.get("engage_numbers") or []
            url = "https://www.xiaohongshu.com" + href if href.startswith("/") else href
            rows.append({
                "id": href.rstrip("/").split("/")[-1] or None,
                "platform": "xiaohongshu",
                "title": c.get("title") or None,
                "text": c.get("cover_text") or None,
                "author": c.get("author") or None,
                "likes": parse_count(d.get("likes")) or parse_count(c.get("likes")),
                "collects": parse_count(d.get("collects")),
                "comments": parse_count(nums[2]) if len(nums) > 2 else None,
                "published_at": None,
                "url": url,
                "cover_text": c.get("cover_text") or None,
            })

        ctx.close()

    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    no_detail = sum(1 for r in rows if r["collects"] is None)
    print(f"写入 {len(rows)} 条 -> {a.out}；未进详情 {no_detail} 条；总耗时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
