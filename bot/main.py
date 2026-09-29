# -*- coding: utf-8 -*-
"""
마비노기 길드 디스코드 봇
  /득템운  /시세  /합산  /패키지  /스팀할인  /봇상태

실행:  python -m bot.main      (저장소 맨 위 폴더에서)
필요한 환경변수(.env): DISCORD_TOKEN, NEXON_API_KEY, ALLOWED_GUILD_IDS
"""
import asyncio
import logging
import os
import sys
from pathlib import Path

import discord
from discord import app_commands

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import settings                                   # noqa: E402
from core import auction, steam, tarot            # noqa: E402
from bot.card_image import compose                # noqa: E402

log = logging.getLogger("mabi-bot")


# ============================== 설정 읽기 ==============================
def load_env():
    """.env 파일(KEY=VALUE)을 환경변수로 읽기"""
    for path in (ROOT / ".env", ROOT / "bot" / ".env"):
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
TOKEN = os.environ.get("DISCORD_TOKEN", "")
NEXON_KEY = os.environ.get("NEXON_API_KEY", "")
ALLOWED_GUILDS = {int(x) for x in os.environ.get("ALLOWED_GUILD_IDS", "").replace(" ", "").split(",") if x}

GOLD_COLOR = 0xE8C46A
PURPLE = 0x6B4FD8


# ============================== 봇 본체 ==============================
class GuildOnlyTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id in ALLOWED_GUILDS:
            return True
        await interaction.response.send_message("이 봇은 허용된 서버에서만 쓸 수 있어요.", ephemeral=True)
        return False


class MabiBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = GuildOnlyTree(self)

    async def setup_hook(self):
        # 명령어는 허용된 서버에만 등록 (전체 공개 등록은 하지 않음)
        for gid in ALLOWED_GUILDS:
            guild = discord.Object(id=gid)
            self.tree.copy_global_to(guild=guild)
            try:
                cmds = await self.tree.sync(guild=guild)
                log.info("서버 %s 에 명령어 %d개 등록", gid, len(cmds))
            except discord.Forbidden:
                log.error("서버 %s 에 명령어를 등록하지 못했어요 (Missing Access). "
                          "① 봇이 그 서버에 초대됐는지 ② 서버 ID가 맞는지 "
                          "③ 초대 링크에 applications.commands 스코프가 있었는지 확인해 주세요. "
                          "초대한 뒤 봇을 재시작하면 등록돼요.", gid)

    async def on_ready(self):
        log.info("로그인: %s", self.user)
        for g in self.guilds:
            if g.id not in ALLOWED_GUILDS:
                log.warning("허용되지 않은 서버에서 나감: %s (%s)", g.name, g.id)
                await g.leave()

    async def on_guild_join(self, guild):
        if guild.id not in ALLOWED_GUILDS:
            log.warning("허용되지 않은 서버 초대 → 나감: %s (%s)", guild.name, guild.id)
            await guild.leave()


bot = MabiBot()
tree = bot.tree


async def run_blocking(func, *args, **kw):
    """넥슨 API 조회는 시간이 걸려서 별도 스레드에서 실행"""
    return await asyncio.to_thread(func, *args, **kw)


def error_text(e):
    if isinstance(e, (auction.QuotaExceeded, auction.ApiError)):
        return f"⚠️ {e}"
    log.exception("처리 중 오류", exc_info=e)
    return "⚠️ 처리 중 오류가 났어요. 잠시 후 다시 해주세요."


def clip(text, limit=1000):
    return text if len(text) <= limit else text[: limit - 20] + "\n… (생략)"


# ============================== /득템운 ==============================
_drawn_today = set()          # (user_id, 날짜) — 오늘 이미 뽑은 사람은 바로 결과를 보여줌


def fortune_embed(r, name, again=False):
    e = discord.Embed(title=f"🔮 {name}님의 오늘의 득템운", color=GOLD_COLOR if r.loot >= 50 else PURPLE)
    e.description = "\n\n".join(f"`{c.position}` **{c.title}**\n{c.text}" for c in r.cards)
    e.add_field(name="득템운", value=f"**{r.loot}%** {r.stars}\n{r.loot_comment}", inline=False)
    e.add_field(name="파티운", value=f"**{r.party_title}**\n{r.party_comment}", inline=False)
    if r.channels:
        e.add_field(name="🍀 행운의 채널",
                    value="  ".join(f"{srv} **{ch}채널**" for srv, ch in r.channels.items()), inline=False)
    e.set_image(url="attachment://cards.png")
    e.set_footer(text=("오늘 이미 뽑은 결과예요. " if again else "")
                 + f"{r.date:%Y.%m.%d} · 재미로 보는 운세 · 자정(한국 시간)에 바뀌어요")
    return e


