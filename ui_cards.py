"""화면용 카드 렌더러: 모델이 쓴 마크다운 답변을 일차 카드, 장소 카드로 바꿔 보여 줍니다.

- 일정 답변: '### N일차 | 제목' 아래의 표를 일차 카드 타임라인으로 그립니다.
- 추천 답변: '### 섹션' 아래의 '- [이름](링크) — 이유' 목록을 장소 카드로 그립니다.
- 형식이 맞지 않으면 아무것도 바꾸지 않고 원래 마크다운을 그대로 보여 줍니다.
- 모델 답변의 글자는 모두 escape 해서 HTML 로 넣습니다. 링크는 http(s) 주소만 허용합니다.
"""

import re
from html import escape
from urllib.parse import quote

import streamlit as st

DAY_HEAD = re.compile(r"^#{2,4}\s*(\d+)\s*일차\s*[|·:\-–—]?\s*(.*)$")
SECTION_HEAD = re.compile(r"^#{2,4}\s*(.+?)\s*$")
LINK_ITEM = re.compile(r"^\s*[-*]\s*\*{0,2}\[([^\]]+)\]\((https?://[^)\s]+)\)\*{0,2}\s*[—–\-:·]\s*(.+?)\s*$")
MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
MD_BOLD = re.compile(r"\*\*(.+?)\*\*")

SLOT_CLASS = {"오전": "morning", "점심": "lunch", "오후": "afternoon", "저녁": "evening"}
KIND_ICON = {"관광지": "🏞️", "식당": "🍽️", "맛집": "🍽️", "카페": "☕", "숙소": "🛏️", "시장": "🛍️", "쇼핑": "🛍️", "휴식": "🛋️"}
MOVE_ICON = (("도보", "🚶"), ("택시", "🚕"), ("버스", "🚌"), ("대중교통", "🚌"), ("지하철", "🚇"), ("기차", "🚆"), ("자차", "🚗"))
SECTION_ICON = {"가볼 만한 곳": "🏞️", "먹을 곳": "🍽️", "쉬어 갈 곳": "☕", "묵을 곳": "🛏️"}


def _inline(text: str) -> str:
    """셀 안의 마크다운(굵게, 링크)을 안전한 HTML 로 바꿉니다. 나머지 글자는 escape 합니다."""
    out, pos = [], 0
    for m in MD_LINK.finditer(text):
        out.append(escape(text[pos:m.start()]))
        out.append(f'<a href="{escape(m.group(2), quote=True)}" target="_blank" rel="noopener noreferrer">{escape(m.group(1))}</a>')
        pos = m.end()
    out.append(escape(text[pos:]))
    html = "".join(out)
    return MD_BOLD.sub(r"<b>\1</b>", html).replace("&lt;br&gt;", " ")


