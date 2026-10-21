"""홈 화면 지도: 지역을 누르면 확대되고, 그 지역의 장소·음식·체험 카드가 나옵니다.

- 지도와 카드는 브라우저 안에서 움직입니다(클릭할 때마다 서버를 부르지 않습니다).
- 데이터는 region_data.json (build_region_data.py 로 만듭니다).
"""

import json
import math
from html import escape

from korea_map import KOREA_OUTLINE_D

LON0, LAT0 = 124.0, 38.8
SCALE = 46.0
K = 0.8039  # cos(36.5도), 위도에 따른 가로 비율 보정
FULL_VIEW = (10.0, 0.0, 290.0, 272.0)
VIEW_W = 92.0  # 지역을 눌렀을 때 보이는 가로 폭


def proj(lon: float, lat: float) -> tuple[float, float]:
    return ((lon - LON0) * K * SCALE, (LAT0 - lat) * SCALE)


MIN_PIN_GAP = 13.0  # 점 사이 최소 간격(지도 단위). 이보다 가까우면 살짝 벌립니다.
MAX_SHIFT = 12.0  # 한 점이 실제 위치에서 벗어날 수 있는 최대 거리(지도 단위)


def spread(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """가까운 점끼리 서로 밀어내서 겹치지 않게 합니다. 실제 위치에서 많이 벗어나지 않게 제한합니다."""
    pos = [list(p) for p in points]
    base = [tuple(p) for p in points]
    for _ in range(300):
        moved = False
        for i in range(len(pos)):
            for j in range(i + 1, len(pos)):
                dx = pos[j][0] - pos[i][0]
                dy = pos[j][1] - pos[i][1]
                d = math.hypot(dx, dy)
                if d >= MIN_PIN_GAP:
                    continue
                if d < 1e-6:
                    dx, dy, d = 1.0, 0.0, 1.0
                push = (MIN_PIN_GAP - d) / 2
                ux, uy = dx / d, dy / d
                pos[i][0] -= ux * push
                pos[i][1] -= uy * push
                pos[j][0] += ux * push
                pos[j][1] += uy * push
                moved = True
        for k in range(len(pos)):
            bx, by = base[k]
            sx, sy = pos[k][0] - bx, pos[k][1] - by
            s = math.hypot(sx, sy)
            if s > MAX_SHIFT:
                pos[k][0] = bx + sx / s * MAX_SHIFT
                pos[k][1] = by + sy / s * MAX_SHIFT
        if not moved:
            break
    return [(p[0], p[1]) for p in pos]


def _with_local_photos(region: dict) -> dict:
    """앱 폴더에 저장한 사진(local)이 있으면 카드와 확대 창 모두 그 사진을 쓰게 합니다."""
    out = dict(region)
    for kind in ("places", "foods", "activities"):
        items = []
        for item in region.get(kind, []):
            photo = item.get("photo")
            if photo and photo.get("local"):
                item = {**item, "photo": {**photo, "thumb": photo["local"], "full": photo["local"]}}
            items.append(item)
        out[kind] = items
    return out


def build_map_html(regions: list[dict]) -> str:
    regions = [_with_local_photos(r) for r in regions]
    base = [proj(r["lon"], r["lat"]) for r in regions]
    placed = spread(base)
    pins = []
    shifted = []
    for i, (r, (x, y)) in enumerate(zip(regions, placed)):
        shifted.append({**r, "px": round(x, 2), "py": round(y, 2)})
        pins.append(
            f'<g class="pin" data-i="{i}" role="button" tabindex="0" aria-label="{escape(r["name"])} 보기">'
            f'<circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="9"/>'
            f'<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="2.5"/>'
            f'<text data-bx="{x:.2f}" data-by="{y:.2f}" x="{x + 5:.1f}" y="{y + 3:.1f}" font-size="9">{escape(r["name"])}</text></g>'
        )
    data_json = json.dumps(
        {"regions": shifted, "full": FULL_VIEW, "viewW": VIEW_W},
        ensure_ascii=False,
    ).replace("</", "<\\/")

    return f"""<!doctype html>
<html><head><meta charset="utf-8">
<style>
  :root {{ --blue: #3182F6; --soft: #E8F3FF; --text: #191F28; --sub: #8B95A1; --card: #FFFFFF; --bg: #F2F4F6; --note: #4E5968; --link: #1B64DA; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --blue: #4C93FF; --soft: #1B2B45; --text: #F2F4F6; --sub: #9AA3AF; --card: #1B1F27; --bg: #0F1217; --note: #B4BCC8; --link: #8DBBFF; }} }}
  html, body {{ margin: 0; background: transparent; font-family: "Pretendard", "Malgun Gothic", sans-serif; color: var(--text); }}
  .wrap {{ background: var(--card); border-radius: 18px; padding: 14px 12px 12px; box-shadow: 0 8px 24px rgba(25,31,40,.07); }}
  .head {{ display: flex; align-items: center; justify-content: space-between; min-height: 34px; }}
  .title {{ font-size: 17px; font-weight: 700; }}
  .hint {{ font-size: 13px; color: var(--sub); }}
  .back {{ display: none; border: none; background: var(--soft); color: var(--blue); font-weight: 700; border-radius: 12px; padding: 7px 12px; cursor: pointer; font-size: 13px; }}
  .back.on {{ display: inline-block; }}
  svg.map {{ display: block; width: 100%; max-width: 420px; margin: 4px auto 0; cursor: grab; touch-action: none; user-select: none; -webkit-user-select: none; }}
  svg.map.drag {{ cursor: grabbing; }}
  .tools {{ display: flex; gap: 6px; align-items: center; }}
  .zb {{ border: none; background: var(--soft); color: var(--blue); font-weight: 800; border-radius: 10px; width: 32px; height: 32px; cursor: pointer; font-size: 16px; line-height: 1; }}
  .zb:hover {{ filter: brightness(.96); }}
  .land {{ fill: var(--soft); stroke: #85B7EB; stroke-width: .8; }}
  .pin {{ cursor: pointer; outline: none; }}
  .pin:focus {{ outline: none; }}
  .pin .hit {{ fill: transparent; }}
  .pin .dot {{ fill: var(--blue); stroke: #fff; stroke-width: .9; transform-box: fill-box; transform-origin: center; animation: pulse 2.4s ease-out infinite; }}
  .pin.on .dot {{ fill: var(--text); animation: none; }}
  .pin:focus-visible .dot {{ stroke: var(--blue); stroke-width: 1.4; }}
  .pin text {{ text-rendering: geometricPrecision; font-weight: 700; fill: var(--text); paint-order: stroke; stroke: var(--card); stroke-width: 2.5px; stroke-linejoin: round; }}
  .pin:hover .dot {{ fill: var(--link); }}
  .pin:hover text {{ fill: var(--blue); }}
  .pin.on text {{ fill: var(--blue); }}
  @keyframes pulse {{ 0% {{ transform: scale(1); opacity: 1; }} 70% {{ transform: scale(2.2); opacity: .15; }} 100% {{ transform: scale(1); opacity: 0; }} }}
  #panel {{ display: none; margin-top: 10px; animation: up .45s ease-out both; }}
  #panel.on {{ display: block; }}
  @keyframes up {{ from {{ opacity: 0; transform: translateY(12px); }} to {{ opacity: 1; transform: none; }} }}
  .sec {{ font-size: 14px; font-weight: 700; margin: 12px 0 6px; }}
  .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }}
  .card {{ background: var(--card); border-radius: 14px; box-shadow: 0 2px 10px rgba(25,31,40,.08); overflow: hidden; transition: transform .2s ease, box-shadow .2s ease; animation: up .4s ease-out both; }}
  .card:hover {{ transform: translateY(-3px); box-shadow: 0 10px 22px rgba(25,31,40,.14); }}
  .card img, .ph {{ width: 100%; height: 84px; object-fit: cover; display: block; background: var(--soft); }}
  .ph {{ display: flex; align-items: center; justify-content: center; color: var(--link); font-size: 12px; font-weight: 700; }}
  .cb {{ padding: 7px 8px 8px; }}
  .cn {{ font-size: 13px; font-weight: 700; line-height: 1.3; }}
  .cnote {{ font-size: 11.5px; color: var(--note); line-height: 1.4; margin-top: 3px; }}
  .credit {{ font-size: 10px; color: var(--sub); margin-top: 4px; }}
  .credit a {{ color: var(--sub); }}
  @media (max-width: 520px) {{ .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
  .lb {{ position: fixed; inset: 0; background: rgba(25,31,40,.55); display: none; align-items: center; justify-content: center; padding: 16px; z-index: 50; }}
  .lb.on {{ display: flex; animation: fade .2s ease-out both; }}
  .lb-box {{ background: var(--card); border-radius: 18px; width: min(720px, 100%); max-height: 92%; overflow: hidden; box-shadow: 0 24px 60px rgba(25,31,40,.35); animation: pop .25s ease-out both; }}
  .lb-box img {{ display: block; width: 100%; max-height: 62vh; object-fit: contain; background: var(--soft); }}
  .lb-cap {{ padding: 14px 16px 16px; }}
  .lb-name {{ font-size: 17px; font-weight: 700; }}
  .lb-note {{ font-size: 13px; color: var(--note); margin-top: 4px; }}
  .lb-cap a {{ display: inline-block; margin-top: 8px; font-size: 12px; color: var(--sub); }}
  .lb-close {{ float: right; border: none; background: var(--soft); color: var(--blue); font-weight: 700; border-radius: 12px; padding: 8px 14px; cursor: pointer; margin-top: 4px; }}
  @keyframes fade {{ from {{ opacity: 0; }} to {{ opacity: 1; }} }}
  @keyframes pop {{ from {{ opacity: 0; transform: scale(.96); }} to {{ opacity: 1; transform: scale(1); }} }}
  @media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; transition: none !important; }} }}
</style></head>
<body>
<div class="wrap">
  <div class="head">
    <div><div class="title" id="ttl">대한민국 여행지</div><div class="hint" id="hint">지역을 누르면 확대돼요</div></div>
    <div class="tools">
      <button class="zb" id="zin" type="button" aria-label="확대" title="확대">＋</button>
      <button class="zb" id="zout" type="button" aria-label="축소" title="축소">－</button>
      <button class="back" id="back" type="button">전국 보기</button>
    </div>
  </div>
  <svg class="map" id="map" viewBox="10 0 290 272" role="img" aria-label="대한민국 지도와 주요 여행지">
    <path class="land" d="{KOREA_OUTLINE_D}"/>
    {"".join(pins)}
  </svg>
  <div id="panel"></div>
</div>
<div class="lb" id="lb">
  <div class="lb-box">
    <img id="lbImg" alt="">
    <div class="lb-cap">
      <div class="lb-name" id="lbName"></div>
      <div class="lb-note" id="lbNote"></div>
      <a id="lbLink" target="_blank" rel="noopener">사진 출처 보기</a>
      <button class="lb-close" id="lbClose" type="button">닫기</button>
    </div>
  </div>
</div>
<script>
const DATA = {data_json};
const FULL = DATA.full;
const RW = 130;        // 지역을 눌렀을 때 보이는 가로 폭(지도 단위)
const MARGIN = 25;     // 지도 가장자리 밖으로 더 끌 수 있는 여유(지도 단위)
const FULL_MW = 420;   // 전국 보기에서 지도의 최대 가로(px)
const svg = document.getElementById('map');
const panel = document.getElementById('panel');
const back = document.getElementById('back');
const ttl = document.getElementById('ttl');
const hint = document.getElementById('hint');
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
let current = FULL.concat([FULL_MW]);  // [x, y, 가로, 세로, 지도 가로(px)]
let raf = null;

function setVB(v) {{
  current = v;
  svg.setAttribute('viewBox', v.slice(0, 4).map(n => n.toFixed(2)).join(' '));
  svg.style.maxWidth = v[4].toFixed(0) + 'px';
  // 확대·이동해도 점과 글자가 화면에서 같은 크기로 보이도록, 화면 픽셀 기준으로 지도 단위 크기를 정합니다.
  const ppu = svg.getBoundingClientRect().width / v[2];
  if (!isFinite(ppu) || ppu <= 0) return;
  const u = 1 / ppu;
  document.querySelectorAll('.pin .dot').forEach(c => c.setAttribute('r', (3.4 * u).toFixed(3)));
  document.querySelectorAll('.pin .hit').forEach(c => c.setAttribute('r', (13 * u).toFixed(3)));
  document.querySelectorAll('.pin text').forEach(t => {{
    t.setAttribute('font-size', (12.5 * u).toFixed(3));
    t.setAttribute('stroke-width', (3.6 * u).toFixed(3));
    t.setAttribute('x', (parseFloat(t.dataset.bx) + 6 * u).toFixed(3));
    t.setAttribute('y', (parseFloat(t.dataset.by) + 4.2 * u).toFixed(3));
  }});
}}
function animateTo(target, dur) {{
  cancelAnimationFrame(raf);
  if (reduce || !dur) {{ setVB(target); return; }}
  const from = current.slice();
  const t0 = performance.now();
  const step = now => {{
    const t = Math.min(1, (now - t0) / dur);
    const e = 1 - Math.pow(1 - t, 3);
    setVB(from.map((f, i) => f + (target[i] - f) * e));
    if (t < 1) raf = requestAnimationFrame(step);
  }};
  raf = requestAnimationFrame(step);
}}
function clampVB(x, y, w, h) {{
  const minX = FULL[0] - MARGIN, maxX = Math.max(minX, FULL[0] + FULL[2] - w + MARGIN);
  const minY = FULL[1] - MARGIN, maxY = Math.max(minY, FULL[1] + FULL[3] - h + MARGIN);
  return [Math.min(Math.max(x, minX), maxX), Math.min(Math.max(y, minY), maxY)];
}}
// 지역을 눌렀을 때는 지도를 위아래로 줄인 직사각형으로 보여 아래 사진이 잘 보이게 합니다.
function regionBox() {{
  const cw = document.querySelector('.wrap').clientWidth - 24;
  const mw = Math.min(cw, 900);
  const hpx = Math.min(230, Math.max(160, mw * 0.32));
  return {{ mw: mw, w: RW, h: RW * hpx / mw }};
}}
function targetFor(px, py) {{
  const b = regionBox();
  const [x, y] = clampVB(px - b.w / 2, py - b.h / 2, b.w, b.h);
  return [x, y, b.w, b.h, b.mw];
}}
// 화면 좌표(cx, cy)를 기준으로 배율 f 만큼 확대(f<1)·축소(f>1)합니다.
function zoomAt(cx, cy, f) {{
  cancelAnimationFrame(raf);
  const [x, y, w, h, mw] = current;
  const r = svg.getBoundingClientRect();
  const ux = x + (cx - r.left) / r.width * w, uy = y + (cy - r.top) / r.height * h;
  const nw = Math.min(FULL[2], Math.max(32, w * f)), nh = h * nw / w;
  const [nx, ny] = clampVB(ux - (ux - x) * nw / w, uy - (uy - y) * nh / h, nw, nh);
  setVB([nx, ny, nw, nh, mw]);
}}
function el(tag, cls, text) {{
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}}
function card(item, label) {{
  const c = el('div', 'card');
  if (item.photo && item.photo.thumb) {{
    const img = el('img'); img.src = item.photo.thumb; img.alt = item.name; img.loading = 'lazy';
    img.title = '눌러서 크게 보기';
    img.addEventListener('click', () => openLb(item));
    c.appendChild(img);
  }} else {{
    c.appendChild(el('div', 'ph', label));
  }}
  const b = el('div', 'cb');
  b.appendChild(el('div', 'cn', item.name));
  if (item.note) b.appendChild(el('div', 'cnote', item.note));
  if (item.photo && item.photo.page) {{
    const cr = el('div', 'credit');
    const a = el('a', null, '사진 출처 보기'); a.href = item.photo.page; a.target = '_blank'; a.rel = 'noopener';
    cr.appendChild(a); b.appendChild(cr);
  }}
  c.appendChild(b);
  return c;
}}
function show(i) {{
  const r = DATA.regions[i];
  document.querySelectorAll('.pin').forEach(p => p.classList.toggle('on', Number(p.dataset.i) === i));
  animateTo(targetFor(r.px, r.py), 900);
  ttl.textContent = r.name + ' 추천';
  hint.textContent = '장소 · 음식 · 체험을 골라 봤어요';
  back.classList.add('on');
  panel.innerHTML = '';
  [['장소', 'places', '장소'], ['음식', 'foods', '음식'], ['체험', 'activities', '체험']].forEach(([title, key, label]) => {{
    panel.appendChild(el('div', 'sec', title));
    const g = el('div', 'grid');
    (r[key] || []).forEach(item => g.appendChild(card(item, label)));
    panel.appendChild(g);
  }});
  panel.classList.add('on');
}}
function reset() {{
  animateTo(FULL.concat([FULL_MW]), 800);
  document.querySelectorAll('.pin').forEach(p => p.classList.remove('on'));
  ttl.textContent = '대한민국 여행지';
  hint.textContent = '지역을 누르면 확대돼요';
  back.classList.remove('on');
  panel.classList.remove('on');
  panel.innerHTML = '';
}}
function projOf(r) {{
  return [r.px, r.py];
}}
document.querySelectorAll('.pin').forEach(p => {{
  p.addEventListener('click', () => show(Number(p.dataset.i)));
  p.addEventListener('keydown', e => {{ if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); show(Number(p.dataset.i)); }} }});
}});
back.addEventListener('click', reset);

// ----- 끌어서 이동, 휠·버튼·손가락으로 확대/축소 -----
const ptrs = new Map();
let dragStart = null, dragged = false, lastDist = 0, suppress = false;
const pdist = () => {{ const p = [...ptrs.values()]; return Math.hypot(p[0][0] - p[1][0], p[0][1] - p[1][1]); }};
const pmid = () => {{ const p = [...ptrs.values()]; return [(p[0][0] + p[1][0]) / 2, (p[0][1] + p[1][1]) / 2]; }};
svg.addEventListener('pointerdown', e => {{
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  ptrs.set(e.pointerId, [e.clientX, e.clientY]);
  cancelAnimationFrame(raf);
  if (ptrs.size === 1) {{ dragStart = {{ x: e.clientX, y: e.clientY, vb: current.slice() }}; dragged = false; }}
  else if (ptrs.size === 2) {{ lastDist = pdist(); dragStart = null; dragged = true; }}
}});
window.addEventListener('pointermove', e => {{
  if (!ptrs.has(e.pointerId)) return;
  ptrs.set(e.pointerId, [e.clientX, e.clientY]);
  if (ptrs.size === 2) {{
    const d = pdist();
    if (lastDist) {{ const m = pmid(); zoomAt(m[0], m[1], lastDist / d); }}
    lastDist = d;
    return;
  }}
  if (!dragStart) return;
  const dx = e.clientX - dragStart.x, dy = e.clientY - dragStart.y;
  if (!dragged && Math.hypot(dx, dy) < 5) return;  // 5px 이내는 클릭으로 봅니다
  dragged = true;
  svg.classList.add('drag');
  const [vx, vy, vw, vh, mw] = dragStart.vb;
  const ppu = svg.getBoundingClientRect().width / vw;
  const [nx, ny] = clampVB(vx - dx / ppu, vy - dy / ppu, vw, vh);
  setVB([nx, ny, vw, vh, mw]);
}});
function endPtr(e) {{
  if (!ptrs.has(e.pointerId)) return;
  ptrs.delete(e.pointerId);
  if (ptrs.size < 2) lastDist = 0;
  if (ptrs.size === 0) {{
    svg.classList.remove('drag');
    if (dragged) {{ suppress = true; setTimeout(() => {{ suppress = false; }}, 0); }}  // 끌고 난 뒤의 클릭은 무시
    dragStart = null;
  }}
}}
window.addEventListener('pointerup', endPtr);
window.addEventListener('pointercancel', endPtr);
svg.addEventListener('click', e => {{ if (suppress) {{ e.stopPropagation(); e.preventDefault(); }} }}, true);
svg.addEventListener('wheel', e => {{ e.preventDefault(); zoomAt(e.clientX, e.clientY, Math.exp(e.deltaY * 0.0015)); }}, {{ passive: false }});
function zoomCenter(f) {{ const r = svg.getBoundingClientRect(); zoomAt(r.left + r.width / 2, r.top + r.height / 2, f); }}
document.getElementById('zin').addEventListener('click', () => zoomCenter(0.72));
document.getElementById('zout').addEventListener('click', () => zoomCenter(1 / 0.72));
window.addEventListener('resize', () => setVB(current));
requestAnimationFrame(() => setVB(current));

function openLb(item) {{
  const lb = document.getElementById('lb');
  const src = (item.photo && (item.photo.full || item.photo.thumb)) || '';
  document.getElementById('lbImg').src = src;
  document.getElementById('lbName').textContent = item.name;
  document.getElementById('lbNote').textContent = item.note || '';
  const link = document.getElementById('lbLink');
  if (item.photo && item.photo.page) {{ link.href = item.photo.page; link.style.display = 'inline'; }} else {{ link.style.display = 'none'; }}
  lb.classList.add('on');
}}
function closeLb() {{ document.getElementById('lb').classList.remove('on'); }}
document.getElementById('lb').addEventListener('click', e => {{ if (e.target.id === 'lb' || e.target.id === 'lbClose') closeLb(); }});
document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeLb(); }});
</script>
</body></html>"""
