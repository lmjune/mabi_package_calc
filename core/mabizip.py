# -*- coding: utf-8 -*-
"""
mabi.zip 거래내역 검색 링크 만들기 (결과는 mabi.zip 에서 확인)

주소 형식 (mabi.zip "검색 조건 URL 복사"로 확인):
  https://mabi.zip/auction-history?q={"itemName": "...", "itemCategory": "...",
        "optionFilters": {"세공 옵션": [{"name": "유효 사거리", "gte": "20"}, ...],
                          "에르그": {"type": "S"}}}
옵션 이름은 정확한 이름이어야 해요.
"""
import json
from urllib.parse import urlencode

BASE = "https://mabi.zip/auction-history"

# 넥슨 API 경매장 카테고리 (자동완성용)
CATEGORIES = [
    "개조석", "검", "경갑옷", "기타", "기타 소모품", "기타 스크롤", "기타 장비", "기타 재료", "꼬리", "날개",
    "낭만농장/달빛섬", "너클", "던전 통행증", "도끼", "도면", "둔기", "듀얼건", "랜스", "로브", "마기그래프",
    "마기그래프 도안", "마도서", "마리오네트", "마법가루", "마비노벨", "마족 스크롤", "말풍선 스티커",
    "매직 크래프트", "모자/가발", "방패", "변신 메달", "보석", "분양 메달", "불타래", "뷰티 쿠폰", "생활 도구",
    "석궁", "수리검", "스케치", "스태프", "신발", "실린더", "아틀라틀", "악기", "알반 훈련석", "액세서리",
    "양손 장비", "얼굴 장식", "에이도스", "에코스톤", "염색 앰플", "오브", "옷본", "원거리 소모품", "원드",
    "음식", "의자/사물", "인챈트 스크롤", "장갑", "제련/블랙스미스", "제스처", "주머니", "중갑옷", "책",
    "천옷", "천옷/방직", "체인 블레이드", "토템", "팔리아스 유물", "퍼퓸", "페이지", "포션", "피니 펫",
    "핀즈비즈", "한손 장비", "핸들", "허브", "활", "힐웬 공학",
]


def history_url(item_name=None, category=None, reforge=None, erg_type=None):
    """
    reforge: [(옵션이름, 이상 또는 None, 이하 또는 None), ...] 최대 3개
    """
    q = {}
    if item_name:
        q["itemName"] = item_name
    if category:
        q["itemCategory"] = category
    filters = {}
    if reforge:
        rows = []
        for name, gte, lte in reforge[:3]:
            row = {"name": name}
            if gte is not None:
                row["gte"] = str(gte)
            if lte is not None:
                row["lte"] = str(lte)
            rows.append(row)
        rows += [{"name": ""}] * (3 - len(rows))      # mabi.zip 화면처럼 칸 3개를 맞춰서 보냄
        filters["세공 옵션"] = rows
    if erg_type:
        filters["에르그"] = {"type": erg_type}
    if filters:
        q["optionFilters"] = filters
    if not q:
        return BASE
    return BASE + "?" + urlencode({"q": json.dumps(q, ensure_ascii=False, separators=(",", ":"))})


def category_matches(text, limit=25):
    t = (text or "").replace(" ", "")
    hits = [c for c in CATEGORIES if t in c.replace(" ", "")]
    hits.sort(key=lambda c: (not c.replace(" ", "").startswith(t), len(c)))
    return hits[:limit]
