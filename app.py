# -*- coding: utf-8 -*-
"""모험가 수첩 (웹) — 경매장 합산 · 패키지 효율 · 오늘의 득템운"""
import os

import pandas as pd
import streamlit as st

import settings
from core import auction, tarot
from tarot_view import build_html


def get_api_key():
    try:
        key = st.secrets.get("NEXON_API_KEY")
    except Exception:
        key = None
    return key or os.environ.get("NEXON_API_KEY")


def run_pricing(api_key, text, use_fallback):
    if not api_key:
        st.error("API 키를 넣어주세요.")
        return None
    items, errors = auction.parse_items(text)
    for e in errors:
        st.warning(e)
    if not items:
        st.warning("아이템 목록이 비어 있어요.")
        return None
    bar = st.progress(0.0, text="조회 중...")
    try:
        return auction.price_items(
            api_key, items, use_fallback,
            progress=lambda i, n, label: bar.progress(i / n, text=f"조회 중: {label}"))
    except Exception as e:
        st.error(str(e))
        return None
    finally:
        bar.empty()


def show_table(res):
    df = pd.DataFrame(res.rows)
    if res.total:
        df["비중"] = df["소계"].apply(lambda v: f"{v / res.total:.1%}" if pd.notna(v) else "")
    st.dataframe(df, hide_index=True, width="stretch", column_config={
        "개당가": st.column_config.NumberColumn(format="localized"),
        "소계": st.column_config.NumberColumn(format="localized"),
    })


def warn_missing(res):
    if res.missing:
        st.error("⚠️ 가격을 못 찾아 합계에서 뺀 아이템이 있어요 (결과가 실제보다 낮게 나와요): "
                 + ", ".join(res.missing))


# ================================ 화면 ================================
st.set_page_config(page_title="모험가 수첩", page_icon="📔")
st.title("📔 모험가 수첩")

api_key = get_api_key()
if not api_key:
    api_key = st.text_input("API 키 (Secrets에 넣어두면 이 칸은 안 보여요)", type="password")
use_fallback = st.toggle("최근 1시간 거래가 없으면 현재 매물 최저가로 대체", value=True)

tab_auction, tab_package, tab_tarot = st.tabs(["🧮 경매장 합산", "📦 패키지 효율", "🔮 오늘의 득템운"])

# ---------------------------- 경매장 합산 ----------------------------
with tab_auction:
    a_text = st.text_area(
        "아이템 목록 — 한 줄에 `이름, 수량` / 둘 중 싼 것은 `이름A | 이름B, 수량`",
        value=settings.DEFAULT_AUCTION_ITEMS, height=200, key="a_text",
        placeholder="예)\n기억의 보석, 10\n보호의 6단계 푸른 개조석 | 보호의 6단계 붉은 개조석, 2",
    )
    if st.button("합산하기", type="primary", width="stretch", key="a_btn"):
        res = run_pricing(api_key, a_text, use_fallback)
        if res:
            st.session_state["a_res"] = res

    if "a_res" in st.session_state:
        res = st.session_state["a_res"]
        warn_missing(res)
        net = round(res.total * (1 - settings.FEE_RATE))
        m1, m2 = st.columns(2)
        m1.metric("합계", f"{auction.kgold(res.total)} 골드", help=f"{res.total:,} 골드")
        m2.metric("판매 시 수령액 (수수료 4% 제외)", f"{auction.kgold(net)} 골드", help=f"{net:,} 골드")
        show_table(res)

