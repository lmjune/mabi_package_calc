# -*- coding: utf-8 -*-
"""
넥슨 경매장 API 조회 + 공유 캐시 + 합산/패키지 계산.

- 같은 아이템 조회는 CACHE_TTL_SECONDS 동안 모든 사용자가 결과를 같이 씀
- 여러 명이 동시에 같은 아이템을 조회해도 API는 한 번만 호출(아이템별 잠금)
- 초당 5건 제한을 넘지 않도록 호출 간격을 강제
- 오늘(KST) 호출 수를 세고, 하루 한도 직전에는 새 조회를 막음
"""
import datetime as dt
import logging
import re
import threading
import time
from dataclasses import dataclass, field

import requests

import settings

log = logging.getLogger("mabi-api")

BASE_URL = "https://open.api.nexon.com/mabinogi/v1/auction"
MIN_INTERVAL = 0.22        # 초당 약 4.5건
MAX_RETRY = 5
KST = dt.timezone(dt.timedelta(hours=9))


class QuotaExceeded(RuntimeError):
    pass


class ApiError(RuntimeError):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


# ============================== 저수준 호출 ==============================
class _Budget:
    """호출 간격 + 일일 호출 수 관리 (스레드 안전)"""

    def __init__(self):
        self._lock = threading.Lock()
        self._last = 0.0
        self._day = None
        self.count = 0

    def _today(self):
        return dt.datetime.now(KST).date()

    def acquire(self):
        with self._lock:
            today = self._today()
            if today != self._day:
                self._day, self.count = today, 0
            limit = settings.DAILY_CALL_LIMIT - settings.DAILY_CALL_RESERVE
            if self.count >= limit:
                raise QuotaExceeded(
                    f"오늘 API 호출 한도에 거의 다 왔어요 ({self.count:,}/{settings.DAILY_CALL_LIMIT:,}). "
                    "내일 다시 해주세요.")
            wait = self._last + MIN_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            self.count += 1

    def calls_today(self):
        with self._lock:
            return self.count if self._day == self._today() else 0


budget = _Budget()


def _get(api_key, path, params):
    for attempt in range(MAX_RETRY):
        budget.acquire()
        r = requests.get(f"{BASE_URL}/{path}", params=params, timeout=15,
                         headers={"x-nxopen-api-key": api_key})
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500):
            time.sleep(2 ** attempt)
            continue
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {"message": r.text}
        log.warning("넥슨 API %s %s → %s %s", path, params, r.status_code, err)
        raise ApiError(f"API 오류 {r.status_code}: {err.get('name')} {err.get('message')}", err.get("name"))
    raise ApiError("요청이 너무 많아 재시도 횟수를 초과했어요. 잠시 후 다시 해주세요.")


def _fetch_all(api_key, path, list_key, item_name):
    results, cursor = [], ""
    while True:
        params = {"item_name": item_name}
        if cursor:
            params["cursor"] = cursor
        data = _get(api_key, path, params)
        results.extend(data.get(list_key) or [])
        cursor = data.get("next_cursor")
        if not cursor:
            remember_names(x.get("item_name") for x in results)
            return [x for x in results if x.get("item_name") == item_name]


# ============================== 아이템 이름 사전 ==============================
# 조회하면서 본 아이템 이름을 모아둬요. 자동완성·부분 검색에 써요 (API 호출 없이).
KNOWN_NAMES = set()
_names_lock = threading.Lock()


def remember_names(names):
    with _names_lock:
        KNOWN_NAMES.update(n for n in names if n)


def _squash(text):
    return re.sub(r"\s+", "", text or "")


def local_matches(text, limit=25):
    """공백 무시 부분 일치 (예: '숏소드' → '배틀 숏 소드', '기억 보석' → '기억의 보석'). 짧은 이름·앞부분 일치 우선"""
    q = _squash(text)
    if not q:
        return []
    words = [w for w in re.split(r"\s+", text.strip()) if w]

    def ok(n):
        sn = _squash(n)
        return q in sn or (len(words) > 1 and all(w in sn for w in words))   # '기억 보석' → '기억의 보석'

    with _names_lock:
        hits = [n for n in KNOWN_NAMES if ok(n)]
    hits.sort(key=lambda n: (not _squash(n).startswith(q), len(n), n))
    return hits[:limit]