class PickView(discord.ui.View):
    def __init__(self, reading, owner, name):
        super().__init__(timeout=180)
        self.r, self.owner, self.name = reading, owner, name
        self.revealed = []
        self.message = None
        for i in range(5):
            btn = discord.ui.Button(label="🂠", style=discord.ButtonStyle.secondary, custom_id=f"pick{i}")
            btn.callback = self._make_cb(btn)
            self.add_item(btn)

    def progress_embed(self):
        n = len(self.r.cards)
        e = discord.Embed(title=f"🔮 {self.name}님의 오늘의 득템운", color=PURPLE)
        e.description = (f"카드 **{n}장**이 당신을 부르고 있어요. 마음이 가는 카드를 골라주세요 "
                         f"({len(self.revealed)}/{n})")
        for c in self.revealed:
            e.add_field(name=f"`{c.position}` {c.title}", value=c.text, inline=False)
        e.set_image(url="attachment://cards.png")
        return e

    def image(self):
        return discord.File(compose(self.revealed, len(self.r.cards)), filename="cards.png")

    def _make_cb(self, btn):
        async def cb(interaction: discord.Interaction):
            if interaction.user.id != self.owner.id:
                await interaction.response.send_message("다른 사람의 카드예요. `/득템운`으로 직접 뽑아보세요!",
                                                        ephemeral=True)
                return
            card = self.r.cards[len(self.revealed)]
            self.revealed.append(card)
            btn.label = card.ko + (" ↺" if card.reversed else "")
            btn.style = discord.ButtonStyle.primary
            btn.disabled = True
            if len(self.revealed) == len(self.r.cards):
                await self._finish(interaction)
            else:
                await interaction.response.edit_message(embed=self.progress_embed(),
                                                        attachments=[self.image()], view=self)
        return cb

    async def _finish(self, interaction=None):
        self.stop()
        self.revealed = list(self.r.cards)
        for item in self.children:
            item.disabled = True
        _drawn_today.add((self.owner.id, self.r.date))
        kw = dict(embed=fortune_embed(self.r, self.name), view=self,
                  attachments=[discord.File(compose(self.r.cards), filename="cards.png")])
        if interaction:
            await interaction.response.edit_message(**kw)
        elif self.message:
            await self.message.edit(**kw)

    async def on_timeout(self):
        try:
            await self._finish()           # 3분 동안 안 고르면 자동 공개
        except discord.HTTPException:
            pass


@tree.command(name="득템운", description="타로 카드로 오늘의 득템운·파티운·행운의 채널을 봐요 (하루 동안 고정)")
async def cmd_fortune(interaction: discord.Interaction):
    r = tarot.draw(interaction.user.id)
    name = interaction.user.display_name
    if (interaction.user.id, r.date) in _drawn_today:
        await interaction.response.send_message(
            embed=fortune_embed(r, name, again=True),
            file=discord.File(compose(r.cards), filename="cards.png"))
        return

    await interaction.response.send_message(embed=discord.Embed(
        title=f"🔮 {name}님의 오늘의 득템운", description="카드를 섞는 중… 🃏🃏🃏", color=PURPLE))
    await asyncio.sleep(1.5)
    view = PickView(r, interaction.user, name)
    view.message = await interaction.edit_original_response(
        embed=view.progress_embed(), attachments=[view.image()], view=view)


# ============================== /시세 ==============================
_recent_items = []


def remember_item(name):
    if name in _recent_items:
        _recent_items.remove(name)
    _recent_items.insert(0, name)
    del _recent_items[50:]


def known_items():
    names = list(_recent_items)
    for p in settings.PACKAGES.values():
        items, _ = auction.parse_items(p["items"])
        for cands, _ in items:
            names += [c for c in cands if c not in names]
    return names


async def item_autocomplete(interaction, current: str):
    cur = current.replace(" ", "")
    hits = [n for n in known_items() if cur in n.replace(" ", "")]
    return [app_commands.Choice(name=n[:100], value=n[:100]) for n in hits[:25]]


