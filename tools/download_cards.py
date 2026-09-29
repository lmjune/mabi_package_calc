# -*- coding: utf-8 -*-
"""
라이더-웨이트 타로(1909, 퍼블릭 도메인) 메이저 아르카나 22장을
위키미디어 공용에서 받아 data/cards/00.jpg ~ 21.jpg 로 저장해요.

한 번만 실행하고, 받은 이미지를 GitHub에 같이 올리면 됩니다.
    pip install requests
    python tools/download_cards.py
"""
import re
import sys
import time
from pathlib import Path

import requests

API = "https://commons.wikimedia.org/w/api.php"
OUT = Path(__file__).resolve().parent.parent / "data" / "cards"
WIDTH = 360          # 저장할 가로 크기(px)
HEADERS = {"User-Agent": "mabi-package-calc/1.0 (tarot card downloader; personal guild bot)"}


def find_file(no):
    """'RWS Tarot 06 ...' 형태의 파일 제목 찾기"""
    r = requests.get(API, headers=HEADERS, timeout=20, params={
        "action": "query", "format": "json", "list": "search", "srnamespace": 6,
        "srsearch": f'intitle:"RWS Tarot {no:02d}"', "srlimit": 20,
    })
    r.raise_for_status()
    titles = [x["title"] for x in r.json().get("query", {}).get("search", [])]
    pat = re.compile(rf"^File:RWS[ _]Tarot[ _]{no:02d}[ _].+\.(jpe?g|png)$", re.I)
    ok = [t for t in titles if pat.match(t)]
    return min(ok, key=len) if ok else None      # 가장 짧은(원본에 가까운) 이름


def thumb_url(title):
    r = requests.get(API, headers=HEADERS, timeout=20, params={
        "action": "query", "format": "json", "titles": title,
        "prop": "imageinfo", "iiprop": "url", "iiurlwidth": WIDTH,
    })
    r.raise_for_status()
    for page in r.json()["query"]["pages"].values():
        info = (page.get("imageinfo") or [{}])[0]
        return info.get("thumburl") or info.get("url")
    return None


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    failed = []
    for no in range(22):
        dest = OUT / f"{no:02d}.jpg"
        if dest.exists():
            print(f"{no:02d} 이미 있음")
            continue
        try:
            title = find_file(no)
            url = thumb_url(title) if title else None
            if not url:
                raise RuntimeError("파일을 못 찾음")
            img = requests.get(url, headers=HEADERS, timeout=30)
            img.raise_for_status()
            dest.write_bytes(img.content)
            print(f"{no:02d} 저장 ← {title}")
        except Exception as e:
            failed.append(no)
            print(f"{no:02d} 실패: {e}")
        time.sleep(0.5)
    if failed:
        print("\n실패한 번호:", failed, "— 다시 실행하거나 직접 data/cards/NN.jpg 로 넣어주세요.")
        sys.exit(1)
    print("\n완료! data/cards 폴더를 GitHub에 올려주세요.")


if __name__ == "__main__":
    main()
