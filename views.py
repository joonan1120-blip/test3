"""사이드바 메뉴별 화면. app.py 에서 메뉴를 고르면 해당 함수를 부릅니다."""

import json
import re
from datetime import date, timedelta
from html import escape
from pathlib import Path

import streamlit.components.v1 as components

import streamlit as st

import agents
import calendar_client as cal
import plan_store
import ui_cards
from contextlib import nullcontext

import chat_store
from chatbot import ChatbotError, ask, complete_json
from config import MAX_QUESTION_CHARS, REASONING, get_agent_mode, get_model_name
from kakao_places import KakaoError, day_distances, extract_places, verify_places
from korea_map import KOREA_OUTLINE_D, KOREA_PINS_SVG
from map_widget import build_map_html
from agent import route_question, run_lookup
from plan_dates import TripInfo, extract_trip
from plan_pipeline import (
    WIDE_KINDS,
    Conditions,
    build_context,
    collect_lodging,
    collect_places,
    collect_weather,
)
from travel_data import (
    TravelDataError,
    fetch_domestic_rankings,
    fetch_krw_rates,
    geocode,
    get_daily_weather,
    get_plan_weather,
    get_trip_weather,
)

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _clean(text: str) -> str:
    """이전에 저장된 답변에 남아 있을 수 있는 <br> 태그를 공백으로 바꿔 글자로 보이지 않게 합니다."""
    return re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)

# Open-Meteo 날씨 코드(WMO) → (아이콘, 이름)
WEATHER_ICONS = {
    0: ("☀️", "맑음"),
    1: ("🌤️", "대체로 맑음"),
    2: ("⛅", "구름 조금"),
    3: ("☁️", "흐림"),
    45: ("🌫️", "안개"),
    48: ("🌫️", "안개"),
    51: ("🌦️", "이슬비"),
    53: ("🌦️", "이슬비"),
    55: ("🌦️", "이슬비"),
    56: ("🌧️", "진눈깨비"),
    57: ("🌧️", "진눈깨비"),
    61: ("🌧️", "비"),
    63: ("🌧️", "비"),
    65: ("🌧️", "많은 비"),
    66: ("🌧️", "진눈깨비"),
    67: ("🌧️", "진눈깨비"),
    71: ("🌨️", "눈"),
    73: ("🌨️", "눈"),
    75: ("❄️", "많은 눈"),
    77: ("❄️", "싸락눈"),
    80: ("🌦️", "소나기"),
    81: ("🌧️", "소나기"),
    82: ("⛈️", "강한 소나기"),
    85: ("🌨️", "눈 소나기"),
    86: ("❄️", "눈 소나기"),
    95: ("⛈️", "뇌우"),
    96: ("⛈️", "뇌우"),
    99: ("⛈️", "뇌우"),
}

AI_NOTICE = (
    "AI 가 알고 있는 지식으로 만든 추천입니다. 실시간 인기 순위가 아니며, "
    "운영 시간·가격 등은 공식 자료로 확인해 주세요."
)

POPULAR_PROMPT = (
    "당신은 여행 정보 도우미입니다. 요청 조건에 맞는 여행지 5곳을 JSON 객체 하나로만 답하세요. "
    "설명 문장이나 코드 펜스는 붙이지 마세요. 형식: "
    '{"items": [{"name": "여행지 이름", "country": "나라", "reason": "인기 이유 한 줄", '
    '"best_season": "좋은 시기", "trip_length": "권장 일정", '
    '"spots": ["핵심 스팟과 한 줄 설명", "핵심 스팟과 한 줄 설명", "핵심 스팟과 한 줄 설명"], '
    '"recommended_for": "이런 분께 추천 한 줄", "tip": "꿀팁 또는 주의 한 줄"}]} '
    "실시간 순위를 아는 것처럼 '지금 1위' 같은 표현은 쓰지 마세요. 이모지는 항목당 1개 이내로 가볍게만 쓰세요."
)

COMPARE_PROMPT = (
    "당신은 여행지 비교 도우미입니다. 두 여행지를 비교해 JSON 객체 하나로만 답하세요. "
    "설명 문장이나 코드 펜스는 붙이지 마세요. 형식: "
    '{"rows": [{"label": "항목", "a": "A 내용", "b": "B 내용"}], "verdict": "한 줄 결론"} '
    "rows 는 반드시 다음 항목을 이 순서로 포함하세요: 추천 여행 기간, 예산 수준, 날씨와 계절, "
    "대표 볼거리, 대표 음식, 이동 난이도, 이런 분께 추천. 각 내용은 한두 문장으로 짧게 쓰세요."
)

COMPARE_CSS = """
<style>
  .cmp-grid { display: grid; grid-template-columns: 110px 1fr 1fr; gap: 8px; }
  .cmp-cell {
    background: var(--toss-card); border-radius: 14px; padding: 0.9rem 1rem;
    box-shadow: 0 2px 8px rgba(25, 31, 40, 0.06); color: var(--toss-text); font-size: 0.95rem; line-height: 1.55;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
    animation: pop-in 0.4s ease-out both;
  }
  .cmp-cell:not(.cmp-label):hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 26px rgba(25, 31, 40, 0.12);
  }
  .cmp-label { background: transparent; box-shadow: none; color: var(--toss-sub); font-weight: 700; padding-left: 0.25rem; }
  .cmp-title { background: #3182F6; color: #FFFFFF; font-weight: 800; text-align: center; font-size: 1.05rem; }
  .cmp-verdict {
    background: var(--toss-blue-soft); color: var(--toss-soft-text); border-radius: 14px; padding: 1rem 1.1rem;
    font-weight: 700; margin-top: 12px;
  }
  @media (max-width: 640px) {
    .cmp-grid { grid-template-columns: 1fr 1fr; }
    .cmp-label { display: none; }
  }
</style>
"""


# ---------- 홈: 주요 여행지 환율 ----------

@st.cache_data(ttl=1800, show_spinner=False)
def _cached_fx():
    return fetch_krw_rates()


TICKER_CSS = """
<style>
  .fx-ticker {
    overflow: hidden; background: var(--toss-card); border-radius: 16px; padding: 14px 0;
    box-shadow: 0 2px 8px rgba(25, 31, 40, 0.06); white-space: nowrap;
  }
  .fx-track { display: inline-flex; width: max-content; animation: fx-scroll 45s linear infinite; }
  .fx-ticker:hover .fx-track { animation-play-state: paused; }
  .fx-item { padding: 0 22px; color: var(--toss-text); font-size: 1rem; }
  .fx-item b { color: #3182F6; margin-right: 6px; }
  @keyframes fx-scroll { from { transform: translateX(0); } to { transform: translateX(-50%); } }
  @media (prefers-reduced-motion: reduce) { .fx-track { animation: none; } }
</style>
"""


def _fx_ticker_html(rows: list[dict]) -> str:
    items = []
    for row in rows:
        # 엔화는 1엔이 너무 작아서 100엔 기준으로 보여 줍니다. 소수점은 버리고 정수로 표시합니다.
        unit, krw = (100, row["krw"] * 100) if row["code"] == "JPY" else (1, row["krw"])
        items.append(
            f'<span class="fx-item"><b>{escape(row["country"])}</b>'
            f'{unit} {escape(row["code"])} = {round(krw):,}원</span>'
        )
    one_round = "".join(items)
    # 같은 목록을 두 번 이어 붙이고 -50% 까지만 움직이면, 끝에서 처음으로 자연스럽게 이어집니다.
    return f'<div class="fx-ticker"><div class="fx-track">{one_round}{one_round}</div></div>'