# ---------------------------- 패키지 효율 ----------------------------
with tab_package:
    names = list(settings.PACKAGES)
    p_name = st.selectbox("패키지", names, index=names.index(settings.DEFAULT_PACKAGE), key="p_name")
    preset = settings.PACKAGES[p_name]
    c1, c2 = st.columns(2)
    p_price = c1.number_input("패키지 가격 (원)", min_value=0, value=preset["price"],
                              step=1000, key=f"p_price_{p_name}")
    p_count = c2.number_input("구매 개수", min_value=1, value=settings.DEFAULT_PACKAGE_COUNT,
                              step=1, key="p_count")
    c3, c4 = st.columns(2)
    p_rate = c3.number_input("마일리지 적립률 (%)", min_value=0.0, max_value=100.0,
                             value=settings.DEFAULT_MILEAGE_RATE, step=1.0, format="%.1f", key="p_rate")
    p_m_per = c4.number_input("1000숲 = 마일리지", min_value=1, value=settings.DEFAULT_MILEAGE_PER_1000,
                              step=500, key="p_m_per")
    p_market = st.number_input("비교: 현금으로 1000숲 살 때 (원, 0=비교 안 함)", min_value=0,
                               value=settings.DEFAULT_MARKET_WON, step=1000, key="p_market")

    preview = auction.calc_package(p_name, 0, p_price, p_count, p_rate, p_m_per)
    st.caption(f"1개당 마일리지 {preview.mileage_pts:,} → 약 {preview.mileage_gold:,} 골드 "
               f"({p_count:,}개면 마일리지 {preview.mileage_pts * p_count:,} ≈ "
               f"{preview.mileage_gold * p_count:,} 골드)")

    with st.expander("구성품 (패키지 1개 기준)"):
        p_text = st.text_area("한 줄에 `이름, 수량` / 둘 중 싼 것은 `이름A | 이름B, 수량`",
                              value=preset["items"], height=380, key=f"p_text_{p_name}")

    if st.button("효율 계산", type="primary", width="stretch", key="p_btn"):
        res = run_pricing(api_key, p_text, use_fallback)
        if res:
            st.session_state["p_res"] = res

    if "p_res" in st.session_state:
        res = st.session_state["p_res"]
        warn_missing(res)
        pr = auction.calc_package(p_name, res.total, p_price, p_count, p_rate, p_m_per, p_market)

        st.subheader(f"{p_name} × {p_count:,}개")
        st.metric("총 결제 금액", f"{pr.pay_total:,}원")
        k2, k3 = st.columns(2)
        k2.metric("되팔면 (수수료 제외)", f"{auction.kgold(pr.net_total)} 골드", help=f"{pr.net_total:,} 골드")
        k3.metric("마일리지 포함", f"{auction.kgold(pr.net_total_m)} 골드", help=f"{pr.net_total_m:,} 골드")

        st.subheader("1000숲을 얼마에 사는 셈?")
        w1, w2 = st.columns(2)
        if p_market:
            w1.metric("마일리지 제외", f"{pr.won_per:,}원", delta=f"{pr.won_per - p_market:+,}원 vs 시세",
                      delta_color="inverse")
            w2.metric("마일리지 포함", f"{pr.won_per_m:,}원", delta=f"{pr.won_per_m - p_market:+,}원 vs 시세",
                      delta_color="inverse")
            v = pr.verdict()
            if v:
                (st.success if "싸게" in v else st.warning)(v)
        else:
            w1.metric("마일리지 제외", f"{pr.won_per:,}원")
            w2.metric("마일리지 포함", f"{pr.won_per_m:,}원")
            st.caption("현금 1000숲 시세를 넣으면 이득인지 손해인지 비교해 드려요.")

        st.code(pr.summary_lines(), language=None)
        with st.expander(f"구성품별 가격 (1개 기준 합계 {res.total:,} 골드)"):
            show_table(res)

# ---------------------------- 오늘의 득템운 ----------------------------
with tab_tarot:
    nick = st.text_input("닉네임", key="t_nick", max_chars=20,
                         placeholder="같은 닉네임이면 오늘 하루 동안 같은 결과가 나와요")
    if st.button("🔮 카드 뽑으러 가기", type="primary", width="stretch", key="t_btn"):
        if nick.strip():
            st.session_state["t_user"] = nick.strip()
        else:
            st.warning("닉네임을 넣어주세요.")
    if st.session_state.get("t_user"):
        reading = tarot.draw(st.session_state["t_user"])
        st.iframe(build_html(reading), height=900)

st.caption(f"거래 데이터는 게임보다 평균 10분 늦게 반영돼요. 같은 아이템은 "
           f"{settings.CACHE_TTL_SECONDS // 60}분 동안 조회 결과를 모두가 같이 써요. "
           f"오늘 API 호출 {auction.budget.calls_today():,}/{settings.DAILY_CALL_LIMIT:,}")