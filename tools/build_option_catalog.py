# -*- coding: utf-8 -*-
"""
경매장 옵션 사전 만들기 — 카테고리별 매물을 훑어서 '옵션 틀'과 '아이템 이름'을 모아요.
매물 자체는 저장하지 않고, 처음 보는 옵션/이름만 사전에 더해요.

    python tools/build_option_catalog.py                 # 전체 카테고리
    python tools/build_option_catalog.py 활 "염색 앰플"    # 일부만
    python tools/build_option_catalog.py --restart       # 처음부터 다시 훑기 (사전은 유지, 새 것만 추가)

API 키: .env 의 NEXON_COLLECT_API_KEY (없으면 NEXON_API_KEY)

멈춤/재개:
  - 진행 상황은 data/catalog_state.json 에 저장돼요. 중간에 꺼도 다시 실행하면 이어서 해요.
  - 하루 호출 상한(--daily, 기본 950)에 닿으면 다음 날(한국 시간 자정)까지 기다렸다가 자동으로 이어가요.

카테고리를 그만 보는 조건:
  - 연속 --stale 페이지(기본 3) 동안 새 옵션 틀이 없고 새 아이템 이름도 거의 없을 때
  - 또는 --max-pages(기본 20페이지 = 1만 개)에 닿았을 때

결과: data/option_catalog.json (원본, PC 보관) + data/option_index.json (봇용 색인, GitHub 에 올리기)
색인만 다시 만들기: python tools/build_option_catalog.py --index-only
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core.mabizip import CATEGORIES  # noqa: E402
from core.options import build_index, INDEX_PATH  # noqa: E402

URL = "https://open.api.nexon.com/mabinogi/v1/auction/list"
CATALOG = ROOT / "data" / "option_catalog.json"
STATE = ROOT / "data" / "catalog_state.json"
KST = dt.timezone(dt.timedelta(hours=9))
NUM = re.compile(r"-?\d+(?:\.\d+)?")
MAX_EXAMPLES = 3


# ------------------------------------------------------------------ 파일
def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)                       # 중간에 꺼져도 파일이 깨지지 않게


def api_key():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    for name in ("NEXON_COLLECT_API_KEY", "NEXON_API_KEY"):
        key = os.environ.get(name) or env.get(name)
        if key:
            print(f"API 키: {name}")
            return key
    sys.exit(".env 에 NEXON_COLLECT_API_KEY (또는 NEXON_API_KEY) 를 넣어주세요.")


# ------------------------------------------------------------------ 호출 관리
def today():
    return dt.datetime.now(KST).date().isoformat()


def wait_until_tomorrow():
    now = dt.datetime.now(KST)
    nxt = (now + dt.timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    secs = (nxt - now).total_seconds()
    print(f"\n⏸  오늘 호출 상한 도달 → {nxt:%m/%d %H:%M} 까지 기다렸다가 이어서 할게요 "
          f"(약 {secs / 3600:.1f}시간). 꺼도 괜찮아요, 다시 실행하면 이어서 해요.")
    time.sleep(secs)


def call(key, state, args, params):
    while True:
        if state["calls"].get(today(), 0) >= args.daily:
            if args.no_wait:
                return None
            wait_until_tomorrow()
            continue
        time.sleep(args.interval)
        try:
            r = requests.get(URL, params=params, headers={"x-nxopen-api-key": key}, timeout=30)
        except requests.RequestException as e:
            print(f"   네트워크 오류, 1분 뒤 재시도: {e}")
            time.sleep(60)
            continue
        state["calls"][today()] = state["calls"].get(today(), 0) + 1
        if r.status_code == 200:
            return r.json()
        try:
            err = r.json().get("error", {})
        except ValueError:
            err = {"message": r.text[:200]}
        if r.status_code == 429:
            print(f"   호출 제한(429) {err.get('message')} → 10분 쉬었다가 재시도")
            time.sleep(600)
            continue
        if r.status_code >= 500 or err.get("name") in ("OPENAPI00009", "OPENAPI00010", "OPENAPI00011"):
            print(f"   서버 점검/준비 중 {r.status_code} {err.get('name')} → 30분 뒤 재시도")
            time.sleep(1800)
            continue
        print(f"   오류 {r.status_code} {err} → 이 카테고리는 건너뛸게요")
        return {"auction_item": [], "next_cursor": None, "_error": True}


# ------------------------------------------------------------------ 옵션 틀
def template(op):
    """옵션 1줄 → (틀, 숫자들). 예: '유효 사거리 20 레벨' → ('유효 사거리 # 레벨', [20])"""
    text = str(op.get("option_value") or "")
    if op.get("option_value2") not in (None, ""):
        text += " | " + str(op["option_value2"])
    nums = [float(n) for n in NUM.findall(text)]
    return NUM.sub("#", text).strip(), nums


def add_listing(cat_entry, item):
    """새 옵션 틀 수, 새 이름 여부"""
    new_t = 0
    names = cat_entry.setdefault("item_names", {})
    is_new_name = item.get("item_name") not in names
    names[item.get("item_name")] = names.get(item.get("item_name"), 0) + 1
    opts = cat_entry.setdefault("options", {})
    for op in item.get("item_option") or []:
        t, nums = template(op)
        sub = str(op.get("option_sub_type") or "")
        slot = opts.setdefault(op.get("option_type") or "?", {}).setdefault(sub, {})
        if t not in slot:
            slot[t] = {"n": 0, "min": list(nums), "max": list(nums), "ex": []}
            new_t += 1
        e = slot[t]
        e["n"] += 1
        if len(nums) == len(e["min"]):
            e["min"] = [min(a, b) for a, b in zip(e["min"], nums)]
            e["max"] = [max(a, b) for a, b in zip(e["max"], nums)]
        raw = {k: op.get(k) for k in ("option_value", "option_value2", "option_desc") if op.get(k) not in (None, "")}
        if len(e["ex"]) < MAX_EXAMPLES and raw not in e["ex"]:
            e["ex"].append(raw)
    return new_t, is_new_name


# ------------------------------------------------------------------ 메인
def main():
    ap = argparse.ArgumentParser(description="경매장 옵션 사전 만들기")
    ap.add_argument("categories", nargs="*", help="카테고리 (기본: 전체)")
    ap.add_argument("--max-pages", type=int, default=20, help="카테고리당 최대 페이지 (1페이지=500개)")
    ap.add_argument("--stale", type=int, default=3, help="새 옵션이 없는 페이지가 이만큼 이어지면 다음 카테고리로")
    ap.add_argument("--daily", type=int, default=950, help="하루 호출 상한")
    ap.add_argument("--interval", type=float, default=0.5, help="호출 간격(초)")
    ap.add_argument("--no-wait", action="store_true", help="상한에 닿으면 기다리지 않고 종료")
    ap.add_argument("--restart", action="store_true", help="진행 상황을 지우고 처음부터 다시 훑기")
    ap.add_argument("--index-only", action="store_true", help="수집 없이 option_catalog.json 으로 색인만 다시 만들기")
    args = ap.parse_args()
    if args.index_only:
        INDEX_PATH.write_text(json.dumps(build_index(load(CATALOG, {"categories": {}})), ensure_ascii=False,
                                         separators=(",", ":")), encoding="utf-8")
        print(f"색인 생성: {INDEX_PATH}")
        return

    cats = args.categories or CATEGORIES
    bad = [c for c in cats if c not in CATEGORIES]
    if bad:
        sys.exit(f"없는 카테고리: {bad}")

    key = api_key()
    catalog = load(CATALOG, {"categories": {}})
    state = load(STATE, {"calls": {}, "progress": {}})
    if args.restart:
        state["progress"] = {}

    for ci, cat in enumerate(cats, 1):
        prog = state["progress"].setdefault(cat, {"done": False, "cursor": "", "pages": 0, "stale": 0})
        if prog["done"]:
            continue
        entry = catalog["categories"].setdefault(cat, {"listings_seen": 0})
        print(f"\n[{ci}/{len(cats)}] {cat}  (이어서 {prog['pages']}페이지부터)")
        while not prog["done"]:
            params = {"auction_item_category": cat}
            if prog["cursor"]:
                params["cursor"] = prog["cursor"]
            data = call(key, state, args, params)
            if data is None:                      # --no-wait 이고 상한 도달
                save(STATE, state)
                save(CATALOG, catalog)
                print("\n오늘 상한에 닿아서 멈췄어요. 내일 다시 실행하면 이어서 해요.")
                return
            items = data.get("auction_item") or []
            new_t = new_n = 0
            for it in items:
                t, n = add_listing(entry, it)
                new_t += t
                new_n += n
            entry["listings_seen"] += len(items)
            prog["pages"] += 1
            prog["cursor"] = data.get("next_cursor") or ""
            # 새 옵션 틀이 없고 새 이름도 2% 미만이면 '변화 없음' 페이지
            prog["stale"] = prog["stale"] + 1 if (new_t == 0 and new_n <= max(1, len(items) // 50)) else 0
            print(f"   {prog['pages']:>3}p  매물 {len(items):>3} · 새 옵션 {new_t:>3} · 새 이름 {new_n:>3}"
                  f"  (오늘 호출 {state['calls'].get(today(), 0)})")
            if (not prog["cursor"] or data.get("_error") or prog["stale"] >= args.stale
                    or prog["pages"] >= args.max_pages):
                prog["done"] = True
            entry["updated"] = dt.datetime.now(KST).isoformat(timespec="seconds")
            catalog["updated"] = entry["updated"]
            save(CATALOG, catalog)
            save(STATE, state)

    n_t = sum(len(ts) for c in catalog["categories"].values()
              for subs in c.get("options", {}).values() for ts in subs.values())
    n_n = sum(len(c.get("item_names", {})) for c in catalog["categories"].values())
    INDEX_PATH.write_text(json.dumps(build_index(catalog), ensure_ascii=False, separators=(",", ":")),
                          encoding="utf-8")
    print(f"\n✅ 완료! 옵션 틀 {n_t:,}개 · 아이템 이름 {n_n:,}개")
    print(f"   봇용 색인: {INDEX_PATH}  ← 이 파일을 GitHub 에 올려주세요")
    print("   (option_catalog.json 은 다음 수집 때 이어서 쓰는 원본이라 PC에만 두면 돼요)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n중단했어요. 다시 실행하면 이어서 해요.")
