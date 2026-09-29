# -*- coding: utf-8 -*-
"""웹(Streamlit)용 득템운 화면 — 뒷면 카드를 클릭하면 뒤집히는 연출"""
import base64
import json

from core.tarot import Reading
from core.tarot_cards import ROMAN


def _img_src(card):
    p = card.image_path
    if not p:
        return None
    mime = "image/png" if p.suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def build_html(r: Reading) -> str:
    cards = [{
        "roman": ROMAN[c.no], "ko": c.ko, "en": c.en, "rev": c.reversed, "pos": c.position,
        "text": c.text, "img": _img_src(c),
    } for c in r.cards]
    result = {
        "loot": r.loot, "stars": r.stars, "lootComment": r.loot_comment,
        "partyTitle": r.party_title, "partyComment": r.party_comment,
        "channels": r.channels, "date": r.date.strftime("%Y.%m.%d"),
    }
    data = json.dumps({"user": r.user_key, "cards": cards, "result": result}, ensure_ascii=False)
    data = data.replace("</", "<\\/")   # <script> 안전
    return TEMPLATE.replace("__DATA__", data)


TEMPLATE = r"""
<!doctype html><html><head><meta charset="utf-8">
<style>
  :root { --bg:#16112a; --panel:#221a3d; --gold:#e8c46a; --ink:#f3ecff; --muted:#b8a9d9; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font-family:"Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif; }
  .wrap { padding:18px 12px 28px; }
  .head { text-align:center; margin-bottom:14px; }
  .head h2 { margin:0 0 4px; font-size:20px; color:var(--gold); letter-spacing:1px; }
  .head p { margin:0; color:var(--muted); font-size:14px; }
  .table { display:flex; justify-content:center; gap:10px; flex-wrap:nowrap; perspective:1000px; }
  .card { width:min(18vw,120px); aspect-ratio:0.58; position:relative; cursor:pointer;
          transform-style:preserve-3d; transition:transform .8s cubic-bezier(.2,.8,.2,1), opacity .5s;
          opacity:0; transform:translateY(40px) rotateZ(-6deg); }
  .card.in { opacity:1; transform:none; }
  .card.in:hover:not(.flipped):not(.done) { transform:translateY(-8px); }
  .card.flipped { transform:rotateY(180deg); cursor:default; }
  .card.done { opacity:.18; pointer-events:none; }
  .face { position:absolute; inset:0; border-radius:10px; backface-visibility:hidden; overflow:hidden;
          box-shadow:0 6px 18px rgba(0,0,0,.45); }
  .back { background:
            radial-gradient(circle at 50% 50%, #e8c46a 0 7%, transparent 8%),
            repeating-linear-gradient(45deg, #3a2a6b 0 8px, #2c2054 8px 16px);
          border:3px solid var(--gold); }
  .back::after { content:"✦"; position:absolute; inset:0; display:grid; place-items:center;
                 color:#16112a; font-size:18px; }
  .front { transform:rotateY(180deg); background:#f6eedb; border:3px solid var(--gold); }
  .front img { width:100%; height:100%; object-fit:cover; display:block; }
  .front .fallback { height:100%; display:flex; flex-direction:column; align-items:center;
          justify-content:center; gap:6px; color:#3a2a6b; padding:6px; text-align:center;
          background:linear-gradient(160deg,#fff7e0,#e9d9b4); }
  .fallback .rn { font-size:26px; font-weight:800; }
  .fallback .ko { font-size:15px; font-weight:700; }
  .fallback .en { font-size:10px; opacity:.7; }
  .rev .front img, .rev .front .fallback { transform:rotate(180deg); }
  .readings { margin:18px auto 0; max-width:640px; display:flex; flex-direction:column; gap:10px; }
  .rd { background:var(--panel); border-left:4px solid var(--gold); border-radius:8px; padding:10px 14px;
        opacity:0; transform:translateY(10px); transition:all .5s; }
  .rd.show { opacity:1; transform:none; }
  .rd b { color:var(--gold); }
  .rd .tag { font-size:12px; color:var(--muted); margin-right:6px; }
  .result { margin:18px auto 0; max-width:640px; background:linear-gradient(160deg,#2b2150,#1d1636);
            border:1px solid #4a3a82; border-radius:12px; padding:16px; display:none; }
  .result.show { display:block; animation:pop .6s ease; }
  @keyframes pop { from{opacity:0; transform:scale(.96)} to{opacity:1; transform:none} }
  .big { font-size:40px; font-weight:800; color:var(--gold); }
  .bar { height:10px; background:#3a2d66; border-radius:6px; overflow:hidden; margin:6px 0 4px; }
  .bar i { display:block; height:100%; width:0; background:linear-gradient(90deg,#8f6bff,#e8c46a);
           transition:width 1.2s ease; }
  .sec { margin-top:14px; }
  .sec h4 { margin:0 0 4px; font-size:14px; color:var(--muted); font-weight:600; }
  .chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:6px; }
  .chip { background:#3a2d66; border:1px solid #5b4a99; border-radius:999px; padding:6px 12px; font-size:14px; }
  .chip b { color:var(--gold); }
  .muted { color:var(--muted); font-size:13px; }
</style></head><body><div class="wrap">
  <div class="head">
    <h2>🔮 오늘의 득템운</h2>
    <p id="guide"></p>
  </div>
  <div class="table" id="table"></div>
  <div class="readings" id="readings"></div>
  <div class="result" id="result"></div>
</div>
<script>
const D = __DATA__;
const N = D.cards.length;
let picked = 0;
const esc = s => String(s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const guide = document.getElementById('guide');
const table = document.getElementById('table');
function setGuide(){ guide.textContent = picked < N
  ? `${D.user}님, 카드 ${N}장이 당신을 부르고 있어요. 마음이 가는 카드를 골라주세요 (${picked}/${N})`
  : `${D.result.date} · ${D.user}님의 운세 (오늘 하루 동안 같은 결과예요)`; }
setGuide();

for (let i = 0; i < 5; i++) {
  const el = document.createElement('div');
  el.className = 'card';
  el.innerHTML = '<div class="face back"></div><div class="face front"></div>';
  el.onclick = () => pick(el);
  table.appendChild(el);
  setTimeout(() => el.classList.add('in'), 120 + i * 140);
}

function front(c){
  return c.img ? `<img src="${c.img}" alt="${esc(c.ko)}">`
    : `<div class="fallback"><div class="rn">${c.roman}</div><div class="ko">${esc(c.ko)}</div><div class="en">${esc(c.en)}</div></div>`;
}

function pick(el){
  if (picked >= N || el.classList.contains('flipped')) return;
  const c = D.cards[picked++];
  el.querySelector('.front').innerHTML = front(c);
  if (c.rev) el.classList.add('rev');
  el.classList.add('flipped');
  const rd = document.createElement('div');
  rd.className = 'rd';
  rd.innerHTML = `<span class="tag">${esc(c.pos)}</span><b>${c.roman}. ${esc(c.ko)}${c.rev ? ' (역방향)' : ''}</b><br>${esc(c.text)}`;
  document.getElementById('readings').appendChild(rd);
  setTimeout(() => rd.classList.add('show'), 500);
  setGuide();
  if (picked === N) setTimeout(finish, 1100);
}

function finish(){
  document.querySelectorAll('.card:not(.flipped)').forEach(e => e.classList.add('done'));
  const R = D.result;
  const chips = Object.entries(R.channels).map(([s, ch]) => `<span class="chip">${esc(s)} <b>${ch}채널</b></span>`).join('')
              || '<span class="muted">설정된 채널이 없어요</span>';
  const box = document.getElementById('result');
  box.innerHTML = `
    <div class="sec" style="margin-top:0"><h4>득템운</h4>
      <span class="big">${R.loot}%</span> <span style="color:#e8c46a;font-size:20px">${R.stars}</span>
      <div class="bar"><i id="fill"></i></div><div>${esc(R.lootComment)}</div></div>
    <div class="sec"><h4>파티운</h4><div style="font-size:18px;font-weight:700">${esc(R.partyTitle)}</div>
      <div>${esc(R.partyComment)}</div></div>
    <div class="sec"><h4>행운의 채널</h4><div class="chips">${chips}</div></div>
    <div class="sec muted">재미로 보는 운세예요. 결과는 내일 자정(한국 시간)에 바뀌어요.</div>`;
  box.classList.add('show');
  setTimeout(() => document.getElementById('fill').style.width = R.loot + '%', 100);
}
</script></body></html>
"""
