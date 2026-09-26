# -*- coding: utf-8 -*-
"""마비노기 경매장 최근 거래가 합산 - Streamlit 앱"""
import os
import time

import pandas as pd
import requests
import streamlit as st

# ============ 기본 아이템 목록 (여기를 고쳐서 GitHub에 다시 올리면 기본값이 바뀝니다) ============
# 한 줄에 하나:  아이템이름, 수량
# 둘 중 싼 것:   아이템A | 아이템B, 수량   (아이템 이름에 / 가 들어가는 게 있어서 | 로 구분)
DEFAULT_ITEMS = """\
찬란한 세공 도구, 80
기억의 보석, 80
반짝이 이름/채팅 지정 색상 변경 포션(30일), 5
간편한 망각의 비약, 20
환생의 비약, 20
인챈트 보호 포션, 2
보호의 6단계 푸른 개조석 | 보호의 6단계 붉은 개조석, 2
보호의 7단계 푸른 개조석 | 보호의 7단계 붉은 개조석, 2
특별 개조 전환 키트, 1
간편한 특별 개조 복구의 정수, 1
전용 해제 포션, 1
스크롤 전용 해제 포션, 2
특별한 유물 조각(1000%), 10
증폭된 스킬 수련 인장(50), 10
경매장 수수료 100% 할인 쿠폰, 3
인챈트 추출 보호 포션, 2
"""

FEE_RATE = 0.04            # 경매장 수수료 4%
MILEAGE = 4_000_000        # 마일리지 (골드)
PACKAGE_PRICE = 119_000    # 원
GOLD_UNIT = 10_000_000     # 1000숲 = 1,000만 골드
# ============================================================================================

BASE_URL = "https://open.api.nexon.com/mabinogi/v1/auction"
REQUEST_DELAY = 0.3
MAX_RETRY = 5


def get_api_key():
    try:
        key = st.secrets.get("NEXON_API_KEY")
    except Exception:  # secrets.toml 이 없을 때
        key = None
    return key or os.environ.get("NEXON_API_KEY")


def api_get(api_key, path, params):
    for attempt in range(MAX_RETRY):
        r = requests.get(f"{BASE_URL}/{path}", params=params, timeout=15,
                         headers={"x-nxopen-api-key": api_key})
        time.sleep(REQUEST_DELAY)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500):
            time.sleep(2 ** attempt)
            continue
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {"message": r.text}
        raise RuntimeError(f"API 오류 {r.status_code}: {err.get('name')} {err.get('message')}")
    raise RuntimeError("요청이 너무 많아 재시도 횟수를 초과했어요. 잠시 후 다시 해주세요.")


def fetch_all(api_key, path, list_key, item_name):
    results, cursor = [], ""
    while True:
        params = {"item_name": item_name}
        if cursor:
            params["cursor"] = cursor
        data = api_get(api_key, path, params)
        results.extend(data.get(list_key) or [])
        cursor = data.get("next_cursor")
        if not cursor:
            return results


@st.cache_data(ttl=300, show_spinner=False)  # 같은 아이템은 5분간 다시 조회하지 않음
def min_price(api_key, item_name, use_fallback):
    history = [h for h in fetch_all(api_key, "history", "auction_history", item_name)
               if h.get("item_name") == item_name]
    if history:
        return min(h["auction_price_per_unit"] for h in history), "최근 거래"
    if use_fallback:
        listing = [i for i in fetch_all(api_key, "list", "auction_item", item_name)
                   if i.get("item_name") == item_name]
        if listing:
            return min(i["auction_price_per_unit"] for i in listing), "현재 매물"
    return None, None


def parse_items(text):
    """'이름A | 이름B, 수량' 형식의 줄들을 [(후보목록, 수량)] 으로"""
    items, errors = [], []
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line:
            names_part, count_part = line.rsplit(",", 1)
        else:
            names_part, count_part = line, "1"
        try:
            count = int(count_part.strip())
        except ValueError:
            errors.append(f"{n}번째 줄 수량이 숫자가 아니에요: `{line}`")
            continue
        names = [s.strip() for s in names_part.split("|") if s.strip()]
        if names:
            items.append((names, count))
    return items, errors


# ================================ 화면 ================================
st.set_page_config(page_title="마비 경매장 합산", page_icon="💰")
st.title("💰 마비노기 경매장 합산")

api_key = get_api_key()
if not api_key:
    api_key = st.text_input("API 키 (Secrets에 넣어두면 이 칸은 안 보여요)", type="password")

text = st.text_area(
    "아이템 목록 — 한 줄에 `이름, 수량` / 둘 중 싼 것은 `이름A | 이름B, 수량`",
    value=DEFAULT_ITEMS, height=380,
)
use_fallback = st.checkbox("최근 1시간 거래가 없으면 현재 매물 최저가로 대체", value=True)

if st.button("가격 조회", type="primary", width="stretch"):
    if not api_key:
        st.error("API 키를 넣어주세요.")
        st.stop()

    items, errors = parse_items(text)
    for e in errors:
        st.warning(e)
    if not items:
        st.stop()

    rows, total, missing = [], 0, []
    progress = st.progress(0.0, text="조회 중...")
    try:
        for idx, (names, count) in enumerate(items):
            progress.progress(idx / len(items), text=f"조회 중: {' / '.join(names)}")
            best, notes = None, []
            for name in names:
                price, src = min_price(api_key, name, use_fallback)
                notes.append(f"{name}: {price:,}" if price is not None else f"{name}: 없음")
                if price is not None and (best is None or price < best[0]):
                    best = (price, name, src)
            if best is None:
                missing.append(" / ".join(names))
                rows.append({"아이템": " / ".join(names), "수량": count,
                             "개당가": None, "소계": None, "출처": "가격 없음", "비교": ""})
                continue
            price, name, src = best
            total += price * count
            rows.append({"아이템": name, "수량": count, "개당가": price,
                         "소계": price * count, "출처": src,
                         "비교": " · ".join(notes) if len(names) > 1 else ""})
    except Exception as e:
        progress.empty()
        st.error(str(e))
        st.stop()
    progress.empty()

    total_r = round(total * (1 - FEE_RATE))
    total_m = round((total + MILEAGE) * (1 - FEE_RATE))
    won_r = round(PACKAGE_PRICE * GOLD_UNIT / total_r) if total_r else 0
    won_m = round(PACKAGE_PRICE * GOLD_UNIT / total_m) if total_m else 0

    c1, c2, c3 = st.columns(3)
    c1.metric("합계", f"{total:,}")
    c2.metric("수수료 제외", f"{total_r:,}")
    c3.metric("마일리지 포함·수수료 제외", f"{total_m:,}")
    c4, c5 = st.columns(2)
    c4.metric("1000숲에 얼마? (마일리지 제외)", f"{won_r:,}원")
    c5.metric("1000숲에 얼마? (마일리지 포함)", f"{won_m:,}원")
    st.code(
        f"35개 기준 수수료 제외: {total_r:,} 골드 / "
        f"마일리지 {MILEAGE // 10_000}만 계산 수수료 제외: {total_m:,} 골드",
        language=None,
    )
    df = pd.DataFrame(rows)
    st.dataframe(
        df, hide_index=True, width="stretch",
        column_config={
            "개당가": st.column_config.NumberColumn(format="localized"),
            "소계": st.column_config.NumberColumn(format="localized"),
        },
    )
    if missing:
        st.warning("가격을 못 찾아 합계에서 뺀 아이템: " + ", ".join(missing))
    st.caption("거래 데이터는 게임보다 평균 10분 늦게 반영돼요. 같은 아이템은 5분 동안 결과를 재사용해요.")