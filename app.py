# -*- coding: utf-8 -*-
"""마비노기 경매장 합산 + 현금 패키지 효율 계산기 (Streamlit)"""
import os
import time

import pandas as pd
import requests
import streamlit as st

# ======================= 기본값 (고쳐서 GitHub에 올리면 기본값이 바뀝니다) =======================
# 아이템 목록 형식 — 한 줄에 하나:  아이템이름, 수량
#                    둘 중 싼 것:   아이템A | 아이템B, 수량

# [경매장 합산] 탭 기본 목록
DEFAULT_AUCTION_ITEMS = """\
기억의 보석, 10
환생의 비약, 5
"""

# [패키지 효율] 탭 기본값 — 패키지 1개에 들어있는 구성품
DEFAULT_PACKAGE_NAME = "내 패키지"
DEFAULT_PACKAGE_ITEMS = """\
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
DEFAULT_PACKAGE_PRICE = 119_000   # 패키지 1개 가격 (원)
DEFAULT_PACKAGE_COUNT = 35        # 구매 개수
DEFAULT_MILEAGE_RATE = 5.0        # 마일리지 적립률 (%) — 결제 금액의 몇 % 가 마일리지로 들어오는지
DEFAULT_MILEAGE_PER_1000 = 15_000 # 1000숲(1,000만 골드)에 해당하는 마일리지
DEFAULT_MARKET_WON = 0            # 비교 기준: 현금으로 1000숲 살 때 가격(원). 0이면 비교 안 함

FEE_RATE = 0.04                   # 경매장 수수료 4%
GOLD_UNIT = 10_000_000            # 1000숲 = 1,000만 골드
# ===================================================================================================

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


def price_items(api_key, items, use_fallback):
    """[(후보목록, 수량)] → (행 목록, 합계, 못 찾은 아이템)"""
    rows, total, missing = [], 0, []
    progress = st.progress(0.0, text="조회 중...")
    try:
        for idx, (names, count) in enumerate(items):
            progress.progress(idx / len(items), text=f"조회 중: {' | '.join(names)}")
            best, notes = None, []
            for name in names:
                price, src = min_price(api_key, name, use_fallback)
                notes.append(f"{name}: {price:,}" if price is not None else f"{name}: 없음")
                if price is not None and (best is None or price < best[0]):
                    best = (price, name, src)
            if best is None:
                missing.append(" | ".join(names))
                rows.append({"아이템": " | ".join(names), "수량": count, "개당가": None,
                             "소계": None, "출처": "가격 없음", "비교": ""})
                continue
            price, name, src = best
            total += price * count
            rows.append({"아이템": name, "수량": count, "개당가": price, "소계": price * count,
                         "출처": src, "비교": " · ".join(notes) if len(names) > 1 else ""})
    finally:
        progress.empty()
    return rows, total, missing


def run_pricing(api_key, text, use_fallback):
    """입력 검사 + 조회. 실패하면 None"""
    if not api_key:
        st.error("API 키를 넣어주세요.")
        return None
    items, errors = parse_items(text)
    for e in errors:
        st.warning(e)
    if not items:
        st.warning("아이템 목록이 비어 있어요.")
        return None
    try:
        return price_items(api_key, items, use_fallback)
    except Exception as e:
        st.error(str(e))
        return None


def show_table(rows, total=None):
    df = pd.DataFrame(rows)
    if total and "소계" in df:
        df["비중"] = df["소계"].apply(lambda v: f"{v / total:.1%}" if pd.notna(v) else "")
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        "개당가": st.column_config.NumberColumn(format="localized"),
        "소계": st.column_config.NumberColumn(format="localized"),
    })


def warn_missing(missing):
    if missing:
        st.error("⚠️ 가격을 못 찾아 합계에서 뺀 아이템이 있어요 (결과가 실제보다 낮게 나와요): "
                 + ", ".join(missing))


# ================================ 화면 ================================
st.set_page_config(page_title="마비 경매장 계산기", page_icon="💰")
st.title("💰 마비 경매장 계산기")

api_key = get_api_key()
if not api_key:
    api_key = st.text_input("API 키 (Secrets에 넣어두면 이 칸은 안 보여요)", type="password")
use_fallback = st.toggle("최근 1시간 거래가 없으면 현재 매물 최저가로 대체", value=True)

tab_auction, tab_package = st.tabs(["🧮 경매장 합산", "📦 패키지 효율"])

# ---------------------------- 경매장 합산 ----------------------------
with tab_auction:
    a_text = st.text_area(
        "아이템 목록 — 한 줄에 `이름, 수량` / 둘 중 싼 것은 `이름A | 이름B, 수량`",
        value=DEFAULT_AUCTION_ITEMS, height=200, key="a_text",
    )
    if st.button("합산하기", type="primary", width="stretch", key="a_btn"):
        res = run_pricing(api_key, a_text, use_fallback)
        if res:
            st.session_state["a_res"] = res

    if "a_res" in st.session_state:
        rows, total, missing = st.session_state["a_res"]
        warn_missing(missing)
        m1, m2 = st.columns(2)
        m1.metric("합계", f"{total:,} 골드")
        m2.metric("판매 시 수령액 (수수료 4% 제외)", f"{round(total * (1 - FEE_RATE)):,} 골드")
        show_table(rows, total)

# ---------------------------- 패키지 효율 ----------------------------
with tab_package:
    p_name = st.text_input("패키지 이름", value=DEFAULT_PACKAGE_NAME, key="p_name")
    c1, c2 = st.columns(2)
    p_price = c1.number_input("패키지 가격 (원)", min_value=0, value=DEFAULT_PACKAGE_PRICE,
                              step=1000, key="p_price")
    p_count = c2.number_input("구매 개수", min_value=1, value=DEFAULT_PACKAGE_COUNT,
                              step=1, key="p_count")
    c3, c4 = st.columns(2)
    p_rate = c3.number_input("마일리지 적립률 (%)", min_value=0.0, max_value=100.0,
                             value=DEFAULT_MILEAGE_RATE, step=1.0, format="%.1f", key="p_rate")
    p_m_per = c4.number_input("1000숲 = 마일리지", min_value=1, value=DEFAULT_MILEAGE_PER_1000,
                              step=500, key="p_m_per")
    p_market = st.number_input("비교: 현금으로 1000숲 살 때 (원, 0=비교 안 함)", min_value=0,
                               value=DEFAULT_MARKET_WON, step=1000, key="p_market")

    mileage_pts = round(p_price * p_rate / 100)                 # 1개당 받는 마일리지
    p_mileage = round(mileage_pts * GOLD_UNIT / p_m_per)        # 골드로 환산
    st.caption(f"1개당 마일리지 {mileage_pts:,} → 약 {p_mileage:,} 골드 "
               f"({p_count:,}개면 마일리지 {mileage_pts * p_count:,} ≈ {p_mileage * p_count:,} 골드)")
    with st.expander("구성품 (패키지 1개 기준)"):
        p_text = st.text_area(
            "한 줄에 `이름, 수량` / 둘 중 싼 것은 `이름A | 이름B, 수량`",
            value=DEFAULT_PACKAGE_ITEMS, height=380, key="p_text",
        )

    if st.button("효율 계산", type="primary", width="stretch", key="p_btn"):
        res = run_pricing(api_key, p_text, use_fallback)
        if res:
            st.session_state["p_res"] = res

    if "p_res" in st.session_state:
        rows, total, missing = st.session_state["p_res"]
        warn_missing(missing)

        # 패키지 1개 기준 (골드)
        one_net = round(total * (1 - FEE_RATE))                    # 되팔면 받는 골드
        one_net_m = round((total + p_mileage) * (1 - FEE_RATE))    # 마일리지 포함
        won_per = round(p_price * GOLD_UNIT / one_net) if one_net else 0
        won_per_m = round(p_price * GOLD_UNIT / one_net_m) if one_net_m else 0

        st.subheader(f"{p_name} × {p_count:,}개")
        k1, k2, k3 = st.columns(3)
        k1.metric("총 결제 금액", f"{p_price * p_count:,}원")
        k2.metric("되팔면 (수수료 제외)", f"{one_net * p_count:,} 골드")
        k3.metric("마일리지 포함", f"{one_net_m * p_count:,} 골드")

        st.subheader("1000숲을 얼마에 사는 셈?")
        w1, w2 = st.columns(2)
        if p_market:
            w1.metric("마일리지 제외", f"{won_per:,}원", delta=f"{won_per - p_market:+,}원 vs 시세",
                      delta_color="inverse")
            w2.metric("마일리지 포함", f"{won_per_m:,}원", delta=f"{won_per_m - p_market:+,}원 vs 시세",
                      delta_color="inverse")
            best = won_per_m or won_per
            if best and best < p_market:
                st.success(f"마일리지 포함 기준으로 현금 시세보다 **{1 - best / p_market:.1%} 싸게** 골드를 얻는 셈이에요.")
            elif best:
                st.warning(f"마일리지 포함해도 현금 시세보다 **{best / p_market - 1:.1%} 비싸요.**")
        else:
            w1.metric("마일리지 제외", f"{won_per:,}원")
            w2.metric("마일리지 포함", f"{won_per_m:,}원")
            st.caption("현금 1000숲 시세를 넣으면 이득인지 손해인지 비교해 드려요.")

        st.code(
            f"{p_name} {p_count:,}개 기준 수수료 제외: {one_net * p_count:,} 골드 / "
            f"마일리지 {p_rate:g}%({p_mileage // 10_000:,}만) 계산 수수료 제외: {one_net_m * p_count:,} 골드\n"
            f"1000숲에 얼마? 마일리지 제외 {won_per:,}원 / 마일리지 포함 {won_per_m:,}원",
            language=None,
        )
        with st.expander(f"구성품별 가격 (1개 기준 합계 {total:,} 골드)"):
            show_table(rows, total)

st.caption("거래 데이터는 게임보다 평균 10분 늦게 반영돼요. 같은 아이템은 5분 동안 결과를 재사용해요.")