# ============================== 공유 캐시 ==============================
_cache = {}                 # key -> (저장시각, 값)
_cache_lock = threading.Lock()
_key_locks = {}


def _cached(key, loader):
    with _cache_lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < settings.CACHE_TTL_SECONDS:
            return hit[1]
        klock = _key_locks.setdefault(key, threading.Lock())
    with klock:                          # 같은 키는 한 명만 조회, 나머지는 기다렸다가 결과 공유
        with _cache_lock:
            hit = _cache.get(key)
            if hit and time.time() - hit[0] < settings.CACHE_TTL_SECONDS:
                return hit[1]
        value = loader()
        with _cache_lock:
            _cache[key] = (time.time(), value)
        return value


def cache_size():
    now = time.time()
    with _cache_lock:
        return sum(1 for t, _ in _cache.values() if now - t < settings.CACHE_TTL_SECONDS)


def history(api_key, item_name):
    """최근 1시간 거래 내역 (공유 캐시)"""
    return _cached(("history", item_name),
                   lambda: _fetch_all(api_key, "history", "auction_history", item_name))


def listing(api_key, item_name):
    """현재 매물 (공유 캐시)"""
    return _cached(("list", item_name),
                   lambda: _fetch_all(api_key, "list", "auction_item", item_name))


def keyword_words(text):
    """검색어 → 넥슨 키워드 검색 형식 (한글·영문·숫자 단어, 최대 10개)"""
    return re.findall(r"[0-9A-Za-z가-힣]+", text or "")[:10]


def _keyword_fetch(api_key, words, max_pages=2):
    results, cursor = [], ""
    for _ in range(max_pages):            # 결과가 아주 많으면 앞쪽 1,000개까지만 (호출 한도 보호)
        params = {"keyword": ",".join(words)}
        if cursor:
            params["cursor"] = cursor
        data = _get(api_key, "keyword-search", params)
        results.extend(data.get("auction_item") or [])
        cursor = data.get("next_cursor")
        if not cursor:
            break
    remember_names(x.get("item_name") for x in results)
    return results


@dataclass
class Found:
    name: str
    list_min: int
    list_count: int


def keyword_search(api_key, text):
    """
    이름 일부로 현재 매물 검색 → 아이템별로 묶어서 [Found] (매물 많은 순)
    넥슨 규칙: 입력한 단어가 이름에 '단어 그대로' 모두 들어 있어야 찾아져요.
      '숏 소드' → '배틀 숏 소드' O  /  '모험가 소드' → '모험가의 플루트 숏 소드' X
    """
    words = keyword_words(text)
    if not words:
        return []
    try:
        rows = _cached(("keyword", tuple(words)), lambda: _keyword_fetch(api_key, words))
    except ApiError as e:
        if e.code != "OPENAPI00004":
            raise
        # 넥슨이 받아주지 않는 검색어(너무 짧은 단어 등) → 한 글자 단어를 빼고 한 번 더, 그래도 안 되면 '결과 없음'
        longer = [w for w in words if len(w) >= 2]
        if not longer or longer == words:
            return []
        try:
            rows = _cached(("keyword", tuple(longer)), lambda: _keyword_fetch(api_key, longer))
        except ApiError as e2:
            if e2.code != "OPENAPI00004":
                raise
            return []
    groups = {}
    for x in rows:
        g = groups.setdefault(x["item_name"], [])
        g.append(x["auction_price_per_unit"])
    found = [Found(n, min(p), len(p)) for n, p in groups.items()]
    found.sort(key=lambda f: (-f.list_count, f.name))
    return found


