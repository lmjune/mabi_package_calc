# -*- coding: utf-8 -*-
"""뽑은 카드들을 한 장의 PNG로 합치기 (역방향은 뒤집어서)"""
import io

from PIL import Image, ImageDraw, ImageFont

from core.tarot_cards import ROMAN

W, H, GAP, PAD = 240, 414, 18, 20
BG = (22, 17, 42)
GOLD = (232, 196, 106)


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:          # 오래된 Pillow
        return ImageFont.load_default()


def _fallback(card):
    """이미지 파일이 없을 때 쓰는 기본 카드 앞면"""
    im = Image.new("RGB", (W, H), (246, 238, 219))
    d = ImageDraw.Draw(im)
    d.rectangle([6, 6, W - 7, H - 7], outline=GOLD, width=6)
    d.text((W / 2, H / 2 - 30), ROMAN[card.no], fill=(58, 42, 107), font=_font(56), anchor="mm")
    d.text((W / 2, H / 2 + 40), card.en, fill=(58, 42, 107), font=_font(20), anchor="mm")
    return im


def _back():
    im = Image.new("RGB", (W, H), (44, 32, 84))
    d = ImageDraw.Draw(im)
    for x in range(-H, W, 16):
        d.line([(x, 0), (x + H, H)], fill=(58, 42, 107), width=6)
    d.rectangle([3, 3, W - 4, H - 4], outline=GOLD, width=6)
    d.ellipse([W / 2 - 14, H / 2 - 14, W / 2 + 14, H / 2 + 14], fill=GOLD)
    return im


def _face(card):
    p = card.image_path
    try:
        im = Image.open(p).convert("RGB").resize((W, H)) if p else _fallback(card)
    except Exception:
        im = _fallback(card)
    if card.reversed:
        im = im.rotate(180)
    return im


def compose(cards, total_slots=None):
    """cards: 공개된 카드들 / total_slots: 전체 장수(남은 자리는 뒷면으로)"""
    n = max(total_slots or len(cards), 1)
    canvas = Image.new("RGB", (PAD * 2 + W * n + GAP * (n - 1), PAD * 2 + H), BG)
    for i in range(n):
        im = _face(cards[i]) if i < len(cards) else _back()
        canvas.paste(im, (PAD + i * (W + GAP), PAD))
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    buf.seek(0)
    return buf