MAP_CSS = """
<style>
  .kr-card {
    background: var(--toss-card); border-radius: 18px; padding: 18px 12px 8px;
    box-shadow: 0 8px 24px rgba(25, 31, 40, 0.07); margin-top: 1rem;
    animation: pop-in 0.5s ease-out both;
  }
  .kr-card svg { display: block; width: 100%; max-width: 360px; margin: 0 auto; }
  .kr-land { fill: var(--toss-blue-soft); stroke: #85B7EB; stroke-width: 0.8; }
  .kr-pin circle { fill: #3182F6; stroke: #FFFFFF; stroke-width: 1.5; transform-box: fill-box; transform-origin: center; animation: kr-pulse 2.4s ease-out infinite; }
  .kr-pin text { font-size: 9px; font-weight: 700; fill: var(--toss-text); }
  @keyframes kr-pulse { 0% { transform: scale(1); opacity: 1; } 70% { transform: scale(2.2); opacity: 0.15; } 100% { transform: scale(1); opacity: 0; } }
  @media (prefers-reduced-motion: reduce) { .kr-pin circle { animation: none; } }
</style>
"""


REGION_FILE = Path(__file__).resolve().parent / "region_data.json"


def _korea_map_card():
    # 지역 데이터가 있으면 클릭형 지도를, 없으면 점만 있는 정적 지도를 보여 줍니다.
    if REGION_FILE.exists():
        try:
            regions = json.loads(REGION_FILE.read_text(encoding="utf-8")).get("regions", [])
        except (OSError, ValueError):
            regions = []
        if regions:
            components.html(build_map_html(regions), height=920, scrolling=True)
            return
    _static_korea_map()


def _static_korea_map():
    svg = (
        '<svg viewBox="10 0 290 272" role="img" aria-label="대한민국 지도와 주요 여행지 위치">'
        f'<path class="kr-land" d="{KOREA_OUTLINE_D}"/>'
        f"{KOREA_PINS_SVG}"
        "</svg>"
    )
    st.markdown(
        MAP_CSS + f'<div class="kr-card">{svg}</div>',
        unsafe_allow_html=True,
    )


def home_view():
    st.title("여행이")
    st.caption("오늘의 주요 환율 (주요 10개국, 외화 기준 원화 환산)")

    # 환율을 못 가져와도 지도는 보여 줍니다.
    try:
        rows = _cached_fx()
    except TravelDataError as e:
        rows = []
        st.info(str(e))

    if rows:
        st.markdown(TICKER_CSS + _fx_ticker_html(rows), unsafe_allow_html=True)
        if rows[0].get("date"):
            st.caption(f"기준일 {rows[0]['date']} (ECB 기준 환율, 실제 환전 시세와 다를 수 있습니다)")

    _korea_map_card()

    st.markdown("")
    st.markdown("**무엇을 도와드릴까요?** 왼쪽 메뉴에서 골라 보세요.")
    st.markdown("- 여행 질문: 기간·인원·목적을 말하면 일정을 짜 드려요.")
    st.markdown("- 인기 여행지: 국내와 해외(단기·장기)를 골라 볼 수 있어요.")
    st.markdown("- 여행지 비교: 두 곳을 나란히 비교해요.")
    st.markdown("- 날씨 보기: 여행 날짜에 맞춘 날씨를 확인해요.")


# ---------- 여행 질문 (대화) ----------

CHAT_STATE_KEYS = (
    "last_answer", "recommend_only", "plan_pending", "plan_done", "recommended_places",
    "recommended_lodging", "from_recommend", "auto_question", "verify_result", "plan_start_suggest", "plan_meta",
)


def _clear_chat_state():
    """대화가 바뀌면 이전 대화의 추천·일정 상태(버튼, 검증 결과 등)도 함께 지웁니다."""
    for key in CHAT_STATE_KEYS:
        st.session_state.pop(key, None)


def _reset_chat():
    st.session_state.history = []
    st.session_state.chat_id = None
    _clear_chat_state()


SCROLL_TO_ANSWER_JS = """
<script>
(function () {
  const doc = window.parent.document;
  const go = () => {
    const msgs = doc.querySelectorAll('[data-testid="stChatMessage"]');
    const last = msgs[msgs.length - 1];
    if (last) last.scrollIntoView({ block: "start", behavior: "auto" });
  };
  // 검증 로딩이 뒤따라 붙으면서 화면이 다시 아래로 내려가므로, 잠깐 동안 계속 답변 위치로 맞춥니다.
  // 사용자가 직접 스크롤하면 바로 멈춥니다.
  let n = 0;
  let timer = null;
  const stop = () => { if (timer) clearInterval(timer); timer = null; };
  ["wheel", "touchstart", "keydown"].forEach(ev => doc.addEventListener(ev, stop, { passive: true, once: true }));
  timer = setInterval(() => {
    go();
    n += 1;
    if (n >= 28) stop();
  }, 250);
})();
</script>
"""


def _scroll_to_latest_answer():
    """일정 답변이 나오면 화면을 그 답변의 맨 위로 맞춥니다. 긴 답변을 처음부터 읽을 수 있게 합니다."""
    components.html(SCROLL_TO_ANSWER_JS, height=0)


PLAN_STEPS = ["장소 찾기", "숙소 찾기", "날씨 확인", "답변 쓰기"]
EXAMPLE_CHIPS = [
    "이번 주말 부산 1박 2일 혼자 여행 추천해줘",
    "제주 2박 3일 가족여행 일정 짜줘",
    "강릉 당일치기 맛집 코스",
    "비 오는 날 서울에서 갈 만한 곳",
]


def _stage(placeholder, active: int):
    """장소 → 숙소 → 날씨 → 답변 쓰기 단계 중 지금 어디인지 보여 줍니다."""
    placeholder.markdown(ui_cards.stage_html(PLAN_STEPS, active), unsafe_allow_html=True)


def _go_calendar(answer: str):
    """이 일정을 '캘린더 등록' 메뉴에서 열어 줍니다. 장소 확인을 마쳐 저장된 일정만 열 수 있습니다."""
    plan_id = plan_store.plan_id_for(answer)
    if plan_store.get_plan(plan_id) is None:
        st.toast("아직 장소 확인이 끝난 일정이 아니에요. 잠시 뒤에 다시 눌러 주세요.")
        return
    st.session_state.cal_plan_id = plan_id
    st.session_state.menu = "캘린더 등록"


def _render_answer(text: str, research: dict | None = None, key: str | None = None):
    """답변을 카드형으로 보여 줍니다. 카드로 바꿀 수 없는 답변은 그대로 마크다운으로 보여 줍니다.
    일정 답변이면 우측 상단에 '캘린더에 등록' 버튼을 둡니다."""
    if key and ui_cards.is_plan(_clean(text)):
        st.button("📅 캘린더에 등록", key=f"tocal_{key}", type="primary", on_click=_go_calendar, args=(text,))
    ui_cards.render_answer(_clean(text), research, WEATHER_ICONS)


def _pick_chip(text: str):
    st.session_state.chip_question = text


from prompts import PLAN_WORDS, RECOMMEND_RULE, is_plan_request as _is_plan_request  # noqa: E402,F401


def _research_payload(research: dict) -> dict:
    """원결과와 실행 기록을 저장할 수 있는 형태(날짜는 문자열)로 바꿉니다."""
    payload = {"log": research.get("log", [])}
    cond = research.get("cond")
    if cond:
        payload["cond"] = {
            "destination": cond.destination,
            "start": cond.start.isoformat() if cond.start else None,
            "days": cond.days,
        }
    if "places" in research:
        payload["places"] = {
            "status": research["places"]["status"],
            "places": research["places"]["places"],
            "message": research["places"].get("message", ""),
        }
    if research.get("lodging"):
        payload["lodging"] = {
            "status": research["lodging"]["status"],
            "places": research["lodging"]["places"][:8],
            "message": research["lodging"].get("message", ""),
        }
    if "weather" in research:
        w = research["weather"]
        payload["weather"] = {
            "status": w["status"],
            "message": w.get("message", ""),
            "days": [
                {
                    "date": d["date"].isoformat(),
                    "tmax": d["tmax"],
                    "tmin": d["tmin"],
                    "rain_mm": d["rain_mm"],
                    "code": d.get("code"),
                }
                for d in w.get("days", [])
            ],
        }
    return payload