def smart_search(api_key, text, max_probes=3):
    """
    띄어쓰기가 달라도 찾기 (예: '브리레흐' → '브리 레흐의 정수', '브리 레흐 던전 통행증' …)
    1) 입력 그대로 키워드 검색
    2) 짧은 단어(끝 2~3글자, 각 단어, 앞 2글자)로도 넓게 검색해서, 공백을 무시하고 입력이 들어간 이름을 모두 모음
       (넥슨 검색은 단어가 정확히 같아야 해서 '레흐'로는 '레흐의'가 안 걸리기 때문)
    3) 봇이 전에 본 이름 중 맞는 것도 추가 (호출 없음)
    추가 호출은 최대 max_probes 번, 결과는 10분 캐시
    """
    target = _squash(text)
    words = keyword_words(text)
    merged = {f.name: f for f in keyword_search(api_key, text)}
    if text.strip() in merged:                      # 정확한 이름이면 더 찾을 필요 없음
        return list(merged.values())

    local = local_matches(text, 50)                  # 아는 이름(옵션 사전 색인 포함)에 있으면 추가 호출 없이
    if local:
        for n in local:
            merged.setdefault(n, Found(n, None, 0))
        found = list(merged.values())
        found.sort(key=lambda f: (f.list_min is None, -f.list_count, f.name))
        return found

    if len(target) >= 2:
        probes = []
        for p in [target[-2:], target[-3:], *sorted(words, key=len), target[:2]]:
            if len(p) >= 2 and p not in probes and p != " ".join(words):
                probes.append(p)
        for p in probes[:max_probes]:
            for f in keyword_search(api_key, p):
                if target in _squash(f.name) and f.name not in merged:
                    merged[f.name] = f

    for n in local_matches(text, 50):
        merged.setdefault(n, Found(n, None, 0))

    found = list(merged.values())
    found.sort(key=lambda f: (f.list_min is None, -f.list_count, f.name))
    return found


def category_listing(api_key, category, max_pages=4):
    """카테고리 현재 매물 (앞쪽 max_pages 페이지 = 최대 500×N개, 공유 캐시)"""
    def load():
        results, cursor = [], ""
        for _ in range(max_pages):
            params = {"auction_item_category": category}
            if cursor:
                params["cursor"] = cursor
            data = _get(api_key, "list", params)
            results.extend(data.get("auction_item") or [])
            cursor = data.get("next_cursor")
            if not cursor:
                break
        remember_names(x.get("item_name") for x in results)
        return results, bool(cursor)          # (매물, 더 남았는지)
    return _cached(("category", category, max_pages), load)


def full_listing(api_key, item_name):
    """아이템 현재 매물 (옵션 포함 원본)"""
    return listing(api_key, item_name)


# ============================== 가격 ==============================
def min_price(api_key, item_name, use_fallback=True):
    """(최저 개당가, 출처) / 없으면 (None, None)"""
    h = history(api_key, item_name)
    if h:
        return min(x["auction_price_per_unit"] for x in h), "최근 거래"
    if use_fallback:
        l = listing(api_key, item_name)
        if l:
            return min(x["auction_price_per_unit"] for x in l), "현재 매물"
    return None, None


@dataclass
class Quote:
    item_name: str
    trade_min: int = None
    trade_count: int = 0
    list_min: int = None
    list_count: int = 0


def quote(api_key, item_name):
    """단일 아이템 시세: 최근 거래 최저가 + 현재 매물 최저가"""
    h = history(api_key, item_name)
    l = listing(api_key, item_name)
    return Quote(
        item_name,
        min((x["auction_price_per_unit"] for x in h), default=None), len(h),
        min((x["auction_price_per_unit"] for x in l), default=None), len(l),
    )


# ============================== 목록 합산 ==============================
def parse_items(text):
    """'이름A | 이름B, 수량' 줄들 → ([(후보목록, 수량)], [오류메시지])"""
    items, errors = [], []
    for n, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line:
            names_part, count_part = line.rsplit(",", 1)
        else:
            names_part, count_part = line, "1"
        try:
            count = int(count_part.strip().replace("개", ""))
        except ValueError:
            errors.append(f"{n}번째 줄 수량이 숫자가 아니에요: {line}")
            continue
        names = [s.strip() for s in names_part.split("|") if s.strip()]
        if names:
            items.append((names, count))
    return items, errors


@dataclass
class PricedList:
    rows: list = field(default_factory=list)   # dict: 아이템, 수량, 개당가, 소계, 출처, 비교
    total: int = 0
    missing: list = field(default_factory=list)


