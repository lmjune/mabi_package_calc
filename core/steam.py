# -*- coding: utf-8 -*-
"""
스팀 할인 목록 — 스팀 상점 검색 결과(할인 중만)를 가져와요.
공식 문서가 있는 API가 아니라 상점 웹페이지가 쓰는 주소라서, 스팀이 구조를 바꾸면 고쳐야 할 수 있어요.
"""
import html
import re
import threading
import time
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

SEARCH_URL = "https://store.steampowered.com/search/results/"
HEADERS = {"User-Agent": "Mozilla/5.0 (mabi guild bot)", "Accept-Language": "ko-KR,ko;q=0.9"}
CACHE_TTL = 1800           # 30분 동안 같은 조회 결과를 모두가 같이 씀

SORTS = {                  # 보여줄 이름 → 검색 파라미터
    "인기순": {"filter": "topsellers"},
    "평가순": {"sort_by": "Reviews_DESC"},
    "낮은 가격순": {"sort_by": "Price_ASC"},
    "최신순": {"sort_by": "Released_DESC"},
}


@dataclass
class Deal:
    appid: str
    name: str
    url: str
    discount: int          # 할인율 %
    original: str          # "₩ 54,900"
    final: str             # "₩ 27,450"
    final_value: int       # 27450
    review: str            # "매우 긍정적 94%" (없으면 "")
    image: str


def _parse(results_html):
    soup = BeautifulSoup(results_html, "html.parser")
    deals = []
    for a in soup.select("a.search_result_row"):
        block = a.select_one(".discount_block")
        title = a.select_one(".title")
        if not block or not title:
            continue
        try:
            discount = int(block.get("data-discount") or 0)
        except ValueError:
            discount = 0
        if discount <= 0:
            continue
        orig = a.select_one(".discount_original_price")
        final = a.select_one(".discount_final_price")
        try:
            final_value = int(block.get("data-price-final") or 0) // 100
        except ValueError:
            final_value = 0
        review = ""
        rv = a.select_one(".search_review_summary")
        if rv and rv.get("data-tooltip-html"):
            tip = html.unescape(rv["data-tooltip-html"])
            label = re.split(r"<br\s*/?>", tip)[0].strip()
            pct = re.search(r"(\d+)%", tip)
            review = f"{label} {pct.group(1)}%" if pct else label
        img = a.select_one(".search_capsule img")
        deals.append(Deal(
            appid=a.get("data-ds-appid") or a.get("data-ds-packageid") or a.get("data-ds-bundleid") or "",
            name=title.get_text(strip=True),
            url=(a.get("href") or "").split("?")[0],
            discount=discount,
            original=orig.get_text(strip=True) if orig else "",
            final=final.get_text(strip=True) if final else "",
            final_value=final_value,
            review=review,
            image=img.get("src", "") if img else "",
        ))
    return deals


_cache, _lock = {}, threading.Lock()


def fetch_deals(sort="인기순", start=0, count=25, keyword=""):
    """할인 중인 게임 목록 (list[Deal], 전체 개수)"""
    key = (sort, start, count, keyword)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
    params = {"specials": 1, "infinite": 1, "cc": "kr", "l": "korean",
              "start": start, "count": count, **SORTS.get(sort, {})}
    if keyword:
        params["term"] = keyword
    r = requests.get(SEARCH_URL, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()
    value = (_parse(data.get("results_html") or ""), int(data.get("total_count") or 0))
    with _lock:
        _cache[key] = (time.time(), value)
    return value