def _render_research(payload: dict):
    """답변 아래에 접어 둔 원결과(장소, 날씨)와 실행 기록을 보여 줍니다."""
    with st.expander("원결과와 실행 기록 보기", expanded=False):
        if "places" in payload:
            p = payload["places"]
            st.markdown("**A · 장소 조사 원결과**")
            if p["status"] == "ok":
                for item in p["places"]:
                    st.markdown(f"- {escape(item['name'])} · {escape(item['address'])} · [지도]({item['link']})")
            else:
                st.markdown(f"- 상태: {p['status']} {escape(p.get('message', ''))}")
        if "lodging" in payload:
            lg = payload["lodging"]
            st.markdown("**숙소 조사 원결과**")
            if lg["status"] == "ok":
                for item in lg["places"]:
                    st.markdown(f"- {escape(item['name'])} · {escape(item['address'])} · [지도]({item['link']})")
            else:
                st.markdown(f"- 상태: {lg['status']} {escape(lg.get('message', ''))}")
        if "weather" in payload:
            w = payload["weather"]
            st.markdown(f"**B · 날씨 조사 원결과** (상태: {w['status']})")
            for i, d in enumerate(w["days"], 1):
                _, label = WEATHER_ICONS.get(d.get("code"), ("", "정보 없음"))
                st.markdown(
                    f"- {i}일차 {d['date']} · {label} · 최고 {d['tmax']:.0f}° 최저 {d['tmin']:.0f}° · 강수 {d['rain_mm']:.1f}mm"
                )
        if payload.get("log"):
            st.markdown("**실행 기록**")
            for entry in payload["log"]:
                st.markdown(
                    f"- `{entry['tool']}` · 입력: {escape(str(entry['input']))} · 상태: {entry['status']} · 결과 {entry['count']}건"
                )


def _legacy_turn(question: str, stage_ph):
    """기존 방식(AGENT_MODE=legacy): 판단과 조사, 답변 작성이 이 함수 안에 한데 들어 있습니다.
    모듈형 방식에 문제가 생겼을 때 되돌아가기 위해 그대로 보존합니다."""
    trip = TripInfo()
    research = None
    # 질문에 적힌 날짜, 여행지, 박 수를 먼저 찾고, 질문 종류(일정, 장소 조회, 대화)를 정합니다.
    user_text_all = "\n".join(
        [m["content"] for m in st.session_state.history if m["role"] == "user"] + [question.strip()]
    )
    with st.spinner("질문 종류를 확인하는 중..."):
        trip = extract_trip(user_text_all, date.today())
        if _is_plan_request(question):
            route = "일정"
        else:
            route = route_question(question)
            pending = st.session_state.get("plan_pending", False)
            if pending and route in ("대화", "일정"):
                # 일정 짜기 도중 되물음에 답한 경우(예: "블루보트", "2명 보통")도 일정으로 이어 갑니다.
                # 날씨·장소 조회처럼 다른 용건이면 그대로 따로 처리합니다.
                route = "일정"
            after_plan = st.session_state.get("plan_done", False) or "일차" in (st.session_state.get("last_answer") or "")
            if pending and route == "일정":
                pass
            elif route in ("대화", "일정") and trip.destination:
                # 일정을 짜 달라는 말이 없으면 가볼 만한 곳만 먼저 추천합니다.
                # 이미 일정이 나온 대화의 이어 질문("인천은?")은 일정으로 이어 갑니다.
                route = "일정" if after_plan else "추천"
            elif route == "일정":
                route = "대화"

    if route in ("장소조회", "날씨"):
        # 장소·날씨 에이전트: 도구를 부르고, 결과를 보고 다시 찾거나 답합니다.
        labels = {code: label for code, (_, label) in WEATHER_ICONS.items()}
        with st.spinner("장소나 날씨를 조회하는 중..."):
            out = run_lookup(question.strip(), st.session_state.history, labels=labels)
        answer = out["answer"]
        research = {"log": out["log"]}
        st.markdown(_clean(answer))
    elif route == "추천":
        # 추천 파이프라인: 장소와 날씨를 조회하고, 일정표 없이 가볼 만한 곳만 추천합니다.
        cond = Conditions(trip.destination, trip.start_date, trip.days)
        log = []
        _stage(stage_ph, 0)
        places = collect_places(cond, log, kinds=WIDE_KINDS)
        _stage(stage_ph, 1)
        lodging = collect_lodging(cond, log, near=places["places"][:8])
        _stage(stage_ph, 2)
        weather = collect_weather(cond, log)
        labels = {code: label for code, (_, label) in WEATHER_ICONS.items()}
        context = build_context(cond, places, weather, labels, lodging)
        model_question = question.strip() + f"\n\n{context}\n\n{RECOMMEND_RULE}"
        _stage(stage_ph, 3)
        answer = ask(model_question, st.session_state.history, effort=REASONING["chat"])
        # 일정 짜기 버튼을 누르면 쓰도록, 답변에 실제로 나온 장소를 기억해 둡니다.
        st.session_state.recommended_places = [p for p in places["places"] if p["name"] in answer]
        st.session_state.recommended_lodging = [p for p in lodging["places"] if p["name"] in answer]
        research = {"cond": cond, "places": places, "weather": weather, "lodging": lodging, "log": log}
        stage_ph.empty()
        _render_answer(answer, _research_payload(research), key=f"h{len(st.session_state.history) + 1}")
    elif route == "일정":
        # 일정 파이프라인: 장소(A)와 날씨(B)를 따로 조회하고, 조회 사실만 근거로 계획을 씁니다.
        cond = Conditions(trip.destination, trip.start_date, trip.days)
        log: list[dict] = []
        with nullcontext():
            _stage(stage_ph, 0)
            places = collect_places(cond, log) if cond.destination else {"status": "missing", "places": [], "message": ""}
            # 일정 짜기 버튼에서 온 요청이면, 직전에 추천한 장소를 후보 맨 앞에 두고 일정에 꼭 넣습니다.
            from_rec = st.session_state.pop("from_recommend", False) or st.session_state.get("plan_pending", False)
            preferred = st.session_state.get("recommended_places", []) if from_rec else []
            preferred_lodging = st.session_state.get("recommended_lodging", []) if from_rec else []
            if preferred:
                names = {p["name"] for p in preferred}
                places = {**places, "status": "ok", "places": preferred + [p for p in places["places"] if p["name"] not in names]}
            _stage(stage_ph, 1)
            lodging = collect_lodging(cond, log, near=places["places"][:8]) if cond.destination else None
            if lodging and preferred_lodging:
                lnames = {p["name"] for p in preferred_lodging}
                lodging = {**lodging, "status": "ok", "places": preferred_lodging + [p for p in lodging["places"] if p["name"] not in lnames]}
            _stage(stage_ph, 2)
            weather = collect_weather(cond, log)
        labels = {code: label for code, (_, label) in WEATHER_ICONS.items()}
        context = build_context(cond, places, weather, labels, lodging) if cond.destination else None
        if context and preferred_lodging:
            context += "\n[숙소 후보] " + ", ".join(p["name"] for p in preferred_lodging) + " — 앞서 추천한 숙소 후보입니다. 사용자가 고른 곳이 있으면 그곳, 없으면 동선에 맞는 1곳만 정해 모든 밤의 숙소로 씁니다. 후보를 모두 쓸 필요는 없습니다."
        if context and preferred:
            context += (
                "\n[우선 후보 장소] " + ", ".join(p["name"] for p in preferred)
                + " — 앞서 추천한 곳입니다. 기간·인원·일정 강도에 맞게 이 중에서 골라 씁니다(모두 넣을 필요 없음). "
                + "되묻지 말고 바로 풀코스(일차별 표, 식사, 숙소 포함)로 작성합니다."
            )
        model_question = question.strip() + (f"\n\n{context}" if context else "")
        _stage(stage_ph, 3)
        answer = ask(model_question, st.session_state.history, effort=REASONING["plan"])
        research = {"cond": cond, "places": places, "weather": weather, "lodging": lodging, "log": log}
        stage_ph.empty()
        _render_answer(answer, _research_payload(research), key=f"h{len(st.session_state.history) + 1}")
    else:
        # 일반 대화: 추론을 낮춰 빠르게 답합니다.
        with st.spinner("답변을 만드는 중..."):
            answer = ask(question.strip(), st.session_state.history, effort=REASONING["chat"])
        st.markdown(_clean(answer))

    if route == "일정":
        # 일정을 못 짰으면(되물음) 다음 답변도 일정으로 이어 가고, 짰으면 추천 기억을 지웁니다.
        if "일차" in answer:
            st.session_state.plan_pending = False
            st.session_state.pop("recommended_places", None)
            st.session_state.pop("recommended_lodging", None)
        else:
            st.session_state.plan_pending = True
    else:
        st.session_state.plan_pending = False
    if "일차" in answer:
        _scroll_to_latest_answer()
    return route, answer, research, trip


