# 📔 모험가 수첩 — 마비노기 경매장 계산기 + 길드 디스코드 봇

- **웹 (Streamlit)** — 경매장 합산 · 패키지 효율 · 오늘의 득템운
- **디스코드 봇** — `/득템운` `/시세` `/합산` `/패키지` `/스팀할인` `/메뉴` `/봇상태` (허용한 서버에서만 동작)

계산 로직은 `core/`에 한 벌만 있고, 웹과 봇이 같이 씁니다.

```
app.py              웹 화면 (Streamlit)
tarot_view.py       웹 득템운 카드 뽑기 연출
settings.py         ★ 직접 고치는 설정 (채널 목록, 패키지, 기본값)
core/auction.py     넥슨 API 조회 · 공유 캐시 · 합산 · 패키지 계산
core/tarot.py       득템운 계산 (사용자+날짜로 하루 고정)
core/tarot_cards.py 타로 22장 해석·점수 (고쳐도 됨)
core/steam.py      스팀 할인 목록
core/menus.py      ★ 점심·저녁 메뉴 목록 (고쳐도 됨)
bot/main.py         디스코드 봇
bot/card_image.py   뽑은 카드 이미지 합치기
data/cards/         카드 이미지 00.jpg ~ 21.jpg
tools/download_cards.py  카드 이미지 받는 스크립트
deploy/mabi-bot.service  리눅스 서버용 자동 실행 설정
```

---

## 1. 처음 한 번: 설정과 카드 이미지

1. `settings.py`의 `CHANNELS`에 서버별 채널 목록을 넣어요.
   ```python
   CHANNELS = {"류트": [1, 2, 4], "울프": [1, 3], "하프": [2, 5], "만돌린": [1, 2]}
   ```
2. 카드 이미지를 받아요 (라이더-웨이트 1909년판, 저작권 만료). 인터넷 되는 PC에서:
   ```
   pip install requests
   python tools/download_cards.py
   ```
   `data/cards/`에 22장이 생기면 GitHub에 같이 올려요. 이미지가 없어도 동작은 하고, 숫자·이름만 적힌 기본 카드로 보여요.

## 2. 웹 (Streamlit) 업데이트

지금처럼 push만 하면 돼요. Main file은 그대로 `app.py`.
```
git add .
git commit -m "득템운, 봇 추가"
git push
```

## 3. 디스코드 봇 만들기

### 3-1. 봇 등록 (Discord Developer Portal)
1. https://discord.com/developers/applications → **New Application** → 이름 입력.
2. 왼쪽 **Bot** 메뉴
   - **Reset Token** → 나온 토큰을 복사해 둬요 (`DISCORD_TOKEN`). 다시는 안 보여주니 잘 보관.
   - **Public Bot** 끄기 → 나만 봇을 초대할 수 있어요.
   - Privileged Gateway Intents는 전부 꺼둬도 돼요.
3. 왼쪽 **OAuth2 → URL Generator**
   - Scopes: `bot`, `applications.commands`
   - Bot Permissions: `Send Messages`, `Embed Links`, `Attach Files`
   - 맨 아래 URL을 열어서 길드 디스코드 서버에 초대.
4. 서버 ID 복사: 디스코드 **설정 → 고급 → 개발자 모드** 켜기 → 서버 이름 우클릭 → **서버 ID 복사** (`ALLOWED_GUILD_IDS`).

### 3-2. 내 PC에서 먼저 테스트 (Windows)
```
cd C:\mabi_package_calc
python -m venv .venv
.venv\Scripts\activate
pip install -r bot\requirements.txt
copy .env.example .env
notepad .env          ← 토큰, API 키, 서버 ID 입력
python -m bot.main
```
`로그인: ...` 과 `서버 ... 에 명령어 5개 등록`이 나오면 성공. 디스코드에서 `/`를 치면 명령어가 보여요.
(명령어가 안 보이면 디스코드를 Ctrl+R로 새로고침)

