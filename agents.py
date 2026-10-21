"""에이전트 모듈: 질문을 받아 라우터 → (조회 에이전트 | 리서처 → 작성자)로 나눠 처리합니다.

화면(views.py)을 모르는 순수 로직이라 Streamlit 없이도 부를 수 있습니다.

구성
- classify  : 질문에서 여행 정보를 뽑고, 질문 종류(장소조회, 날씨, 일정, 추천, 대화)를 정합니다. 라우터를 부릅니다.
- router    : 질문 종류를 모델로 나눕니다(추론 없음).
- lookup_agent : 장소·날씨 질문. 도구(tools.py)를 부르고 결과를 보고 다시 찾거나 답합니다(ReAct 방식).
- researcher: 일정·추천용 조사. 장소, 숙소, 날씨를 정해진 순서로 조사합니다(조사 도구 사용).
- writer_*  : 조사 결과(조회 사실)만 근거로 답변을 씁니다. 도구 없이 추론을 높여 씁니다.
- handle    : 위를 묶는 오케스트레이터. 한 번의 질문 처리 전체가 LangSmith 에서 하나의 트리로 보입니다.

모델 제약: 도구 호출은 추론 없음(none)에서만 가능합니다. 그래서 도구를 쓰는 단계(라우터, 조회 에이전트)와
추론을 높여 쓰는 단계(작성자)를 나눴습니다.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import openai

import tools
from agent import ROUTE_SCHEMA, ROUTE_SYSTEM, _lookup_system  # 질문 분류와 조회 규칙 문구는 기존과 같은 것을 씁니다
from chatbot import ChatbotError, ask
from config import REASONING, get_api_key, get_model_name
from plan_dates import TripInfo, extract_trip
from plan_pipeline import WIDE_KINDS, Conditions, build_context
from prompts import RECOMMEND_RULE, is_plan_request
from tracing import traceable, wrap_openai

MAX_TOOL_CALLS = 4
MAX_HISTORY = 10
GENERIC_ERROR = "요청을 처리할 수 없습니다. 질문 내용을 바꿔 다시 시도하세요."

LOOKUP_TOOLS = ["search_place", "get_weather"]


# ---------- 입력·출력 묶음 ----------

@dataclass
class Memory:
    """대화에서 이어받는 상태. 화면의 session_state 에서 만들어 넘깁니다."""

    history: list = field(default_factory=list)
    last_answer: str = ""
    plan_done: bool = False  # 이 대화에서 일정이 한 번 나왔는지
    plan_pending: bool = False  # 일정을 짜다가 되물어서 답을 기다리는 중인지
    recommended_places: list = field(default_factory=list)
    recommended_lodging: list = field(default_factory=list)
    from_recommend: bool = False  # '일정 짜기' 버튼에서 온 요청인지


@dataclass
class Turn:
    """한 번의 질문 처리 결과."""

    route: str
    trip: TripInfo
    answer: str
    research: dict | None  # 화면의 '원결과와 실행 기록'용
    plan_pending: bool = False
    clear_recommended: bool = False  # 일정을 짰으니 추천 기억을 지웁니다
    recommended_places: list | None = None  # 추천 답변이면 답변에 나온 장소·숙소를 기억합니다
    recommended_lodging: list | None = None


# ---------- 라우터 ----------

@traceable(run_type="chain", name="router")
def route_question(text: str) -> str:
    """질문 종류를 장소조회, 날씨, 일정, 대화 중 하나로 돌려줍니다. 실패하면 대화로 봅니다."""
    key = get_api_key()
    if not key or not text.strip():
        return "대화"
    try:
        client = wrap_openai(openai.OpenAI(api_key=key, timeout=30))
        res = client.chat.completions.create(
            model=get_model_name(),
            reasoning_effort="none",
            messages=[{"role": "system", "content": ROUTE_SYSTEM}, {"role": "user", "content": text}],
            response_format={"type": "json_schema", "json_schema": {"name": "route", "schema": ROUTE_SCHEMA, "strict": True}},
            max_completion_tokens=50,
        )
        return json.loads(res.choices[0].message.content).get("route", "대화")
    except (openai.OpenAIError, ValueError, KeyError, TypeError):
        return "대화"


@traceable(run_type="chain", name="classify")
def classify(question: str, memory: Memory) -> tuple[TripInfo, str]:
    """질문에서 날짜·여행지·박 수를 찾고, 어떤 흐름으로 처리할지 정합니다."""
    user_text_all = "\n".join([m["content"] for m in memory.history if m["role"] == "user"] + [question.strip()])
    trip = extract_trip(user_text_all, date.today())
    if is_plan_request(question):
        return trip, "일정"

    route = route_question(question)
    pending = memory.plan_pending
    if pending and route in ("대화", "일정"):
        # 일정 짜기 도중 되물음에 답한 경우(예: "블루보트", "2명 보통")도 일정으로 이어 갑니다.
        # 날씨·장소 조회처럼 다른 용건이면 그대로 따로 처리합니다.
        route = "일정"
    after_plan = memory.plan_done or "일차" in (memory.last_answer or "")
    if pending and route == "일정":
        pass
    elif route in ("대화", "일정") and trip.destination:
        # 일정을 짜 달라는 말이 없으면 가볼 만한 곳만 먼저 추천합니다.
        # 이미 일정이 나온 대화의 이어 질문("인천은?")은 일정으로 이어 갑니다.
        route = "일정" if after_plan else "추천"
    elif route == "일정":
        route = "대화"
    return trip, route


# ---------- 조회 에이전트 (도구를 부르는 ReAct 방식) ----------

def _tool_loop(system: str, history: list, question: str, tool_names: list[str], ctx: tools.ToolContext) -> str:
    key = get_api_key()
    if not key:
        return "OpenAI 키가 설정되지 않아 조회하지 못했습니다."
    client = wrap_openai(openai.OpenAI(api_key=key, timeout=90))
    messages = [{"role": "system", "content": system}]
    for item in (history or [])[-MAX_HISTORY:]:
        messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": question})

    calls = 0
    while True:
        use_tools = calls < MAX_TOOL_CALLS and not ctx.stopped
        kwargs = {"tools": tools.specs(tool_names)} if use_tools else {}
        try:
            res = client.chat.completions.create(
                model=get_model_name(),
                messages=messages,
                reasoning_effort="none",  # 도구 호출은 추론 없음에서만 가능합니다
                max_completion_tokens=1200,
                **kwargs,
            )
        except openai.OpenAIError as e:
            raise ChatbotError(GENERIC_ERROR) from e
        msg = res.choices[0].message
        if not msg.tool_calls:
            return (msg.content or "").strip()

        messages.append({"role": "assistant", "content": msg.content, "tool_calls": [t.model_dump() for t in msg.tool_calls]})
        for t in msg.tool_calls:
            calls += 1
            payload = tools.execute(t.function.name, t.function.arguments, ctx)
            messages.append({"role": "tool", "tool_call_id": t.id, "content": json.dumps(payload, ensure_ascii=False)})
        if ctx.stopped:
            ctx.log.append({"tool": "stop", "input": "", "status": "error 이후 도구 호출 중단", "count": 0})


@traceable(run_type="chain", name="lookup_agent")
def lookup_agent(question: str, history: list, labels: dict) -> dict:
    """장소·날씨 질문을 도구로 조회해 답합니다. 반환: {"answer": str, "log": [...]}"""
    ctx = tools.ToolContext(labels=labels or {})
    answer = _tool_loop(_lookup_system(date.today()), history, question, LOOKUP_TOOLS, ctx)
    return {"answer": answer, "log": ctx.log}


# ---------- 리서처 (일정·추천용 조사) ----------

def _prefer_first(found: dict, preferred: list) -> dict:
    """직전에 추천한 곳을 조사 결과 맨 앞에 둡니다. 이미 있는 곳은 중복으로 넣지 않습니다."""
    names = {p["name"] for p in preferred}
    return {**found, "status": "ok", "places": preferred + [p for p in found["places"] if p["name"] not in names]}


@traceable(run_type="chain", name="researcher")
def researcher(cond: Conditions, mode: str, memory: Memory, on_stage: Callable[[int], None]) -> dict:
    """장소 → 숙소 → 날씨 순서로 조사합니다. mode 는 'recommend'(추천) 또는 'plan'(일정)."""
    log: list = []
    if mode == "recommend":
        on_stage(0)
        places = tools.research_places(cond, log, kinds=WIDE_KINDS)
        on_stage(1)
        lodging = tools.research_lodging(cond, log, near=places["places"][:8])
        on_stage(2)
        weather = tools.research_weather(cond, log)
        return {"cond": cond, "places": places, "weather": weather, "lodging": lodging, "log": log, "preferred": [], "preferred_lodging": []}

    # 일정: '일정 짜기' 버튼이나 되물음 뒤에는 직전에 추천한 곳을 후보 맨 앞에 둡니다.
    use_pref = memory.from_recommend or memory.plan_pending
    preferred = memory.recommended_places if use_pref else []
    preferred_lodging = memory.recommended_lodging if use_pref else []
    on_stage(0)
    places = tools.research_places(cond, log) if cond.destination else {"status": "missing", "places": [], "message": ""}
    if preferred:
        places = _prefer_first(places, preferred)
    on_stage(1)
    lodging = tools.research_lodging(cond, log, near=places["places"][:8]) if cond.destination else None
    if lodging and preferred_lodging:
        lodging = _prefer_first(lodging, preferred_lodging)
    on_stage(2)
    weather = tools.research_weather(cond, log)
    return {"cond": cond, "places": places, "weather": weather, "lodging": lodging, "log": log, "preferred": preferred, "preferred_lodging": preferred_lodging}


# ---------- 작성자 (도구 없이, 조회 사실만 근거로 답변 작성) ----------

@traceable(run_type="chain", name="writer_recommend")
def writer_recommend(question: str, context: str, history: list) -> str:
    return ask(question.strip() + f"\n\n{context}\n\n{RECOMMEND_RULE}", history, effort=REASONING["chat"])


@traceable(run_type="chain", name="writer_plan")
def writer_plan(question: str, context: str | None, history: list) -> str:
    return ask(question.strip() + (f"\n\n{context}" if context else ""), history, effort=REASONING["plan"])


@traceable(run_type="chain", name="writer_chat")
def writer_chat(question: str, history: list) -> str:
    return ask(question.strip(), history, effort=REASONING["chat"])


def _plan_context(research: dict, labels: dict) -> str | None:
    cond = research["cond"]
    if not cond.destination:
        return None
    context = build_context(cond, research["places"], research["weather"], labels, research["lodging"])
    preferred, preferred_lodging = research["preferred"], research["preferred_lodging"]
    if preferred_lodging:
        context += (
            "\n[숙소 후보] " + ", ".join(p["name"] for p in preferred_lodging)
            + " — 앞서 추천한 숙소 후보입니다. 사용자가 고른 곳이 있으면 그곳, 없으면 동선에 맞는 1곳만 정해 모든 밤의 숙소로 씁니다. 후보를 모두 쓸 필요는 없습니다."
        )
    if preferred:
        context += (
            "\n[우선 후보 장소] " + ", ".join(p["name"] for p in preferred)
            + " — 앞서 추천한 곳입니다. 기간·인원·일정 강도에 맞게 이 중에서 골라 씁니다(모두 넣을 필요 없음). "
            + "되묻지 말고 바로 풀코스(일차별 표, 식사, 숙소 포함)로 작성합니다."
        )
    return context


# ---------- 오케스트레이터 ----------

@traceable(run_type="chain", name="travel_turn")
def handle(question: str, memory: Memory, labels: dict, on_phase: Callable[[str, int], None] | None = None) -> Turn:
    """한 번의 질문을 처리합니다. on_phase(종류, 번호)로 진행 상황을 알립니다.
    종류: 'classify'(질문 확인), 'lookup'(조회), 'chat'(답변 쓰기), 'stage'(일정·추천 단계 0~3)."""
    on = on_phase or (lambda *_: None)
    on("classify", 0)
    trip, route = classify(question, memory)

    if route in ("장소조회", "날씨"):
        on("lookup", 0)
        out = lookup_agent(question.strip(), memory.history, labels)
        return Turn(route, trip, out["answer"], {"log": out["log"]})

    if route in ("추천", "일정"):
        cond = Conditions(trip.destination, trip.start_date, trip.days)
        mode = "recommend" if route == "추천" else "plan"
        research = researcher(cond, mode, memory, lambda i: on("stage", i))
        on("stage", 3)
        if route == "추천":
            context = build_context(cond, research["places"], research["weather"], labels, research["lodging"])
            answer = writer_recommend(question, context, memory.history)
            return Turn(
                route, trip, answer, _public(research),
                recommended_places=[p for p in research["places"]["places"] if p["name"] in answer],
                recommended_lodging=[p for p in research["lodging"]["places"] if p["name"] in answer],
            )
        answer = writer_plan(question, _plan_context(research, labels), memory.history)
        planned = "일차" in answer
        # 일정을 못 짰으면(되물음) 다음 답변도 일정으로 이어 가고, 짰으면 추천 기억을 지웁니다.
        return Turn(route, trip, answer, _public(research), plan_pending=not planned, clear_recommended=planned)

    on("chat", 0)
    return Turn(route, trip, writer_chat(question, memory.history), None)


def _public(research: dict) -> dict:
    """화면에 넘기는 조사 결과. 내부용 후보 목록은 뺍니다."""
    return {k: research[k] for k in ("cond", "places", "weather", "lodging", "log")}