@tree.command(name="시세", description="아이템 하나의 경매장 최저가 (최근 1시간 거래 · 현재 매물)")
@app_commands.describe(아이템="경매장에 표시되는 정확한 이름", 나만보기="결과를 나에게만 보여주기")
@app_commands.autocomplete(아이템=item_autocomplete)
async def cmd_quote(interaction: discord.Interaction, 아이템: str, 나만보기: bool = False):
    await interaction.response.defer(thinking=True, ephemeral=나만보기)
    try:
        q = await run_blocking(auction.quote, NEXON_KEY, 아이템.strip())
    except Exception as e:
        await interaction.followup.send(error_text(e))
        return
    if q.trade_min is None and q.list_min is None:
        await interaction.followup.send(f"🔍 **{아이템}** 은(는) 거래 내역도 매물도 없어요. 이름을 정확히 입력했는지 확인해 주세요.")
        return
    remember_item(q.item_name)
    e = discord.Embed(title=f"🔍 {q.item_name}", color=GOLD_COLOR)
    e.add_field(name="최근 1시간 거래 최저가",
                value=f"**{q.trade_min:,}** 골드\n({q.trade_count}건)" if q.trade_min is not None else "거래 없음")
    e.add_field(name="현재 매물 최저가",
                value=f"**{q.list_min:,}** 골드\n({q.list_count}건)" if q.list_min is not None else "매물 없음")
    e.set_footer(text="게임보다 평균 10분 늦게 반영돼요")
    await interaction.followup.send(embed=e)


# ============================== /합산 ==============================
class SumModal(discord.ui.Modal, title="경매장 합산"):
    items = discord.ui.TextInput(
        label="아이템 목록 (한 줄에: 이름, 수량)", style=discord.TextStyle.paragraph, max_length=4000,
        placeholder="기억의 보석, 10\n보호의 6단계 푸른 개조석 | 보호의 6단계 붉은 개조석, 2")

    def __init__(self, private):
        super().__init__()
        self.private = private

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=self.private)
        items, errors = auction.parse_items(self.items.value)
        if not items:
            await interaction.followup.send("아이템 목록이 비어 있어요." + ("\n" + "\n".join(errors) if errors else ""))
            return
        try:
            res = await run_blocking(auction.price_items, NEXON_KEY, items, True)
        except Exception as e:
            await interaction.followup.send(error_text(e))
            return
        net = round(res.total * (1 - settings.FEE_RATE))
        e = discord.Embed(title="🧮 경매장 합산", color=GOLD_COLOR)
        e.add_field(name="합계", value=f"**{auction.kgold(res.total)}** 골드\n`{res.total:,}`")
        e.add_field(name="판매 시 수령액 (수수료 4% 제외)", value=f"**{auction.kgold(net)}** 골드\n`{net:,}`")
        lines = [f"{r['아이템']} ×{r['수량']}  " + (f"{r['소계']:,}" if r["소계"] is not None else "가격 없음")
                 for r in res.rows]
        e.add_field(name="아이템별", value="```\n" + clip("\n".join(lines), 1000) + "\n```", inline=False)
        warn = []
        if res.missing:
            warn.append("⚠️ 가격을 못 찾아 합계에서 뺀 아이템: " + ", ".join(res.missing))
        warn += errors
        if warn:
            e.add_field(name="확인해 주세요", value=clip("\n".join(warn)), inline=False)
        await interaction.followup.send(embed=e)

    async def on_error(self, interaction, error):
        msg = error_text(error)
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


@tree.command(name="합산", description="여러 아이템의 경매장 최저가를 합산해요 (입력창이 열려요)")
@app_commands.describe(나만보기="결과를 나에게만 보여주기")
async def cmd_sum(interaction: discord.Interaction, 나만보기: bool = False):
    await interaction.response.send_modal(SumModal(나만보기))


# ============================== /패키지 ==============================
async def package_autocomplete(interaction, current: str):
    return [app_commands.Choice(name=n, value=n) for n in settings.PACKAGES if current in n][:25]