def _modular_turn(question: str, stage_ph):
    """모듈형 방식(AGENT_MODE=modular): 판단과 조사, 작성은 agents.py 가 하고, 여기서는 화면 표시와 기억 갱신만 합니다."""
    ss = st.session_state
    memory = agents.Memory(
        history=ss.history,
        last_answer=ss.get("last_answer") or "",
        plan_done=ss.get("plan_done", False),
        plan_pending=ss.get("plan_pending", False),
        recommended_places=ss.get("recommended_places", []),
        recommended_lodging=ss.get("recommended_lodging", []),
        from_recommend=ss.pop("from_recommend", False),
    )
    labels = {code: label for code, (_, label) in WEATHER_ICONS.items()}
    phase_steps = ["질문 확인", "조회", "답변 쓰기"]
    phase_index = {"classify": 0, "lookup": 1, "chat": 2}

    def on_phase(kind: str, i: int):
        if kind == "stage":
            _stage(stage_ph, i)
        else:
            stage_ph.markdown(ui_cards.stage_html(phase_steps, phase_index[kind]), unsafe_allow_html=True)

    turn = agents.handle(question.strip(), memory, labels, on_phase)

    # 다음 질문을 위한 기억 갱신
    ss.plan_pending = turn.plan_pending
    if turn.recommended_places is not None:
        ss.recommended_places = turn.recommended_places
        ss.recommended_lodging = turn.recommended_lodging or []
    if turn.clear_recommended:
        ss.pop("recommended_places", None)
        ss.pop("recommended_lodging", None)

    stage_ph.empty()
    if turn.route in ("추천", "일정"):
        _render_answer(turn.answer, _research_payload(turn.research), key=f"h{len(ss.history) + 1}")
    else:
        st.markdown(_clean(turn.answer))
    if "일차" in turn.answer:
        _scroll_to_latest_answer()
    return turn.route, turn.answer, turn.research, turn.trip


def _run_turn(question: str, stage_ph):
    """AGENT_MODE 에 따라 모듈형 또는 기존 방식으로 질문을 처리합니다."""
    if get_agent_mode() == "modular":
        return _modular_turn(question, stage_ph)
    return _legacy_turn(question, stage_ph)


def _chat_turn():
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("chat_id", None)
    st.title("여행 질문")
    st.caption(f"이전 질문과 답변을 기억합니다. 다른 여행지를 보려면 새 대화를 시작하세요. (모델: {get_model_name()})")
    st.button("새 대화 시작", on_click=_reset_chat)

    if not st.session_state.history:
        with st.chat_message("assistant"):
            st.markdown(
                "안녕하세요, 여행 도우미 **여행이**입니다. 어디로 떠나고 싶으신가요? "
                "기간, 인원, 여행 목적을 알려 주시면 일정을 짜 드릴게요."
            )
    if not st.session_state.history and not st.session_state.get("chip_question"):
        st.caption("이렇게 물어보세요")
        cols = st.columns(2)
        for i, text in enumerate(EXAMPLE_CHIPS):
            with cols[i % 2]:
                st.button(text, key=f"chip_{i}", on_click=_pick_chip, args=(text,), use_container_width=True)

    for n, item in enumerate(st.session_state.history):
        with st.chat_message(item["role"]):
            _render_answer(item["content"], item.get("research"), key=f"h{n}" if item["role"] == "assistant" else None)
            if item.get("research"):
                _render_research(item["research"])

    question = st.chat_input(
        "여행 질문을 입력하세요. 예: 혼자서 3박 4일 부산 여행, 휴식 위주로 가고 싶어요.",
        max_chars=MAX_QUESTION_CHARS,
    )
    if question is None and st.session_state.get("chip_question"):
        question = st.session_state.pop("chip_question")
    if question is None and st.session_state.get("auto_question"):
        # '일정 짜기' 버튼을 누르면 이 질문이 대신 들어옵니다.
        question = st.session_state.pop("auto_question")
        st.session_state.from_recommend = True
    if question is None:
        return
    if not question.strip():
        st.toast("질문이 비어 있습니다.")
        return

    with st.chat_message("user"):
        st.markdown(question.strip())
    trip = TripInfo()
    research = None
    with st.chat_message("assistant"):
        stage_ph = st.empty()
        try:
            route, answer, research, trip = _run_turn(question, stage_ph)
        except ChatbotError as e:
            stage_ph.empty()
            # 실패한 질문은 기록에 남기지 않습니다. 다음 질문의 문맥에 들어가지 않도록 하기 위해서입니다.
            st.error(str(e))
            return

    st.session_state.history.append({"role": "user", "content": question.strip()})
    assistant_item = {"role": "assistant", "content": answer}
    if research:
        assistant_item["research"] = _research_payload(research)
        _render_research(assistant_item["research"])
    st.session_state.history.append(assistant_item)
    st.session_state.last_answer = answer
    if "일차" in answer:
        st.session_state.plan_done = True
        st.session_state.plan_meta = {
            "destination": trip.destination,
            "start": trip.start_date.isoformat() if trip.start_date else None,
            "days": trip.days,
        }
    # 일정이 한 번 나온 대화에서는 '일정 짜기' 버튼을 다시 보이지 않습니다.
    st.session_state.recommend_only = route == "추천" and not st.session_state.get("plan_done", False)
    # 일정 답변이면 찾아 둔 시작일을 날씨 칸의 기본값으로 씁니다.
    st.session_state.plan_start_suggest = trip.start_date if "일차" in answer else None
    # 성공한 대화는 파일에 저장합니다. 같은 대화는 같은 id 로 덮어씁니다.
    st.session_state.chat_id = chat_store.save_chat(st.session_state.get("chat_id"), st.session_state.history)


