# -*- coding: utf-8 -*-
"""
오늘의 득템운 — 사용자 + 오늘 날짜(KST)로 결과가 정해져서 하루 동안 고정돼요.
같은 사람이 같은 날 몇 번을 뽑아도 같은 카드, 같은 운세가 나옵니다.
"""
import datetime as dt
import hashlib
import random
from dataclasses import dataclass
from pathlib import Path

import settings
from core.tarot_cards import CARDS, ROMAN

KST = dt.timezone(dt.timedelta(hours=9))
CARD_DIR = Path(__file__).resolve().parent.parent / "data" / "cards"
POSITIONS = {1: ["오늘"], 2: ["지금", "흐름"], 3: ["시작", "과정", "결과"]}
REVERSED_CHANCE = 0.35


@dataclass
class DrawnCard:
    no: int
    ko: str
    en: str
    reversed: bool
    position: str
    loot: int
    party: int
    text: str

    @property
    def title(self):
        return f"{ROMAN[self.no]}. {self.ko}" + (" (역방향)" if self.reversed else "")

    @property
    def image_path(self):
        """data/cards/NN.jpg (없으면 None)"""
        for ext in ("jpg", "png", "jpeg", "webp"):
            p = CARD_DIR / f"{self.no:02d}.{ext}"
            if p.exists():
                return p
        return None


@dataclass
class Reading:
    user_key: str
    date: dt.date
    cards: list
    loot: int              # 득템운 %
    loot_comment: str
    party_score: float
    party_title: str
    party_comment: str
    channels: dict         # 서버 -> 채널 번호

    @property
    def stars(self):
        n = max(1, min(5, round(self.loot / 20)))
        return "★" * n + "☆" * (5 - n)


def today_kst():
    return dt.datetime.now(KST).date()


def _rng(user_key, date):
    seed = hashlib.sha256(f"{user_key}|{date.isoformat()}|mabi-tarot".encode()).hexdigest()
    return random.Random(int(seed, 16))


def _loot_comment(p):
    if p >= 90:
        return "대박 예감! 미뤄둔 인챈트·세공을 질러도 좋은 날이에요."
    if p >= 70:
        return "운이 따르는 날. 평소보다 한 번 더 돌아도 좋아요."
    if p >= 50:
        return "무난한 하루. 욕심만 부리지 않으면 본전 이상은 해요."
    if p >= 30:
        return "조금 아쉬운 날. 큰 도박보다는 꾸준한 사냥 위주로."
    return "오늘은 쉬어가는 날. 강화·인챈트는 내일로 미루세요."


def _party(score):
    if score >= 1.5:
        return "🎉 최고의 파티운", "오늘 모인 파티는 손발이 척척! 먼저 파티를 모집해 보세요."
    if score >= 0.5:
        return "🤝 좋은 파티운", "좋은 파티를 만날 것 같아요. 모르는 파티에 들어가도 괜찮아요."
    if score > -0.5:
        return "🙂 무난한 파티운", "아는 사람과 파티하면 무난해요. 길드원에게 먼저 말 걸어보세요."
    if score > -1.5:
        return "🚶 솔플 추천", "오늘은 혼자 도는 게 속 편해요."
    return "🧘 무조건 솔플", "오늘 파티는 삐걱일 기운. 조용한 채널에서 솔플하세요."


def draw(user_key, date=None):
    date = date or today_kst()
    rng = _rng(str(user_key), date)

    n = rng.choice([1, 2, 3])
    picks = rng.sample(range(len(CARDS)), n)
    cards = []
    for pos, idx in zip(POSITIONS[n], picks):
        c = CARDS[idx]
        rev = rng.random() < REVERSED_CHANCE
        side = c["rev"] if rev else c["up"]
        cards.append(DrawnCard(c["no"], c["ko"], c["en"], rev, pos,
                               side["loot"], side["party"], side["text"]))

    loot_avg = sum(c.loot for c in cards) / n
    loot = round(50 + loot_avg * 14 + rng.uniform(-6, 6))
    loot = max(3, min(99, loot))

    party_score = sum(c.party for c in cards) / n
    party_title, party_comment = _party(party_score)

    channels = {srv: rng.choice(chs) for srv, chs in settings.CHANNELS.items() if chs}

    return Reading(str(user_key), date, cards, loot, _loot_comment(loot),
                   party_score, party_title, party_comment, channels)
