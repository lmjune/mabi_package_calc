# -*- coding: utf-8 -*-
"""
넥슨 경매장 API 조회 + 공유 캐시 + 합산/패키지 계산.

- 같은 아이템 조회는 CACHE_TTL_SECONDS 동안 모든 사용자가 결과를 같이 씀
- 여러 명이 동시에 같은 아이템을 조회해도 API는 한 번만 호출(아이템별 잠금)
- 초당 5건 제한을 넘지 않도록 호출 간격을 강제
- 오늘(KST) 호출 수를 세고, 하루 한도 직전에는 새 조회를 막음
"""
import datetime as dt
import threading
import time
from dataclasses import dataclass, field

import requests

import settings

BASE_URL = "https://open.api.nexon.com/mabinogi/v1/auction"
MIN_INTERVAL = 0.22        # 초당 약 4.5건
MAX_RETRY = 5
KST = dt.timezone(dt.timedelta(hours=9))


class QuotaExceeded(RuntimeError):
    pass


class ApiError(RuntimeError):
    pass


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
        raise ApiError(f"API 오류 {r.status_code}: {err.get('name')} {err.get('message')}")
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
            return [x for x in results if x.get("item_name") == item_name]


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
