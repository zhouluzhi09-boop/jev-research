# -*- coding: utf-8 -*-
"""小红书浏览器采集。

仅供个人研究使用：请遵守平台条款，不抓取个人信息，不用于数据售卖。
依赖已登录的浏览器会话；页面改版会导致采集失效。
"""
import argparse
import json
import os
import re

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
    m = re.match(r"^([\d.]+)\s*(万|w)?$", s)
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
    ap.add_argument("--user-data-dir", default=os.path.expanduser("~/.jev/xhs-profile"))
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    cards = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(a.user_data_dir, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(SEARCH.format(kw=a.keyword), wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        for _ in range(a.scrolls):
            page.evaluate("window.scrollBy(0, 4000)")
            page.wait_for_timeout(2000)

        seen = set()
        for c in page.evaluate(GRAB):
            href = c.get("href") or ""
            if not href or href in seen:
                continue
            seen.add(href)
            cards.append(c)

        rows = []
        search_url = page.url
        for i, c in enumerate(cards[: a.limit], 1):
            href = c["href"]
            detail = {}
            try:
                page.locator('section.note-item a[href="%s"]' % href).first.click(timeout=8000)
                page.wait_for_timeout(2200)
                detail = page.evaluate(DETAIL) or {}
            except Exception:
                detail = {}
            try:
                page.go_back()
                page.wait_for_timeout(1500)
            except Exception:
                page.goto(search_url, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)

            url = "https://www.xiaohongshu.com" + href if href.startswith("/") else href
            nums = detail.get("engage_numbers") or []
            rows.append({
                "id": href.rstrip("/").split("/")[-1] or None,
                "platform": "xiaohongshu",
                "title": c.get("title") or None,
                "text": c.get("cover_text") or None,
                "author": c.get("author") or None,
                "likes": parse_count(detail.get("likes")) or parse_count(c.get("likes")),
                "collects": parse_count(detail.get("collects")),
                "comments": parse_count(nums[2]) if len(nums) > 2 else None,
                "published_at": None,
                "url": url,
                "cover_text": c.get("cover_text") or None,
            })
            r = rows[-1]
            print(f"[{i}/{min(len(cards), a.limit)}] likes={r['likes']} collects={r['collects']} {r['title']}")

        ctx.close()

    with open(a.out, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    missing = sum(1 for r in rows if r["collects"] is None)
    print(f"写入 {len(rows)} 条 -> {a.out}；收藏缺失 {missing} 条（会进 pending_review）")


if __name__ == "__main__":
    main()