### 3-3. 24시간 켜두기 — Railway (추천)
저장소의 `Dockerfile`, `railway.json`을 Railway가 자동으로 읽어요.
1. https://railway.com → **New Project → Deploy from GitHub repo** → `mabi_package_calc` 선택
   (처음이면 GitHub 연결 권한 허용)
2. 만들어진 서비스 클릭 → **Variables** 탭 → 3개 추가
   `DISCORD_TOKEN`, `NEXON_API_KEY`, `ALLOWED_GUILD_IDS`
3. 변수를 저장하면 자동으로 다시 배포돼요. **Deployments → View Logs**에
   `로그인: ...`, `서버 ... 에 명령어 5개 등록`이 보이면 성공.
4. 이후엔 GitHub에 push만 하면 봇도 자동으로 업데이트돼요.

### 3-3b. 24시간 켜두기 — 직접 리눅스 서버 (Oracle 등)
Oracle Cloud 무료 VM, 저가 VPS 등 어디든 Ubuntu 기준:
```bash
sudo apt update && sudo apt install -y python3-venv git
git clone https://github.com/lmjune/mabi_package_calc.git
cd mabi_package_calc
python3 -m venv .venv
.venv/bin/pip install -r bot/requirements.txt
cp .env.example .env && nano .env        # 값 채우기
.venv/bin/python -m bot.main             # 한 번 실행해서 확인 후 Ctrl+C

# 자동 실행 등록 (파일 안의 User·경로를 먼저 확인)
sudo cp deploy/mabi-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now mabi-bot
sudo systemctl status mabi-bot           # 상태 확인
journalctl -u mabi-bot -f                # 로그 보기
```

### 3-4. 코드 고친 뒤 봇 업데이트 (직접 서버일 때)
```bash
cd mabi_package_calc && git pull && sudo systemctl restart mabi-bot
```

---

## 봇 명령어

| 명령어 | 설명 |
|---|---|
| `/득템운` | 뒷면 카드 5장 중 골라서 뽑기 → 득템운·파티운·서버별 행운의 채널. 사람마다 하루 동안 결과 고정 |
| `/시세 아이템:` | 아이템 최저가 (최근 1시간 거래 + 현재 매물). 이름 일부만 넣어도 찾아주고, 여러 개면 목록에서 고르기 |
| `/합산` | 입력창에 `이름, 수량` 목록 → 합계·수수료 제외 금액 |
| `/패키지` | `settings.py`의 패키지로 효율 계산. 개수·적립률·시세 입력 가능 |
| `/스팀할인` | 스팀 한국 스토어 할인 목록. 정렬(인기순·평가순·낮은 가격순·최신순), 최소할인. 검색어를 넣으면 할인 안 하는 게임도 가격과 함께 나와요. 10개씩 페이지 넘김 |
| `/메뉴` | 점심·저녁 메뉴 추천. 혼밥·종류·예산·제외 조건, 🔄 다시 뽑기 / ✅ 결정, `투표:True`면 후보 3개 투표 |
| `/봇상태` | 오늘 API 호출 수, 캐시 상태 (나만 보임) |

`나만보기:True`를 붙이면 결과가 나에게만 보여요.

## 넥슨 API 사용량

- 개발 단계 키는 **하루 1,000건, 초당 5건**. 패키지 계산 1번 ≈ 18~36건.
- 같은 아이템은 **10분 동안 모두가 결과를 같이 써서** 여러 명이 연달아 조회해도 호출이 늘지 않아요.
- 하루 950건을 넘기면 새 조회를 막고 안내해요. (`settings.py`에서 조정)
- 웹과 봇이 **같은 API 키를 쓰면 한도도 같이 줄어요.** 호출 수는 각 프로그램이 따로 세기 때문에 실제 사용량은 둘을 합한 값이에요.
- 한도가 부족하면 넥슨 오픈API에서 서비스 단계 전환을 신청해야 해요.