def _verify_block():
    """마지막 답변의 장소를 카카오맵으로 확인합니다. 결과는 그 답변에 대한 것만 보여 줍니다."""
    answer = st.session_state.get("last_answer")
    # 일정 답변(일차별 구성)에만 검증합니다. 되묻는 질문이나 일반 답변에는 나오지 않습니다.
    if not answer or "일차" not in answer:
        return

    # 같은 답변은 한 번만 검증합니다. 날씨 날짜를 바꾸는 등 화면이 다시 그려져도 다시 돌리지 않습니다.
    result = st.session_state.get("verify_result")
    if not result or result.get("answer") != answer:
        # 일정 답변은 이미 위에 나와 있고, 검증이 도는 동안만 로딩 표시를 보입니다.
        # 끝나면 로딩 표시는 사라지고, 결과는 아래의 접힌 상자에서 볼 수 있습니다.
        with st.spinner("일정 장소를 카카오맵으로 검증하는 중입니다..."):
            try:
                results = verify_places(extract_places(answer))
                dists = day_distances(results)
                result = {"answer": answer, "results": results, "dists": dists}
            except (ChatbotError, KakaoError) as e:
                result = {"answer": answer, "error": str(e)}
        st.session_state.verify_result = result

    if "error" in result:
        st.error(result["error"])
        return

    results = result["results"]
    if not results:
        st.info("답변에서 검증할 장소를 찾지 못했습니다. 일정 답변에서 다시 눌러 주세요.")
        return
    if not result.get("plan_id"):
        # 검증을 마친 일정은 '캘린더 등록' 메뉴에서 다시 열 수 있게 저장합니다.
        meta = st.session_state.get("plan_meta") or {}
        result["plan_id"] = plan_store.save_plan(
            answer, results, result.get("dists", []), meta.get("destination"), meta.get("start"), meta.get("days")
        )
        st.session_state.cal_plan_id = result["plan_id"]
        st.toast("일정을 '캘린더 등록' 메뉴에 저장했어요.")
    found = [r for r in results if r["found"] is not None]
    # 검증 결과 표는 길어서 접어 둡니다. 눌러야 열립니다.
    with st.expander(
        f"카카오맵 검증 결과 보기 ({len(found)}곳 확인 / {len(results) - len(found)}곳 찾지 못함)",
        expanded=False,
    ):
        _plan_table(results)
        if result["dists"]:
            st.markdown("**같은 날 이동 거리 (직선 기준)**")
            for d in result["dists"]:
                km = d["meters"] / 1000
                st.markdown(f"- {d['day']}일차 · {escape(d['from'])} → {escape(d['to'])}: 약 {km:.1f}km")
        st.caption("직선 거리이므로 실제 이동 시간은 교통수단에 따라 달라집니다.")
    _plan_weather_block(results)


def _plan_weather_block(results: list[dict]):
    """여행 시작일을 고르면 일차별 대표 장소의 날씨를 동시에 가져와 보여 줍니다."""
    # 대화에서 찾은 시작일을 기본값으로 넣습니다. 찾은 날짜가 바뀌면 칸도 새로 만듭니다.
    suggest = st.session_state.get("plan_start_suggest")
    start = st.date_input(
        "여행 시작일 (대화에서 찾지 못했다면 직접 골라 주세요)",
        value=suggest or None,
        min_value=date.today(),
        max_value=date.today() + timedelta(days=365),
        key=f"plan_start_{suggest}",
    )
    if not start:
        return

    # 일차마다 카카오에서 찾은 첫 관광지의 좌표를 대표 좌표로 씁니다.
    # 그 일차에 관광지 좌표가 없으면 같은 일차의 다른 장소, 그래도 없으면 전체에서 찾은 첫 장소를 씁니다.
    kakao_places = [r for r in results if r.get("source") == "kakao" and r["found"] and r.get("day")]
    points = {}
    for r in kakao_places:
        if r["kind"] == "관광지" and r["day"] not in points:
            points[r["day"]] = (r["found"]["lat"], r["found"]["lon"])
    fallback_any = next(((r["found"]["lat"], r["found"]["lon"]) for r in kakao_places), None)
    for day in sorted({r["day"] for r in results if r.get("day")}):
        if day in points:
            continue
        same_day = next((r for r in kakao_places if r["day"] == day), None)
        if same_day:
            points[day] = (same_day["found"]["lat"], same_day["found"]["lon"])
        elif fallback_any:
            points[day] = fallback_any
    if not points:
        st.info("날씨를 찾을 장소 좌표가 없습니다. 카카오에서 확인된 관광지가 있어야 합니다.")
        return

    try:
        with st.spinner("일차별 날씨를 가져오는 중..."):
            weather = get_plan_weather(points, start)
    except TravelDataError as e:
        st.error(str(e))
        return

    st.markdown("**일차별 날씨 (대표 관광지 기준)**")
    for day in sorted(weather):
        w = weather[day]
        d = start + timedelta(days=day - 1)
        if not w:
            st.markdown(f"- {day}일차 · {d.month}/{d.day} · 날씨를 가져오지 못했습니다")
            continue
        icon, label = WEATHER_ICONS.get(w.get("code"), ("🌡️", "정보 없음"))
        st.markdown(
            f"- {day}일차 · {d.month}/{d.day} ({WEEKDAYS[d.weekday()]}) · {icon} {label} · "
            f"최고 {w['tmax']:.0f}° 최저 {w['tmin']:.0f}° · 강수 {w['rain_mm']:.1f}mm"
        )
    if any(w and w.get("source") == "history" for w in weather.values()):
        st.caption("예보 범위 밖 날짜는 작년 같은 날의 기록을 참고용으로 보여 드립니다.")


PLAN_TABLE_CSS = """
<style>
  .plan-wrap { overflow-x: auto; }
  .plan-table { width: 100%; border-collapse: separate; border-spacing: 0; background: var(--toss-card);
    border-radius: 16px; overflow: hidden; box-shadow: 0 2px 8px rgba(25, 31, 40, 0.06); font-size: 0.93rem; }
  .plan-table th { background: var(--toss-blue-soft); color: var(--toss-soft-text); font-weight: 700; text-align: left; padding: 10px 12px; }
  .plan-table td { color: var(--toss-text); padding: 10px 12px; border-top: 1px solid var(--toss-line); vertical-align: top; }
  .plan-day { font-weight: 800; color: #3182F6; white-space: nowrap; }
  .plan-missing { color: var(--toss-sub); }
  .plan-tag { display: inline-block; background: var(--toss-bg); border-radius: 8px; padding: 2px 8px; font-size: 0.82rem; }
  .plan-table { animation: fade-up 0.5s ease-out both; }
  .plan-table tbody tr { transition: background 0.2s ease, transform 0.2s ease; }
  .plan-table tbody tr:hover td { background: var(--toss-hover); }
  .plan-table tbody tr:hover { transform: translateX(3px); }
</style>
"""

SLOT_ORDER = {"오전": 1, "점심": 2, "오후": 3, "저녁": 4, "숙박": 5, "": 6}


