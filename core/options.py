# -*- coding: utf-8 -*-
"""
경매장 옵션 해석 + 옵션 조건 검색

모든 옵션을 "꼬리표(label) + 숫자"로 바꿔서 같은 방식으로 검색해요.
  최대 공격력(16레벨:32 증가)          → [세공 최대 공격력] 16   (비교는 레벨)
  에코스톤 고유 능력 / 지력 / 91        → [에코스톤 고유 능력 지력] 91
  인챈트 / 접두 / 광포한 (랭크 7)       → [인챈트 접두 광포한] 7
  아이템 색상 / 파트 A / 170,10,20      → [아이템 색상 파트 A R] 170, [… G] 10, [… B] 20

조건 문법 (쉼표로 여러 개 = 모두 만족):
  "최공 20"  "최공 20 이상"  "최공 18~20"  "최공 20 이하"  "광포한"  "파트 A R 250 이상"
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

INDEX_PATH = Path(__file__).resolve().parent.parent / "data" / "option_index.json"
NUM = re.compile(r"-?\d+(?:\.\d+)?")

# 줄임말 → 실제 이름(공백 없이). 여러 개면 그중 하나만 맞아도 돼요. 길드에서 쓰는 말을 자유롭게 추가하세요.
ALIASES = {
    "최공": ["최대공격력", "최대대미지"],
    "최대공": ["최대공격력", "최대대미지"],
    "최소공": ["최소공격력", "최소대미지"],
    "마공": ["마법공격력"],
    "크뎀": ["크리티컬대미지"],
    "크리": ["크리티컬"],
    "밸런": ["밸런스"],
    "사거리": ["유효사거리", "사거리"],
    "공속": ["공격속도"],
    "이속": ["이동속도"],
    "캐속": ["캐스팅속도"],
    "쿨감": ["쿨타임감소"],
    "최생": ["최대생명력"],
    "최마": ["최대마나"],
    "최스": ["최대스태미나"],
    "마방": ["마법방어"],
    "마보": ["마법보호"],
    "에코": ["에코스톤"],
    "각성": ["각성능력"],
    "고유": ["고유능력"],
    "토템": ["토템효과"],
    "펫": ["펫정보"],
    "유물": ["무리아스유물"],
    "세트": ["세트효과"],
    "장인": ["장인개조"],
    "특개": ["특별개조"],
    "의장": ["의장등급"],
    "색": ["색상"],
}


def squash(s):
    return re.sub(r"\s+", "", str(s or ""))


@dataclass
class Fact:
    label: str            # 검색용 꼬리표
    number: float = None  # 비교할 숫자 (세공·각성은 레벨)
    show: str = ""        # 결과에 보여줄 글
    kind: str = ""        # option_type
    name: str = ""        # 순수 옵션 이름 (세공 이름 등, 링크용)
    over: bool = False    # 한계돌파 표시


def _first_num(s):
    m = NUM.search(str(s or ""))
    return float(m.group()) if m else None


_REFORGE_1 = re.compile(r"^(.*?)\((\d+)레벨:(.*)\)\s*$")
_REFORGE_2 = re.compile(r"^(.*?)\s*(\d+)\s*레벨")
_PLUS = re.compile(r"([^,]+?)\s*(-?\d+(?:\.\d+)?)\s*(%?)\s*(증가|감소)")
_RANK = re.compile(r"^(.*?)\s*\(랭크\s*([0-9A-Z]+)\)\s*$")


def parse_option(op):
    """넥슨 옵션 1개 → [Fact]"""
    t = op.get("option_type") or ""
    sub = str(op.get("option_sub_type") or "")
    v = str(op.get("option_value") or "").strip()
    v2 = op.get("option_value2")
    v2 = "" if v2 is None else str(v2).strip()

    if t == "세공 옵션":
        m = _REFORGE_1.match(v) or _REFORGE_2.match(v)
        if m:
            name, lv = m.group(1).strip(), int(m.group(2))
            eff = m.group(3).strip() if m.re is _REFORGE_1 else ""
            show = f"{name} {lv}레벨" + (f" ({eff})" if eff else "") + (" ⚡" if lv > 20 else "")
            return [Fact(f"세공 {name}", lv, show, t, name, lv > 20)]
    if t == "에코스톤 각성 능력":
        m = _REFORGE_2.match(v)
        if m:
            name, lv = m.group(1).strip(), int(m.group(2))
            return [Fact(f"에코스톤 각성 능력 {name}", lv, f"각성: {name} {lv}레벨", t, name)]
    if t in ("인챈트", "인챈트 종류"):
        m = _RANK.match(v)
        name, rank = (m.group(1).strip(), m.group(2)) if m else (v, "")
        num = float(rank) if rank.isdigit() else None
        return [Fact(f"인챈트 {sub} {name}", num, f"{sub} {name}" + (f" (랭크 {rank})" if rank else ""), t, name)]
    if t == "세트 효과":
        return [Fact(f"세트 효과 {v}", _first_num(v2), f"세트: {v} {v2}", t, v)]
    if t in ("사용 효과", "조미료 효과", "장인 개조"):
        out = [Fact(f"{t} {m.group(1).strip()}", float(m.group(2)),
                    f"{m.group(1).strip()} {m.group(2)}{m.group(3)} {m.group(4)}", t, m.group(1).strip())
               for m in _PLUS.finditer(v)]
        if out:
            return out
    if t == "무리아스 유물":
        m = re.match(r"^(.*?)\s*(-?\d+(?:\.\d+)?)%\s*증가", v)
        if m:
            return [Fact(f"무리아스 유물 {m.group(1).strip()}", float(m.group(2)), f"유물: {v}", t, m.group(1).strip())]
    if t in ("아이템 색상", "색상"):
        rgb = [float(x) for x in NUM.findall(v)]
        if len(rgb) == 3:
            base = f"{t} {sub}".strip()
            return [Fact(f"{base} {c}", n, f"{sub or '색상'} RGB({v})", t) for c, n in zip("RGB", rgb)]
    if t == "공격" and v2:
        return [Fact("공격 최소 대미지", _first_num(v), f"공격 {v}~{v2}", t),
                Fact("공격 최대 대미지", _first_num(v2), f"공격 {v}~{v2}", t)]
    if t == "부상률" and v2:
        return [Fact("부상률 최소", _first_num(v), f"부상률 {v}~{v2}", t),
                Fact("부상률 최대", _first_num(v2), f"부상률 {v}~{v2}", t)]
    if t == "내구력" and v2:
        return [Fact("내구력", _first_num(v), f"내구력 {v}/{v2}", t),
                Fact("최대 내구력", _first_num(v2), f"내구력 {v}/{v2}", t)]
    if t == "에르그" and sub:
        return [Fact(f"에르그 {sub}등급", _first_num(v), f"에르그 {sub}등급 {v}" + (f"/{v2}" if v2 else "") + "레벨", t, sub)]

    # 그 밖: sub 가 있으면 항목 이름, 값이 숫자면 숫자로 / 글자면 글자로
    num = _first_num(v)
    text_value = "" if (num is not None and NUM.sub("", v).strip(" %cm+|") == "") else v
    label = " ".join(x for x in (t, sub, text_value) if x)
    show = " ".join(x for x in (t, sub, v + (f" | {v2}" if v2 else "")) if x)
    return [Fact(label, None if text_value else num, show, t, sub or text_value)]


def facts_of(item):
    out = []
    for op in item.get("item_option") or []:
        try:
            out += parse_option(op)
        except Exception:
            continue
    return out


# ============================== 조건 ==============================
@dataclass
class Cond:
    raw: str
    words: list                 # 각 단어의 후보 목록 [[...], [...]]
    gte: float = None
    lte: float = None
    labels: list = field(default_factory=list)   # 해석된 꼬리표 (색인 기준)

    def match_label(self, label):
        s = squash(label)
        return all(any(w in s for w in alts) for alts in self.words)

    def match_fact(self, f):
        if self.labels:
            if f.label not in self.labels:
                return False
        elif not self.match_label(f.label):
            return False
        if self.gte is None and self.lte is None:
            return True
        if f.number is None:
            return False
        return (self.gte is None or f.number >= self.gte) and (self.lte is None or f.number <= self.lte)

    def range_text(self):
        if self.gte is not None and self.lte is not None:
            return f" {self.gte:g}~{self.lte:g}"
        if self.gte is not None:
            return f" ≥ {self.gte:g}"
        if self.lte is not None:
            return f" ≤ {self.lte:g}"
        return ""


def parse_conditions(text):
    conds = []
    for part in re.split(r"[,，/]", text or ""):
        part = part.strip()
        if not part:
            continue
        gte = lte = None
        s = part
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*[~\-]\s*(-?\d+(?:\.\d+)?)", s)
        if m:
            gte, lte = float(m.group(1)), float(m.group(2))
            s = s[:m.start()] + s[m.end():]
        else:
            m = re.search(r"(>=|<=|≥|≤)?\s*(-?\d+(?:\.\d+)?)\s*(이상|이하|↑|↓)?\s*$", s)
            if m:
                n = float(m.group(2))
                if m.group(1) in ("<=", "≤") or m.group(3) in ("이하", "↓"):
                    lte = n
                else:
                    gte = n
                s = s[:m.start()]
        tokens = [w for w in re.split(r"\s+", s.strip()) if w]
        words = []
        for w in tokens:
            key = squash(w)
            alts = ALIASES.get(key, []) + [key]
            words.append(list(dict.fromkeys(alts)))
        if words:
            conds.append(Cond(part, words, gte, lte))
    return conds


def filter_items(items, conds):
    """조건을 모두 만족하는 매물 [(item, [맞은 Fact…])]"""
    out = []
    for it in items:
        fs = facts_of(it)
        hit = []
        ok = True
        for c in conds:
            m = [f for f in fs if c.match_fact(f)]
            if not m:
                ok = False
                break
            hit += m
        if ok:
            out.append((it, hit))
    return out


def per_condition_counts(items, conds):
    """조건별로 그 조건 하나만 만족하는 매물 수"""
    res = []
    for c in conds:
        n = sum(1 for it in items if any(c.match_fact(f) for f in facts_of(it)))
        res.append(n)
    return res


# ============================== 색인 (사전에서 뽑은 작은 파일) ==============================
_INDEX = None


def load_index():
    global _INDEX
    if _INDEX is None:
        try:
            _INDEX = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            _INDEX = {"labels": {}, "items": {}, "reforge": []}
    return _INDEX


def item_category(item_name):
    for cat, names in load_index()["items"].items():
        if item_name in names:
            return cat
    return None


PREFIXES = ["세공 ", "인챈트 접두 ", "인챈트 접미 ", "세트 효과 ", "에코스톤 고유 능력 ", "에코스톤 각성 능력 ",
            "토템 효과 ", "무리아스 유물 ", "사용 효과 ", "장인 개조 ", "조미료 효과 ", "펫 정보 "]


def core_name(label):
    for p in PREFIXES:
        if label.startswith(p):
            return label[len(p):]
    return label


def _is_exact(cond, label):
    """'최공' → '세공 최대 공격력' 처럼 옵션 이름 자체가 입력(또는 줄임말 풀이)과 같은지"""
    core = squash(core_name(label))
    joined = "".join(alts[-1] for alts in cond.words)
    if core == joined:
        return True
    return len(cond.words) == 1 and core in cond.words[0]


def label_candidates(cond, category=None, limit=None):
    """조건에 맞는 꼬리표들 (이름이 정확히 같은 것 → 많이 쓰이는 순). 카테고리에 없으면 전체에서"""
    idx = load_index()["labels"]

    def scan(pools):
        counts = {}
        for pool in pools:
            for label, n in pool.items():
                if cond.match_label(label):
                    counts[label] = counts.get(label, 0) + n
        return counts

    counts = scan([idx[category]]) if category in idx else {}
    if not counts:
        counts = scan(idx.values())
    out = sorted(counts, key=lambda x: (not _is_exact(cond, x), -counts[x]))
    return out[:limit] if limit else out


def resolve(conds, category=None):
    """
    조건마다 꼬리표를 정해요. 이름이 정확히 같은 옵션이 있으면 그것만,
    없으면 단어가 들어간 옵션 전부(넓게)로 검색해요. 반환: 조건별 설명 문자열
    """
    notes = []
    for c in conds:
        cands = label_candidates(c, category)
        exact = [l for l in cands if _is_exact(c, l)]
        c.labels = exact
        if exact:
            notes.append(f"`{c.raw}` → {exact[0]}{c.range_text()}" + (f" 외 {len(exact) - 1}" if len(exact) > 1 else ""))
        elif cands:
            more = f" 등 {len(cands)}개 중 하나" if len(cands) > 1 else ""
            notes.append(f"`{c.raw}` → {cands[0]}{more}{c.range_text()}")
        else:
            notes.append(f"`{c.raw}` → (사전에 없는 옵션, 글자로 찾아볼게요){c.range_text()}")
    return notes


def suggest_labels(text, category=None, limit=25):
    """자동완성: 마지막 조건 조각에 맞는 꼬리표"""
    conds = parse_conditions(text.split(",")[-1] if text else "")
    if not conds:
        return []
    return label_candidates(conds[-1], category, limit)


def build_index(catalog):
    """option_catalog.json → option_index.json (봇이 읽는 작은 색인)"""
    labels, items, reforge = {}, {}, set()
    for cat, e in catalog.get("categories", {}).items():
        items[cat] = sorted(n for n in e.get("item_names", {}) if n)
        pool = labels.setdefault(cat, {})
        for t, subs in e.get("options", {}).items():
            for sub, tpls in subs.items():
                for tpl, info in tpls.items():
                    for ex in info.get("ex", [])[:1]:
                        op = {"option_type": t, "option_sub_type": sub, **ex}
                        for f in parse_option(op):
                            pool[f.label] = pool.get(f.label, 0) + info.get("n", 1)
                            if f.kind == "세공 옵션" and f.name:
                                reforge.add(f.name)
    return {"labels": labels, "items": items, "reforge": sorted(reforge)}


def link_terms(conds, category=None):
    """
    mabi.zip 링크에 넣을 수 있는 조건만 골라요 (지금 아는 형식: 세공 옵션, 에르그 등급)
    반환: (세공 [(이름, 이상, 이하)], 에르그 등급 또는 None, 링크에 못 넣은 조건들)
    """
    reforge, erg, skipped = [], None, []
    for c in conds:
        cands = c.labels or label_candidates(c, category)
        if cands and all(l.startswith("세공 ") for l in cands) and len({l[3:] for l in cands}) == 1:
            reforge.append((cands[0][3:], None if c.gte is None else int(c.gte),
                            None if c.lte is None else int(c.lte)))
        elif cands and all(re.fullmatch(r"에르그 [A-Z]등급", l) for l in cands) and len(set(cands)) == 1 and erg is None:
            erg = cands[0].split()[1][0]
            if c.gte is not None or c.lte is not None:
                skipped.append(f"{c.raw} (에르그 레벨은 mabi.zip에서 선택)")
        else:
            skipped.append(c.raw)
    return reforge[:3], erg, skipped + [f"{n} (세공은 3개까지)" for n, _, _ in reforge[3:]]