def price_items(api_key, items, use_fallback=True, progress=None):
    """[(후보목록, 수량)] → PricedList. progress(i, n, label) 콜백 선택"""
    out = PricedList()
    for idx, (names, count) in enumerate(items):
        if progress:
            progress(idx, len(items), " | ".join(names))
        best, notes = None, []
        for name in names:
            price, src = min_price(api_key, name, use_fallback)
            notes.append(f"{name}: {price:,}" if price is not None else f"{name}: 없음")
            if price is not None and (best is None or price < best[0]):
                best = (price, name, src)
        if best is None:
            out.missing.append(" | ".join(names))
            out.rows.append({"아이템": " | ".join(names), "수량": count, "개당가": None,
                             "소계": None, "출처": "가격 없음", "비교": ""})
            continue
        price, name, src = best
        out.total += price * count
        out.rows.append({"아이템": name, "수량": count, "개당가": price, "소계": price * count,
                         "출처": src, "비교": " · ".join(notes) if len(names) > 1 else ""})
    return out


# ============================== 패키지 효율 ==============================
@dataclass
class PackageResult:
    name: str
    count: int
    price: int
    total_one: int          # 패키지 1개 구성품 경매장 합계
    mileage_pts: int        # 1개당 마일리지
    mileage_gold: int       # 1개당 마일리지 골드 환산
    net_one: int            # 1개 되팔면 (수수료 제외)
    net_one_m: int          # 마일리지 포함 (수수료 제외)
    won_per: int            # 1000숲당 원 (마일리지 제외)
    won_per_m: int          # 1000숲당 원 (마일리지 포함)
    market: int             # 비교 시세 (0=없음)
    mileage_rate: float = 0.0

    @property
    def pay_total(self):
        return self.price * self.count

    @property
    def net_total(self):
        return self.net_one * self.count

    @property
    def net_total_m(self):
        return self.net_one_m * self.count

    def verdict(self):
        """시세 비교 한 줄 (시세 없으면 None)"""
        best = self.won_per_m or self.won_per
        if not self.market or not best:
            return None
        if best < self.market:
            return f"마일리지 포함 기준으로 현금 시세보다 {1 - best / self.market:.1%} 싸게 골드를 얻는 셈이에요."
        return f"마일리지 포함해도 현금 시세보다 {best / self.market - 1:.1%} 비싸요."

    def summary_lines(self):
        rate_txt = f"{self.mileage_rate:g}%({self.mileage_gold // 10_000:,}만)"
        return (f"{self.name} {self.count:,}개 기준 수수료 제외: {self.net_total:,} 골드 / "
                f"마일리지 {rate_txt} 계산 수수료 제외: {self.net_total_m:,} 골드\n"
                f"1000숲에 얼마? 마일리지 제외 {self.won_per:,}원 / 마일리지 포함 {self.won_per_m:,}원")


def calc_package(name, total_one, price, count, mileage_rate, mileage_per_1000, market=0):
    fee = 1 - settings.FEE_RATE
    mileage_pts = round(price * mileage_rate / 100)
    mileage_gold = round(mileage_pts * settings.GOLD_UNIT / mileage_per_1000) if mileage_per_1000 else 0
    net_one = round(total_one * fee)
    net_one_m = round((total_one + mileage_gold) * fee)
    won_per = round(price * settings.GOLD_UNIT / net_one) if net_one else 0
    won_per_m = round(price * settings.GOLD_UNIT / net_one_m) if net_one_m else 0
    return PackageResult(name, count, price, total_one, mileage_pts, mileage_gold,
                         net_one, net_one_m, won_per, won_per_m, market, mileage_rate)


# ============================== 표시 ==============================
def kgold(n):
    """5,266,948,470 → '52억 6,694만'"""
    n = int(n)
    eok, man = divmod(abs(n) // 10_000, 10_000)
    sign = "-" if n < 0 else ""
    if eok:
        return f"{sign}{eok:,}억 {man:,}만" if man else f"{sign}{eok:,}억"
    if man:
        return f"{sign}{man:,}만"
    return f"{n:,}"