class DetailView(discord.ui.View):
    def __init__(self, text):
        super().__init__(timeout=600)
        self.text = text

    @discord.ui.button(label="구성품 전체 보기", style=discord.ButtonStyle.secondary)
    async def detail(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("```\n" + clip(self.text, 1900) + "\n```", ephemeral=True)


@tree.command(name="패키지", description="현금 패키지를 경매장에 되팔면 1000숲을 얼마에 사는 셈인지 계산해요")
@app_commands.describe(패키지="settings.py 에 등록된 패키지", 개수="구매 개수",
                       적립률="마일리지 적립률(%)", 시세="비교할 현금 1000숲 시세(원)",
                       나만보기="결과를 나에게만 보여주기")
@app_commands.autocomplete(패키지=package_autocomplete)
async def cmd_package(interaction: discord.Interaction, 패키지: str = settings.DEFAULT_PACKAGE,
                      개수: app_commands.Range[int, 1, 10000] = settings.DEFAULT_PACKAGE_COUNT,
                      적립률: app_commands.Range[float, 0, 100] = settings.DEFAULT_MILEAGE_RATE,
                      시세: app_commands.Range[int, 0, 10_000_000] = settings.DEFAULT_MARKET_WON,
                      나만보기: bool = False):
    preset = settings.PACKAGES.get(패키지)
    if not preset:
        await interaction.response.send_message(
            f"'{패키지}' 패키지가 없어요. 등록된 패키지: {', '.join(settings.PACKAGES)}", ephemeral=True)
        return
    await interaction.response.defer(thinking=True, ephemeral=나만보기)
    items, _ = auction.parse_items(preset["items"])
    try:
        res = await run_blocking(auction.price_items, NEXON_KEY, items, True)
    except Exception as e:
        await interaction.followup.send(error_text(e))
        return
    pr = auction.calc_package(패키지, res.total, preset["price"], 개수, 적립률,
                              settings.DEFAULT_MILEAGE_PER_1000, 시세)

    e = discord.Embed(title=f"📦 {패키지} × {개수:,}개", color=GOLD_COLOR)
    e.add_field(name="총 결제 금액", value=f"**{pr.pay_total:,}원**", inline=False)
    e.add_field(name="되팔면 (수수료 제외)", value=f"**{auction.kgold(pr.net_total)}** 골드")
    e.add_field(name=f"마일리지 {적립률:g}% 포함", value=f"**{auction.kgold(pr.net_total_m)}** 골드")
    vs = (lambda w: f"\n({w - 시세:+,}원 vs 시세)") if 시세 else (lambda w: "")
    e.add_field(name="1000숲을 얼마에 사는 셈?",
                value=f"마일리지 제외 **{pr.won_per:,}원**{vs(pr.won_per)}\n"
                      f"마일리지 포함 **{pr.won_per_m:,}원**{vs(pr.won_per_m)}", inline=False)
    verdict = pr.verdict()
    if verdict:
        e.add_field(name="판정", value=("✅ " if "싸게" in verdict else "❌ ") + verdict, inline=False)

    priced = sorted([r for r in res.rows if r["소계"]], key=lambda r: -r["소계"])
    top = "\n".join(f"{r['아이템']}  {r['소계'] / res.total:.0%}" for r in priced[:5]) if res.total else "-"
    e.add_field(name="가치 비중 TOP 5", value=clip(top), inline=False)
    if res.missing:
        e.add_field(name="⚠️ 가격 없음 (합계 제외, 결과가 실제보다 낮아요)", value=clip(", ".join(res.missing)),
                    inline=False)
    e.add_field(name="복사용", value="```\n" + pr.summary_lines() + "\n```", inline=False)
    e.set_footer(text=f"구성품 1개 기준 합계 {res.total:,} 골드 · 시세는 평균 10분 늦게 반영")

    detail = "\n".join(
        f"{r['아이템']} ×{r['수량']}: " + (f"{r['개당가']:,} → {r['소계']:,} ({r['출처']})"
                                          if r["소계"] is not None else "가격 없음")
        for r in res.rows)
    await interaction.followup.send(embed=e, view=DetailView(detail))


# ============================== /스팀할인 ==============================
STEAM_PAGE = 10
STEAM_COLOR = 0x1B2838


def _md(text):
    return text.replace("[", "(").replace("]", ")").replace("*", "").replace("_", " ")


class SteamView(discord.ui.View):
    def __init__(self, deals, total, title, searching=False):
        super().__init__(timeout=600)
        self.deals, self.total, self.title, self.page = deals, total, title, 0
        self.searching = searching
        self._sync()

    @property
    def pages(self):
        return max(1, -(-len(self.deals) // STEAM_PAGE))

    def embed(self):
        chunk = self.deals[self.page * STEAM_PAGE:(self.page + 1) * STEAM_PAGE]
        lines = []
        for i, d in enumerate(chunk, self.page * STEAM_PAGE + 1):
            if d.discount > 0:
                price = f"`-{d.discount}%` ~~{d.original}~~ → **{d.final}**"
            elif d.final:
                price = f"할인 없음 · **{d.final}**"
            else:
                price = "가격 정보 없음 (출시 예정 등)"
            line = f"**{i}. [{_md(d.name)}]({d.url})**\n{price}"
            if d.review:
                line += f" · {d.review}"
            lines.append(line)
        e = discord.Embed(title=self.title, color=STEAM_COLOR,
                          description="\n".join(lines) or (
                              "검색 결과가 없어요. 이름을 다르게 입력해 보세요." if self.searching
                              else "조건에 맞는 할인 게임이 없어요."))
        if chunk and chunk[0].image:
            e.set_thumbnail(url=chunk[0].image)
        scope = f"검색 결과 {self.total:,}개 중" if self.searching else f"스팀 전체 할인 {self.total:,}개 중"
        e.set_footer(text=f"{self.page + 1}/{self.pages} 페이지 · {scope} · 한국 스토어 기준 · 30분마다 갱신")
        return e

    def _sync(self):
        self.prev.disabled = self.page == 0
        self.next.disabled = self.page >= self.pages - 1

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._sync()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._sync()
        await interaction.response.edit_message(embed=self.embed(), view=self)


@tree.command(name="스팀할인", description="지금 스팀에서 할인 중인 게임 목록")
@app_commands.describe(정렬="목록 정렬 방식 (검색어가 있으면 기본은 관련도순)", 최소할인="이 할인율(%) 이상만",
                       검색어="게임 이름으로 찾기 (할인 안 하는 게임도 가격과 함께 나와요)",
                       나만보기="결과를 나에게만 보여주기")
@app_commands.choices(정렬=[app_commands.Choice(name=n, value=n) for n in steam.SORTS])
async def cmd_steam(interaction: discord.Interaction, 정렬: str = None,
                    최소할인: app_commands.Range[int, 0, 99] = 0, 검색어: str = "", 나만보기: bool = False):
    await interaction.response.defer(thinking=True, ephemeral=나만보기)
    keyword = 검색어.strip()
    sort = 정렬 or (None if keyword else "인기순")
    try:
        deals, total = await run_blocking(steam.fetch_deals, sort, 0, 20 if keyword else 50, keyword)
    except Exception as e:
        log.exception("스팀 조회 실패", exc_info=e)
        await interaction.followup.send("⚠️ 스팀 할인 목록을 가져오지 못했어요. 잠시 후 다시 해주세요.")
        return
    deals = [d for d in deals if d.discount >= 최소할인]
    if keyword:
        title = f"🎮 스팀 검색 · '{keyword}'" + (f" · {sort}" if sort else "")
    else:
        title = f"🎮 스팀 할인 · {sort}"
    if 최소할인:
        title += f" · {최소할인}% 이상 할인"
    view = SteamView(deals, total, title, searching=bool(keyword))
    await interaction.followup.send(embed=view.embed(), view=view if view.pages > 1 else discord.utils.MISSING)


# ============================== /봇상태 ==============================
@tree.command(name="봇상태", description="오늘 넥슨 API 사용량과 캐시 상태")
async def cmd_status(interaction: discord.Interaction):
    await interaction.response.send_message(
        f"오늘 API 호출: **{auction.budget.calls_today():,} / {settings.DAILY_CALL_LIMIT:,}**\n"
        f"캐시에 저장된 조회: {auction.cache_size()}개 (각 {settings.CACHE_TTL_SECONDS // 60}분 유지)",
        ephemeral=True)


# ============================== 실행 ==============================
def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    missing = [k for k, v in {"DISCORD_TOKEN": TOKEN, "NEXON_API_KEY": NEXON_KEY,
                              "ALLOWED_GUILD_IDS": ALLOWED_GUILDS}.items() if not v]
    if missing:
        sys.exit(f"환경변수가 필요해요 (PC는 .env 파일, Railway는 Variables 탭): {', '.join(missing)}")
    bot.run(TOKEN, log_handler=None)


if __name__ == "__main__":
    main()