def _plan_table(results: list[dict]):
    """검증된 장소를 날짜별 표로 보여 줍니다. 시간대 순서로 정렬합니다."""
    rows = sorted(
        results,
        key=lambda r: (r.get("day") or 99, SLOT_ORDER.get(r.get("slot", ""), 6)),
    )
    parts = [
        PLAN_TABLE_CSS,
        '<div class="plan-wrap"><table class="plan-table"><thead><tr>'
        "<th>일차</th><th>시간</th><th>구분</th><th>장소</th><th>주소</th>"
        "</tr></thead><tbody>",
    ]
    for r in rows:
        day = f"{r['day']}일차" if r.get("day") else "미정"
        slot = escape(r.get("slot") or "-")
        kind = f'<span class="plan-tag">{escape(r["kind"])}</span>'
        if r["found"] and r.get("source") == "web":
            # 카카오맵에는 없고 웹 검색에서만 확인된 곳입니다. 주소 대신 출처 링크를 보입니다.
            name = f"{escape(r['query'])} <span class='plan-tag'>웹 확인</span>"
            url = escape(r["found"].get("url", ""))
            addr = f"<a href='{url}' target='_blank'>출처 보기</a>" if url else "-"
            cls = ""
        elif r["found"]:
            name = escape(r["found"]["name"])
            addr = escape(r["found"]["address"])
            cls = ""
        else:
            name = f"{escape(r['query'])} (찾지 못함)"
            addr = "-"
            cls = ' class="plan-missing"'
        parts.append(
            f'<tr{cls}><td class="plan-day">{day}</td><td>{slot}</td>'
            f"<td>{kind}</td><td>{name}</td><td>{addr}</td></tr>"
        )
    parts.append("</tbody></table></div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _request_plan():
    st.session_state.auto_question = "위에서 추천한 곳들을 바탕으로 일정을 짜줘."
    st.session_state.recommend_only = False


def _plan_button():
    """추천만 한 답변의 맨 아래에 '일정 짜기' 버튼을 보여 줍니다."""
    if st.session_state.get("recommend_only"):
        st.button("이 장소들로 일정 짜기", type="primary", key="make_plan_btn", on_click=_request_plan)


def chat_view():
    # 질문 처리 뒤에 검증과 일정 짜기 버튼을 그립니다. 버튼을 눌러 다시 그려져도 남도록 항상 호출합니다.
    _chat_turn()
    _verify_block()
    _plan_button()


# ---------- 저장된 대화 ----------

def _open_chat(chat_id: str):
    chat = chat_store.get_chat(chat_id)
    if chat is None:
        return
    _clear_chat_state()
    st.session_state.history = chat.get("messages", [])
    st.session_state.chat_id = chat_id
    st.session_state.menu = "여행 질문"


def _delete_chat(chat_id: str):
    chat_store.delete_chat(chat_id)
    if st.session_state.get("chat_id") == chat_id:
        _reset_chat()
    if st.session_state.get("viewing_chat") == chat_id:
        st.session_state.viewing_chat = None


def _select_saved(chat_id: str):
    st.session_state.viewing_chat = chat_id


def saved_sidebar(current_menu: str):
    """사이드바에서 '저장된 대화'를 고르면 그 아래에 들여쓴 대화 목록을 보여 줍니다."""
    if current_menu != "저장된 대화":
        return
    viewing = st.session_state.get("viewing_chat")
    with st.container(key="saved_sub"):
        chats = chat_store.load_chats()
        if not chats:
            st.caption("저장된 대화가 없습니다.")
        for chat in chats:
            chat_id = chat.get("id", "")
            col_open, col_del = st.columns([5, 1], vertical_alignment="center")
            with col_open:
                st.button(
                    chat.get("title", "대화"),
                    key=f"sub_{chat_id}",
                    type="primary" if viewing == chat_id else "secondary",
                    on_click=_select_saved,
                    args=(chat_id,),
                )
            with col_del:
                # 목록에서 바로 지웁니다. 대화 파일(chats.json)에서도 함께 빠집니다.
                st.button("×", key=f"subdel_{chat_id}", help="이 대화 삭제", on_click=_delete_chat, args=(chat_id,))


def _select_cal_plan(plan_id: str):
    st.session_state.cal_plan_id = plan_id


def _delete_cal_plan(plan_id: str):
    plan_store.delete_plan(plan_id)
    if st.session_state.get("cal_plan_id") == plan_id:
        st.session_state.cal_plan_id = None


def calendar_sidebar(current_menu: str):
    """사이드바에서 '캘린더 등록'을 고르면 그 아래에 저장된 일정 목록을 보여 줍니다."""
    if current_menu != "캘린더 등록":
        return
    selected = st.session_state.get("cal_plan_id")
    with st.container(key="saved_sub"):
        plans = plan_store.load_plans()
        if not plans:
            st.caption("저장된 일정이 없습니다.")
        for plan in plans:
            plan_id = plan.get("id", "")
            col_open, col_del = st.columns([5, 1], vertical_alignment="center")
            with col_open:
                st.button(
                    plan.get("title", "일정"),
                    key=f"calsub_{plan_id}",
                    type="primary" if selected == plan_id else "secondary",
                    on_click=_select_cal_plan,
                    args=(plan_id,),
                )
            with col_del:
                st.button("×", key=f"subdel_cal_{plan_id}", help="이 일정 삭제", on_click=_delete_cal_plan, args=(plan_id,))


def saved_view():
    st.title("저장된 대화")
    st.caption("왼쪽 목록에서 대화를 고르면 내용이 보입니다. 이어서 질문하려면 '이어서 질문하기'를 누르세요.")

    viewing = st.session_state.get("viewing_chat")
    chat = chat_store.get_chat(viewing) if viewing else None
    if chat is None:
        if not chat_store.load_chats():
            st.info("아직 저장된 대화가 없습니다. 여행 질문을 하면 자동으로 저장됩니다.")
        else:
            st.info("왼쪽 목록에서 대화를 고르세요.")
        return

    st.subheader(chat.get("title", "대화"))
    st.caption(chat.get("updated", ""))
    for item in chat.get("messages", []):
        with st.chat_message(item["role"]):
            st.markdown(_clean(item["content"]))

    c1, c2 = st.columns(2)
    c1.button("이어서 질문하기", type="primary", key="continue_chat", on_click=_open_chat, args=(viewing,))
    c2.button("이 대화 삭제", key="delete_chat", on_click=_delete_chat, args=(viewing,))


# ---------- 인기 여행지 ----------

def _fetch_popular(request: str) -> list[dict]:
    data = complete_json(POPULAR_PROMPT, request, effort=REASONING["list"])
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ChatbotError("추천 목록을 읽지 못했습니다. 다시 시도해 주세요.")
    return items[:5]


def _popular_block(key: str, request: str):
    cache = st.session_state.setdefault("popular_cache", {})
    if st.button("추천 불러오기 / 새로고침", key=f"pop_btn_{key}"):
        try:
            with st.spinner("추천 여행지를 고르는 중..."):
                cache[key] = _fetch_popular(request)
        except ChatbotError as e:
            st.error(str(e))

    items = cache.get(key)
    if not items:
        st.info("버튼을 눌러 추천을 불러오세요.")
        return

    cols = st.columns(2)
    for i, item in enumerate(items):
        with cols[i % 2]:
            with st.container(border=True):
                name = escape(str(item.get("name", "")))
                country = escape(str(item.get("country", "")))
                st.markdown(f"**{name}** · {country}")
                st.write(str(item.get("reason", "")))
                st.caption(f"좋은 시기: {item.get('best_season', '-')} · 권장 일정: {item.get('trip_length', '-')}")
                spots = item.get("spots") or []
                if spots:
                    st.markdown("**핵심 스팟**")
                    for spot in spots[:3]:
                        st.markdown(f"- {escape(str(spot))}")
                if item.get("recommended_for"):
                    st.markdown(f"**이런 분께 추천**: {escape(str(item['recommended_for']))}")
                if item.get("tip"):
                    st.caption(f"꿀팁: {item['tip']}")


@st.cache_data(ttl=21600, show_spinner=False)
def _cached_rankings():
    return fetch_domestic_rankings()


def _ranking_list(title: str, rows: list[dict], value_key: str, unit: str):
    st.markdown(f"**{title}**")
    for i, row in enumerate(rows[:10], start=1):
        place = escape(f"{row['sido']} {row['sigungu']}")
        st.markdown(f"{i}. {place} · {escape(str(row[value_key]))}{unit}")


def _domestic_block():
    try:
        data = _cached_rankings()
    except TravelDataError as e:
        st.info(str(e))
        return

    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            _ranking_list("한국인이 많이 가는 곳 TOP 10", data["korean"], "visitors", "만명")
    with col2:
        with st.container(border=True):
            _ranking_list("10월 성수기 붐비는 곳 TOP 10", data["peak"], "ratio", "배 (평소 대비)")
    st.caption(
        f"{data['source']} · 방문 데이터는 약 한 달 늦게 공개되어 성수기 순위는 작년 같은 달 기준입니다."
    )


def popular_view():
    st.title("인기 여행지")
    st.caption("국내는 방문 데이터 랭킹, 해외는 AI 추천입니다. " + AI_NOTICE)

    tab_domestic, tab_short, tab_long = st.tabs(
        ["국내", "해외 단기 (3박 4일 이내)", "해외 장기 (1주일 이상)"]
    )
    with tab_domestic:
        _domestic_block()
    with tab_short:
        _popular_block("short", "3박 4일 이내 짧게 다녀올 수 있는 해외 여행지 5곳을 골라 주세요.")
    with tab_long:
        _popular_block("long", "1주일 이상 여유 있게 머물기 좋은 해외 여행지 5곳을 골라 주세요.")


# ---------- 여행지 비교 ----------

def _fetch_compare(a: str, b: str) -> dict:
    data = complete_json(COMPARE_PROMPT, f"여행지 A: {a}\n여행지 B: {b}", effort=REASONING["list"])
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ChatbotError("비교 결과를 읽지 못했습니다. 다시 시도해 주세요.")
    return data


def _render_compare(a: str, b: str, data: dict):
    st.markdown(COMPARE_CSS, unsafe_allow_html=True)
    parts = [
        '<div class="cmp-grid">',
        '<div class="cmp-cell cmp-label"></div>',
        f'<div class="cmp-cell cmp-title">{escape(a)}</div>',
        f'<div class="cmp-cell cmp-title">{escape(b)}</div>',
    ]
    for row in data.get("rows", []):
        parts.append(f'<div class="cmp-cell cmp-label">{escape(str(row.get("label", "")))}</div>')
        parts.append(f'<div class="cmp-cell">{escape(str(row.get("a", "")))}</div>')
        parts.append(f'<div class="cmp-cell">{escape(str(row.get("b", "")))}</div>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)

    verdict = data.get("verdict")
    if verdict:
        st.markdown(f'<div class="cmp-verdict">{escape(str(verdict))}</div>', unsafe_allow_html=True)
    st.caption(AI_NOTICE)


def compare_view():
    st.title("여행지 비교")
    st.caption("두 여행지를 기간, 날씨, 예산, 볼거리 기준으로 나란히 봅니다.")

    col1, col2 = st.columns(2)
    a = col1.text_input("여행지 A", placeholder="예: 부산", max_chars=50)
    b = col2.text_input("여행지 B", placeholder="예: 제주", max_chars=50)

    if st.button("비교하기", type="primary"):
        a, b = a.strip(), b.strip()
        if not a or not b:
            st.warning("두 여행지를 모두 입력해 주세요.")
        elif a == b:
            st.warning("서로 다른 여행지를 입력해 주세요.")
        else:
            try:
                with st.spinner("비교하는 중..."):
                    st.session_state.compare_result = (a, b, _fetch_compare(a, b))
            except ChatbotError as e:
                st.error(str(e))

    result = st.session_state.get("compare_result")
    if result:
        _render_compare(*result)


# ---------- 날씨 ----------

def weather_view():
    st.title("날씨 보기")
    st.caption("여행 날짜를 고르면 그 기간의 날씨를 보여 드립니다.")

    place = st.text_input("여행지", placeholder="예: 부산", max_chars=50)

    today = date.today()
    picked = st.date_input(
        "여행 기간",
        value=(today + timedelta(days=30), today + timedelta(days=33)),
        min_value=today,
        max_value=today + timedelta(days=365),
    )

    if st.button("날씨 보기", type="primary"):
        if not place.strip():
            st.warning("여행지를 입력해 주세요.")
        elif not isinstance(picked, (tuple, list)) or len(picked) != 2:
            st.warning("여행 시작일과 종료일을 모두 골라 주세요.")
        else:
            start, end = picked
            if end < start:
                st.warning("종료일은 시작일 이후로 골라 주세요.")
            elif (end - start).days > 29:
                st.warning("한 번에 30일까지만 볼 수 있습니다.")
            else:
                try:
                    with st.spinner("날씨를 불러오는 중..."):
                        place_info = geocode(place.strip())
                        weather = get_daily_weather(place_info["lat"], place_info["lon"], start, end)
                    st.session_state.weather_result = (place_info, weather)
                except TravelDataError as e:
                    st.error(str(e))

    result = st.session_state.get("weather_result")
    if not result:
        return

    place_info, weather = result
    st.subheader(f"{place_info['name']} ({place_info['country']})")
    if weather["source"] == "history":
        # 예보가 없는 날짜는 작년 같은 날의 기록입니다. 예보가 아니라는 점을 분명히 보여 줍니다.
        st.warning("작년 기록입니다 (예보 아님). 예보 범위(15일) 밖이라 작년 같은 기간의 실제 날씨를 참고용으로 보여 드립니다. 실제 날씨는 출발 직전 예보로 확인하세요.")
    else:
        st.info(weather["note"])

    days = weather["days"]
    for i in range(0, len(days), 3):
        cols = st.columns(3)
        for col, day in zip(cols, days[i : i + 3]):
            d = day["date"]
            with col:
                icon, label = WEATHER_ICONS.get(day.get("code"), ("🌡️", "정보 없음"))
                with st.container(border=True):
                    st.markdown(f"**{d.month}/{d.day} ({WEEKDAYS[d.weekday()]})**")
                    if weather["source"] == "history":
                        st.caption("작년 기록")
                    st.markdown(f"<div style='font-size:2.2rem;line-height:1.2'>{icon}</div>", unsafe_allow_html=True)
                    st.markdown(f"**{label}**")
                    st.write(f"최고 {day['tmax']:.0f}° · 최저 {day['tmin']:.0f}°")
                    st.caption(f"강수량 {day['rain_mm']:.1f}mm")


# ---------- 캘린더 등록 (실습 4) ----------

def _cal_status_line(label: str, ok: bool):
    st.markdown(ui_cards.badge(("✓ " if ok else "✕ ") + label, "ok" if ok else "bad"), unsafe_allow_html=True)


WEEKDAYS = "월화수목금토일"


def _event_cards_html(rows: list[dict]) -> str:
    """등록할 일정을 날짜별 카드로 보여 줍니다. 표에서 고치면 카드도 바로 바뀝니다."""
    by_day: dict[str, list[dict]] = {}
    for r in sorted(rows, key=lambda r: (str(r.get("date")), str(r.get("start")))):
        by_day.setdefault(str(r.get("date")), []).append(r)
    out = []
    for day, items in by_day.items():
        try:
            d = date.fromisoformat(day)
            label = f"{d.month}월 {d.day}일 ({WEEKDAYS[d.weekday()]})"
        except ValueError:
            label = day or "날짜 없음"
        out.append(f'<div class="ev-day">{escape(label)}</div>')
        for r in items:
            warn = bool(cal.validate_row(r))
            loc = f'<div class="ev-loc">📍 {escape(str(r.get("location") or ""))}</div>' if r.get("location") else ""
            out.append(
                f'<div class="ev-card {"warn" if warn else ""}"><span class="ev-time">{escape(str(r.get("start")))}–{escape(str(r.get("end")))}</span>'
                f'<div><div class="ev-title">{escape(str(r.get("title") or "(제목 없음)"))}</div>{loc}</div></div>'
            )
    return "".join(out)


CAL_STEPS = ["① 연결 확인", "② 일정 선택", "③ 내용 확인", "④ 등록"]


def _cal_steps_html() -> str:
    """지금 어느 단계인지 보여 주는 진행 표시줄."""
    ready = (st.session_state.get("cal_ready") or {}).get("ready", False)
    has_plan = plan_store.get_plan(st.session_state.get("cal_plan_id") or "") is not None
    approval = st.session_state.get("cal_approval")
    registered = bool(st.session_state.get("cal_results"))
    done = [ready, has_plan, registered or (approval is not None), registered]
    now = next((i for i, d in enumerate(done) if not d), len(done))
    cells = "".join(
        f'<div class="cal-step {"done" if d else "now" if i == now else ""}">{"✓ " if d else ""}{escape(label)}</div>'
        for i, (label, d) in enumerate(zip(CAL_STEPS, done))
    )
    return f'<div class="cal-steps">{cells}</div>'


def calendar_view():
    st.title("캘린더 등록")
    st.caption("여행 일정을 미리보기로 확인하고, 확인한 일정만 연습용 캘린더에 등록합니다.")
    steps_slot = st.empty()
    try:
        _calendar_body()
    finally:
        # 버튼을 누른 결과가 반영된 뒤의 단계를 보여 주려고 맨 마지막에 그립니다.
        steps_slot.markdown(_cal_steps_html(), unsafe_allow_html=True)


def _calendar_body():

    # ① 도구 연결과 준비 상태
    st.subheader("① 연결과 준비 상태")
    c1, c2 = st.columns(2)
    if c1.button("도구 연결 확인", key="cal_btn_conn"):
        with st.spinner("MCP 서버를 실행하는 중..."):
            st.session_state.cal_conn = cal.check_connection()
    if c2.button("캘린더 준비 확인", key="cal_btn_ready"):
        with st.spinner("캘린더를 읽기 전용으로 조회하는 중..."):
            st.session_state.cal_ready = cal.check_ready()

    conn = st.session_state.get("cal_conn")
    if conn:
        if conn["connected"]:
            _cal_status_line(f"MCP 서버 연결됨 — 도구 {len(conn['tools'])}개 발견 ({', '.join(conn['tools'])})", True)
            st.caption("이것은 MCP 연결 확인일 뿐 Google 인증 성공이 아닙니다.")
        else:
            _cal_status_line("연결 실패(MCP) — 성공 표시 없음", False)
    ready = st.session_state.get("cal_ready")
    if ready:
        _cal_status_line(ready["label"], ready["ready"])
        if ready.get("checks"):
            st.caption(" · ".join(ready["checks"]))
        if ready.get("message"):
            st.caption(ready["message"])

    # ② 일정 미리보기
    st.subheader("② 일정 미리보기")
    plan = plan_store.get_plan(st.session_state.get("cal_plan_id") or "")
    if plan is None:
        st.info(
            "왼쪽 목록에서 저장된 일정을 고르세요. 아직 없다면 '여행 질문'에서 일정을 만들면, "
            "장소가 확인된 일정이 자동으로 저장됩니다."
        )
        return
    results = plan.get("results") or []
    st.markdown(f"**{escape(plan.get('title', '일정'))}** · 저장 {plan.get('updated', '')}")
    with st.expander("일정 답변 보기", expanded=False):
        st.markdown(_clean(plan.get("answer", "")))

    try:
        suggest = date.fromisoformat(plan["start"]) if plan.get("start") else None
    except ValueError:
        suggest = None
    start = st.date_input(
        "여행 시작일", value=suggest or date.today() + timedelta(days=1), key=f"cal_start_{plan['id']}_{suggest}"
    )
    source_key = f"{plan['id']}-{start}"
    if st.session_state.get("cal_source") != source_key:
        # 일정이나 시작일이 바뀌면 미리보기를 새로 만들고, 이전 확인과 결과는 지웁니다.
        st.session_state.cal_source = source_key
        st.session_state.cal_rows = cal.default_rows(results, start)
        st.session_state.pop("cal_approval", None)
        st.session_state.pop("cal_results", None)
        st.session_state.pop("cal_message", None)

    st.caption(f"대상 캘린더: {cal.mask_calendar_id()} · 현재 등록된 일정 0건(등록 전)")
    cards_slot = st.container()
    st.caption("✏️ 아래 표에서 제목, 날짜, 시간을 직접 고칠 수 있어요. 위 카드에 바로 반영됩니다.")
    edited = st.data_editor(
        st.session_state.cal_rows,
        key=f"cal_editor_{source_key}",
        num_rows="fixed",
        use_container_width=True,
        column_config={
            "title": "제목", "date": "날짜", "start": "시작", "end": "끝", "timezone": None, "location": "장소",  # 국내 일정만 다루므로 시간대(Asia/Seoul)는 화면에서 숨기고 내부 값으로만 씁니다
        },
    )
    rows = edited.to_dict("records") if hasattr(edited, "to_dict") else list(edited)
    with cards_slot:
        st.markdown(_event_cards_html(rows), unsafe_allow_html=True)
    warnings = {i + 1: w for i, row in enumerate(rows) if (w := cal.validate_row(row))}
    for no, w in warnings.items():
        st.warning(f"{no}행: {', '.join(w)}")

    # ③ 확인과 등록
    st.subheader("③ 확인하고 등록하기")
    signature = cal.rows_signature(rows)
    approval = st.session_state.get("cal_approval")

    b1, b2, b3 = st.columns(3)
    if b1.button("이 내용으로 확인", key="cal_btn_confirm", disabled=bool(warnings) or not rows):
        st.session_state.cal_approval = cal.Approval(signature)
        st.session_state.cal_message = "확인했습니다. 이제 '캘린더에 등록'을 누를 수 있습니다."
        st.session_state.pop("cal_results", None)
        st.rerun()
    if b2.button("취소", key="cal_btn_cancel", disabled=approval is None):
        st.session_state.pop("cal_approval", None)
        st.session_state.cal_message = "취소했습니다. 등록하지 않았습니다."
        st.rerun()

    changed = approval is not None and not approval.used and approval.signature != signature
    can_register = approval is not None and not approval.used and not changed
    if b3.button("캘린더에 등록", key="cal_btn_register", type="primary", disabled=not can_register):
        try:
            with st.spinner("MCP 로 등록하고 다시 조회하는 중..."):
                st.session_state.cal_results = cal.register(rows, approval)
            st.session_state.cal_message = "등록 요청을 마쳤습니다. 결과를 아래에서 확인하세요."
        except cal.ApprovalError as e:
            st.session_state.cal_message = str(e)
        st.rerun()

    if changed:
        st.warning("확인한 뒤 내용이 바뀌었습니다. 다시 확인해 주세요.")
    elif message := st.session_state.get("cal_message"):
        st.info(message)
    st.caption("등록 승인은 버튼으로만 합니다. 대화창에 '등록해 줘'라고 써도 승인되지 않습니다.")

    # ④ 결과
    st.subheader("④ 등록 결과")
    results_out = st.session_state.get("cal_results")
    if not results_out:
        st.caption("생성된 일정 0건")
        return
    created = sum(1 for r in results_out if r["outcome"].startswith("created"))
    st.caption(f"이번에 새로 만든 일정 {created}건")
    for r in results_out:
        text = cal.OUTCOME_TEXT.get(r["outcome"], r["outcome"])
        ok = r["outcome"].endswith("_match") or r["outcome"] == "exists_no_recreate"
        detail = f" ({r['message']})" if r.get("message") else ""
        st.markdown(
            f'<div class="ev-card {"ok" if ok else "warn"}"><span class="ev-time">{escape(str(r["row"].get("start")))}</span>'
            f'<div><div class="ev-title">{escape(r["row"]["title"])}</div>'
            f'<div class="ev-loc">{ui_cards.badge(("✓ " if ok else "! ") + text, "ok" if ok else "warn")}{escape(detail)}</div></div></div>',
            unsafe_allow_html=True,
        )
        if r.get("checks"):
            st.caption("대조: " + " · ".join(f"{name} {'일치' if v else '다름'}" for name, v in zip(("제목", "시작", "끝", "시간대", "장소"), r["checks"].values())))
        if r.get("link"):
            st.markdown(f"[Calendar에서 보기]({r['link']})")
    if any(r["outcome"] == "unconfirmed" for r in results_out):
        if st.button("같은 이벤트 ID로 다시 조회", key="cal_btn_requery"):
            with st.spinner("다시 조회하는 중..."):
                st.session_state.cal_results = cal.requery(results_out)
            st.rerun()