def _plain(text: str) -> str:
    return MD_BOLD.sub(r"\1", MD_LINK.sub(r"\1", text)).strip()


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _is_sep(line: str) -> bool:
    return bool(re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", line.strip()))


def _find(header: list[str], *names: str):
    for i, h in enumerate(header):
        if any(n in h for n in names):
            return i
    return None


def _parse_plan(answer: str):
    """('앞 글', [일차...], '뒷 글')로 나눕니다. 일차 하나 = {no, title, rows, notes}. 실패하면 None."""
    lines = answer.split("\n")
    days, intro, tail = [], [], []
    cur = None
    for line in lines:
        m = DAY_HEAD.match(line.strip())
        if m:
            cur = {"no": int(m.group(1)), "title": _plain(m.group(2)), "table": [], "notes": []}
            days.append(cur)
            continue
        if cur is None:
            intro.append(line)
        elif SECTION_HEAD.match(line.strip()) and line.strip().startswith("#"):
            cur = None
            tail.append(line)
        elif line.strip().startswith("|"):
            cur["table"].append(line)
        elif line.strip():
            cur["notes"].append(line.strip())
    if not days:
        return None
    parsed = []
    for d in days:
        table = [ln for ln in d["table"] if not _is_sep(ln)]
        if len(table) < 2:
            return None
        header = _cells(table[0])
        i_slot, i_place = _find(header, "시간"), _find(header, "장소")
        if i_slot is None or i_place is None:
            return None
        i_kind, i_move, i_desc = _find(header, "구분"), _find(header, "이동"), _find(header, "설명", "메모", "비고")
        rows = []
        for ln in table[1:]:
            c = _cells(ln)
            get = lambda i: c[i] if i is not None and i < len(c) else ""
            rows.append({"slot": get(i_slot), "place": get(i_place), "kind": get(i_kind), "move": get(i_move), "desc": get(i_desc)})
        parsed.append({"no": d["no"], "title": d["title"], "rows": rows, "notes": d["notes"]})
    return "\n".join(intro).strip(), parsed, "\n".join(tail).strip()


def _weather_badge(day: dict, icons: dict) -> str:
    icon, label = icons.get(day.get("code"), ("", ""))
    if not label:
        return ""
    return (
        f'<span class="wx-badge">{icon} {escape(label)} · {day["tmin"]:.0f}~{day["tmax"]:.0f}°'
        f'{" · 강수 %.0fmm" % day["rain_mm"] if day.get("rain_mm") else ""}</span>'
    )


def _move_html(move: str) -> str:
    if not move.strip():
        return ""
    icon = next((ic for key, ic in MOVE_ICON if key in move), "➜")
    return f'<span class="tl-move">{icon} {_inline(move)}</span>'


def kakao_search_url(name: str, region: str | None = None) -> str:
    """장소 이름으로 카카오맵 검색 결과 페이지 주소를 만듭니다. 지역이 이름에 없으면 앞에 붙여 동명 장소를 줄입니다."""
    query = name if not region or region in name else f"{region} {name}"
    return f"https://map.kakao.com/link/search/{quote(query)}"


def _place_html(cell: str, region: str | None) -> str:
    name = _plain(cell)
    return (
        f'<a href="{escape(kakao_search_url(name, region), quote=True)}" target="_blank" rel="noopener noreferrer" '
        f'title="카카오맵에서 검색">{escape(name)}</a>'
    )


def is_plan(answer: str) -> bool:
    return "일차" in answer and _parse_plan(answer) is not None


def _day_card(day: dict, weather_days: list[dict], icons: dict, region: str | None = None) -> str:
    wx = weather_days[day["no"] - 1] if 0 < day["no"] <= len(weather_days) else None
    badge = _weather_badge(wx, icons) if wx else ""
    items = []
    for r in day["rows"]:
        slot = r["slot"].strip()
        cls = next((v for k, v in SLOT_CLASS.items() if k in slot), "etc")
        kind = r["kind"].strip()
        icon = next((ic for k, ic in KIND_ICON.items() if k in kind), "📍")
        kind_tag = f'<span class="tl-kind">{escape(kind)}</span>' if kind else ""
        desc = f'<div class="tl-desc">{_inline(r["desc"])}</div>' if r["desc"].strip() else ""
        items.append(
            f'<li class="tl-item"><span class="tl-chip {cls}">{escape(slot)}</span>'
            f'<div class="tl-body"><div class="tl-place">{icon} {_place_html(r["place"], region)} {kind_tag}</div>{desc}{_move_html(r["move"])}</div></li>'
        )
    notes = "".join(f'<div class="day-note">{_inline(n)}</div>' for n in day["notes"])
    title = f'<span class="day-title">{escape(day["title"])}</span>' if day["title"] else ""
    return (
        f'<section class="day-card"><header><span class="day-no">{day["no"]}일차</span>{title}{badge}</header>'
        f'<ol class="timeline">{"".join(items)}</ol>{notes}</section>'
    )


def _parse_recommend(answer: str):
    """('앞 글', [(섹션, [(이름, 링크, 이유)])], '뒷 글')로 나눕니다. 실패하면 None."""
    intro, tail, sections = [], [], []
    cur = None
    for line in answer.split("\n"):
        s = line.strip()
        head = SECTION_HEAD.match(s) if s.startswith("#") else None
        if head and head.group(1).strip("*") in SECTION_ICON:
            cur = (head.group(1).strip("*"), [])
            sections.append(cur)
            continue
        item = LINK_ITEM.match(line) if cur is not None else None
        if item:
            cur[1].append((item.group(1), item.group(2), item.group(3)))
        elif not sections:
            intro.append(line)
        elif s:
            cur = None
            tail.append(line)
        elif tail:
            tail.append(line)
    sections = [sec for sec in sections if sec[1]]
    if len(sections) < 2:
        return None
    return "\n".join(intro).strip(), sections, "\n".join(tail).strip()


def _place_cards(sections) -> str:
    out = []
    for name, items in sections:
        cards = "".join(
            f'<div class="pl-card"><div class="pl-name">{escape(title)}</div>'
            f'<div class="pl-why">{_inline(why)}</div>'
            f'<a class="pl-map" href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">지도 보기 ›</a></div>'
            for title, url, why in items
        )
        out.append(
            f'<section class="pl-section"><h4>{SECTION_ICON.get(name, "📍")} {escape(name)}</h4>'
            f'<div class="pl-grid">{cards}</div></section>'
        )
    return "".join(out)


def render_answer(answer: str, research: dict | None, weather_icons: dict):
    """답변을 카드형으로 그립니다. 카드로 바꿀 수 없으면 원래 마크다운을 보여 줍니다."""
    plan = _parse_plan(answer) if "일차" in answer else None
    if plan:
        intro, days, tail = plan
        weather = ((research or {}).get("weather") or {}).get("days") or []
        region = ((research or {}).get("cond") or {}).get("destination")
        if intro:
            st.markdown(intro)
        st.markdown("".join(_day_card(d, weather, weather_icons, region) for d in days), unsafe_allow_html=True)
        if tail:
            st.markdown(tail)
        return
    rec = _parse_recommend(answer)
    if rec:
        intro, sections, tail = rec
        if intro:
            st.markdown(intro)
        st.markdown(_place_cards(sections), unsafe_allow_html=True)
        if tail:
            st.markdown(tail)
        return
    st.markdown(answer)


# ---------- 단계 표시와 칩 ----------

def stage_html(steps: list[str], active: int) -> str:
    """진행 단계 표시줄. active 앞은 완료, active 는 진행 중, 뒤는 대기."""
    parts = []
    for i, label in enumerate(steps):
        state = "done" if i < active else "now" if i == active else "wait"
        mark = "✓" if state == "done" else str(i + 1)
        parts.append(f'<div class="stp {state}"><span class="stp-dot">{mark}</span><span class="stp-label">{escape(label)}</span></div>')
    return f'<div class="stepper">{"".join(parts)}</div>'


def badge(text: str, kind: str = "info") -> str:
    """상태 배지. kind: ok, bad, info, warn."""
    return f'<span class="badge {kind}">{escape(text)}</span>'


CSS = """
<style>
  /* ===== 일차 카드 타임라인 ===== */
  .day-card {
    background: var(--toss-card); border: 1px solid var(--toss-line); border-radius: 18px;
    padding: 16px 18px 12px; margin: 12px 0; animation: fade-up 0.45s ease-out both;
    box-shadow: 0 1px 2px rgba(var(--toss-shadow), 0.04), 0 8px 22px rgba(var(--toss-shadow), 0.06);
  }
  .day-card header { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 10px; margin-bottom: 10px; }
  .day-no { background: var(--toss-blue); color: #fff; font-weight: 800; border-radius: 10px; padding: 3px 11px; font-size: 0.92rem; }
  .day-title { font-weight: 800; color: var(--toss-text); font-size: 1.05rem; }
  .wx-badge { margin-left: auto; background: var(--toss-blue-soft); color: var(--toss-soft-text); border-radius: 999px; padding: 3px 11px; font-size: 0.82rem; font-weight: 700; }
  .day-card .timeline { list-style: none !important; margin: 0 !important; padding: 0 !important; }
  .day-card .tl-item { list-style: none !important; margin: 0 !important; display: flex; gap: 14px; align-items: flex-start; padding: 8px 0; position: relative; transition: transform 0.18s ease; }
  /* 세로선은 항목마다 칩 가운데(칩 너비의 절반)를 지나게 그립니다. 첫·끝 항목은 칩 높이의 절반에서 시작·끝납니다 */
  .tl-item::before { content: ""; position: absolute; left: 28px; top: 0; bottom: 0; width: 2px; background: var(--toss-line); z-index: 0; }
  .tl-item:first-child::before { top: 21px; }
  .tl-item:last-child::before { bottom: calc(100% - 21px); }
  .tl-item:hover { transform: translateX(3px); }
  .tl-chip {
    flex: 0 0 auto; width: 58px; text-align: center; font-size: 0.8rem; font-weight: 800; border-radius: 999px; padding: 4px 0;
    border: 3px solid var(--toss-card); position: relative; z-index: 1;
  }
  .tl-chip.morning { background: #FFF4D6; color: #9A6400; }
  .tl-chip.lunch { background: #FFE6D6; color: #B0480B; }
  .tl-chip.afternoon { background: #DDEBFF; color: #1B64DA; }
  .tl-chip.evening { background: #EADFFF; color: #6A3FC9; }
  .tl-chip.etc { background: var(--toss-bg); color: var(--toss-sub); }
  .tl-body { min-width: 0; flex: 1; }
  .tl-place { font-weight: 700; color: var(--toss-text); line-height: 1.5; }
  .tl-place a { color: var(--toss-text); text-decoration: none; border-bottom: 1.5px dotted var(--toss-blue); }
  .tl-place a:hover { color: var(--toss-blue); border-bottom-style: solid; }
  .tl-kind { margin-left: 4px; background: var(--toss-bg); color: var(--toss-sub); border-radius: 8px; padding: 1px 8px; font-size: 0.75rem; font-weight: 700; }
  .tl-desc { color: var(--toss-text); opacity: 0.8; font-size: 0.92rem; line-height: 1.55; margin-top: 2px; }
  .tl-move { display: inline-block; margin-top: 4px; color: var(--toss-sub); font-size: 0.8rem; }
  .day-note { color: var(--toss-sub); font-size: 0.88rem; padding: 6px 2px 0; }

  /* ===== 추천 장소 카드 ===== */
  .pl-section { margin: 14px 0 6px; }
  .pl-section h4 { margin: 0 0 8px; font-size: 1.05rem; font-weight: 800; color: var(--toss-text); }
  .pl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 10px; }
  .pl-card {
    background: var(--toss-card); border: 1px solid var(--toss-line); border-radius: 16px; padding: 12px 14px;
    display: flex; flex-direction: column; gap: 6px; animation: pop-in 0.4s ease-out both;
    transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  }
  .pl-card:hover { transform: translateY(-3px); border-color: var(--toss-blue); box-shadow: 0 10px 24px rgba(var(--toss-shadow), 0.12); }
  .pl-name { font-weight: 800; color: var(--toss-text); }
  .pl-why { color: var(--toss-text); opacity: 0.78; font-size: 0.9rem; line-height: 1.5; flex: 1; }
  .pl-map {
    align-self: flex-start; background: var(--toss-blue-soft); color: var(--toss-soft-text) !important; text-decoration: none !important;
    font-weight: 700; font-size: 0.82rem; border-radius: 999px; padding: 4px 12px; transition: background 0.2s ease;
  }
  .pl-map:hover { background: var(--toss-blue); color: #fff !important; }

  /* ===== 단계 표시 ===== */
  .stepper { display: flex; flex-wrap: wrap; gap: 8px 18px; padding: 4px 0; }
  .stp { display: flex; align-items: center; gap: 8px; color: var(--toss-sub); font-size: 0.9rem; font-weight: 600; }
  .stp-dot {
    width: 24px; height: 24px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center;
    background: var(--toss-bg); color: var(--toss-sub); font-size: 0.78rem; font-weight: 800; border: 1px solid var(--toss-line);
  }
  .stp.done { color: var(--toss-text); }
  .stp.done .stp-dot { background: var(--toss-blue); color: #fff; border-color: var(--toss-blue); }
  .stp.now { color: var(--toss-blue); }
  .stp.now .stp-dot { background: var(--toss-blue-soft); color: var(--toss-soft-text); border-color: var(--toss-blue); animation: stp-pulse 1.2s ease-in-out infinite; }
  @keyframes stp-pulse { 0%, 100% { box-shadow: 0 0 0 0 rgba(49, 130, 246, 0.45); } 50% { box-shadow: 0 0 0 6px rgba(49, 130, 246, 0); } }

  /* ===== 배지 ===== */
  .badge { display: inline-block; border-radius: 999px; padding: 4px 12px; font-size: 0.85rem; font-weight: 800; margin: 2px 6px 2px 0; }
  .badge.ok { background: #E3F7EC; color: #0B7A43; }
  .badge.bad { background: #FDE8EA; color: #C4252F; }
  .badge.warn { background: #FFF1DB; color: #A35A00; }
  .badge.info { background: var(--toss-blue-soft); color: var(--toss-soft-text); }

  /* ===== 예시 질문 칩 ===== */
  [class*="st-key-chip_"] .stButton button {
    border-radius: 999px !important; padding: 0.45rem 1rem; font-size: 0.9rem; font-weight: 700;
    background: var(--toss-card); color: var(--toss-soft-text); border: 1px solid var(--toss-line) !important;
    box-shadow: none !important; white-space: normal; height: auto;
  }
  [class*="st-key-chip_"] .stButton button:hover { border-color: var(--toss-blue) !important; background: var(--toss-blue-soft); }

  /* ===== 일정 카드 위 '캘린더에 등록' 버튼: 우측 상단 ===== */
  [class*="st-key-tocal_"] { width: 100% !important; display: flex !important; justify-content: flex-end !important; margin-bottom: 4px; }
  [class*="st-key-tocal_"] .stButton { width: auto !important; }
  [class*="st-key-tocal_"] .stButton button { border-radius: 999px !important; padding: 0.35rem 1.1rem; font-size: 0.88rem; font-weight: 800; }

  /* ===== 일정 짜기 버튼: 화면 아래에 붙어 따라다님 ===== */
  .st-key-make_plan_btn { position: sticky; bottom: 5.8rem; z-index: 40; display: flex; justify-content: center; margin-top: 0.5rem; }
  .st-key-make_plan_btn .stButton button { border-radius: 999px !important; padding: 0.7rem 1.8rem; font-size: 1rem; box-shadow: 0 10px 28px rgba(49, 130, 246, 0.45) !important; }

  /* ===== 캘린더 등록 ===== */
  .cal-steps { display: flex; gap: 6px; margin: 4px 0 14px; }
  .cal-step { flex: 1; text-align: center; padding: 10px 4px; border-radius: 14px; background: var(--toss-card); border: 1px solid var(--toss-line); color: var(--toss-sub); font-weight: 700; font-size: 0.9rem; }
  .cal-step.done { background: var(--toss-blue-soft); color: var(--toss-soft-text); border-color: transparent; }
  .cal-step.now { background: var(--toss-blue); color: #fff; border-color: transparent; box-shadow: 0 8px 20px rgba(49, 130, 246, 0.35); }
  .ev-day { font-weight: 800; color: var(--toss-text); margin: 14px 0 6px; }
  .ev-card {
    display: flex; gap: 12px; align-items: flex-start; background: var(--toss-card); border: 1px solid var(--toss-line);
    border-radius: 14px; padding: 10px 14px; margin-bottom: 8px; animation: pop-in 0.35s ease-out both;
  }
  .ev-time { flex: 0 0 auto; background: var(--toss-blue-soft); color: var(--toss-soft-text); border-radius: 10px; padding: 3px 10px; font-weight: 800; font-size: 0.85rem; white-space: nowrap; }
  .ev-title { font-weight: 700; color: var(--toss-text); }
  .ev-loc { color: var(--toss-sub); font-size: 0.85rem; }
  .ev-card.ok { border-left: 4px solid #1EB36B; }
  .ev-card.warn { border-left: 4px solid #F59F00; }

  /* ===== 새 질문을 보낼 때 이전 화면이 반투명하게 남는 현상 제거 ===== */
  /* 새 질문 말풍선 안에 이전 답변의 흔적이 흐리게 비쳐 보이므로, 말풍선 안의 흔적은 숨기고 나머지는 흐려지지 않게 합니다 */
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-stale="true"] { display: none !important; }
  [data-stale="true"] { opacity: 1 !important; }

  /* ===== 모바일 ===== */
  @media (max-width: 640px) {
    .block-container { padding-left: 0.9rem; padding-right: 0.9rem; padding-top: 1.5rem; }
    h1 { font-size: 1.6rem; }
    [data-testid="stChatMessage"] { padding: 0.8rem 0.9rem; border-radius: 16px; }
    .day-card { padding: 12px 12px 8px; }
    .tl-item::before { left: 24px; }
    .tl-chip { width: 50px; font-size: 0.74rem; }
    .tl-item { gap: 10px; }
    .wx-badge { margin-left: 0; }
    .pl-grid { grid-template-columns: 1fr; }
    .cal-step { font-size: 0.78rem; padding: 8px 2px; }
    .st-key-make_plan_btn { bottom: 5.2rem; }
  }

  /* ===== 다크 모드에서 연한 배경 칩 색 조정 ===== */
  @media (prefers-color-scheme: dark) {
    .tl-chip.morning { background: #4A3A12; color: #FFD479; }
    .tl-chip.lunch { background: #4A2A18; color: #FFB48A; }
    .tl-chip.afternoon { background: #1E3556; color: #8DBBFF; }
    .tl-chip.evening { background: #34285A; color: #C7ABFF; }
    .badge.ok { background: #12392A; color: #6FE0A6; }
    .badge.bad { background: #43191D; color: #FF9AA2; }
    .badge.warn { background: #44300F; color: #FFC46B; }
  }
</style>
"""
