"""도구 모듈: 모델이 부를 수 있는 도구를 한 곳에 등록하고, 같은 방식으로 실행합니다.

- 도구 하나 = 이름 + 모델에게 보여 줄 설명(schema) + 실행 함수 + 중복 판단 방식.
- 실행은 execute() 하나로 합니다. 중복 호출 건너뛰기, 실행 기록, 오류 시 중단 표시를 여기서 공통으로 처리합니다.
- 새 도구는 REGISTRY 에 Tool 을 하나 더 등록하면 됩니다. 에이전트 코드는 바꾸지 않습니다.
- LangSmith 추적이 켜져 있으면 도구 실행이 '도구' 항목으로 기록됩니다.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from kakao_places import KakaoError, search_places
from plan_pipeline import Conditions, collect_lodging, collect_places, collect_weather
from tracing import traceable
from travel_data import TravelDataError, get_trip_weather


@dataclass
class ToolContext:
    """한 번의 질문 처리 동안 도구들이 함께 쓰는 상태."""

    labels: dict = field(default_factory=dict)  # 날씨 코드 → 한글 설명
    log: list = field(default_factory=list)  # 실행 기록(화면의 '원결과와 실행 기록'에 표시)
    seen: set = field(default_factory=set)  # 이미 부른 호출(중복 판단용)
    stopped: bool = False  # 오류가 나면 True. 이후 도구를 더 부르지 않습니다.


@dataclass(frozen=True)
class Tool:
    name: str
    schema: dict  # OpenAI 함수 도구 형식
    signature: Callable[[dict], str]  # 같은 호출인지 가르는 키. 빈 문자열이면 잘못된 호출로 봅니다.
    log_input: Callable[[dict], str]  # 실행 기록에 적을 입력 요약
    dup_message: str  # 중복일 때 모델에게 돌려줄 말
    run: Callable[[dict, ToolContext], dict]


# ---------- 장소 검색 ----------

def _search_place(args: dict, ctx: ToolContext) -> dict:
    query = str(args.get("query", "")).strip()
    try:
        places = search_places(query, size=5)
        payload = {
            "status": "ok",
            "count": len(places),
            "places": [{"name": p["name"], "address": p["address"], "link": p["link"]} for p in places],
        }
    except KakaoError as e:
        payload = {"status": "error", "count": 0, "message": str(e), "places": []}
    ctx.log.append({"tool": "search_place", "input": query, "status": payload["status"], "count": payload["count"]})
    return payload


# ---------- 날씨 조회 ----------

def _get_weather(args: dict, ctx: ToolContext) -> dict:
    destination = str(args.get("destination", "")).strip()
    date_text = str(args.get("date", "")).strip()
    log_input = f"{destination} {date_text}"
    try:
        day = date.fromisoformat(date_text)
    except ValueError:
        ctx.log.append({"tool": "get_weather", "input": log_input, "status": "bad_date", "count": 0})
        return {"status": "bad_date", "message": "날짜 형식이 YYYY-MM-DD 가 아닙니다."}
    try:
        w = get_trip_weather(destination, day, 1)
    except TravelDataError as e:
        ctx.log.append({"tool": "get_weather", "input": log_input, "status": "error", "count": 0})
        return {"status": "error", "message": str(e)}

    ctx.log.append({"tool": "get_weather", "input": log_input, "status": w["status"], "count": len(w["days"])})
    if w["status"] != "ok":
        return {"status": "out_of_range", "message": "예보 범위 밖이라 날씨를 알 수 없습니다."}
    d = w["days"][0]
    return {
        "status": "ok",
        "date": d["date"].isoformat(),
        "weather": ctx.labels.get(d.get("code"), "정보 없음"),
        "tmax": round(d["tmax"]),
        "tmin": round(d["tmin"]),
        "rain_mm": round(d["rain_mm"], 1),
    }


SEARCH_PLACE = Tool(
    name="search_place",
    schema={
        "type": "function",
        "function": {
            "name": "search_place",
            "description": "카카오맵에서 장소를 검색한다. '지역 + 장소 종류 단어 하나'로 짧게 넣는다. 예: '경주 박물관'",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "지역 + 장소 종류"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    signature=lambda a: f"search_place:{str(a.get('query', '')).strip()}" if str(a.get("query", "")).strip() else "",
    log_input=lambda a: str(a.get("query", "")).strip(),
    dup_message="같은 검색어입니다. 다른 검색어를 쓰세요.",
    run=_search_place,
)

GET_WEATHER = Tool(
    name="get_weather",
    schema={
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "여행지의 특정 날짜 날씨 예보를 조회한다. 날짜는 YYYY-MM-DD 로 넣는다. 예보 범위 밖이면 예보 없음을 돌려준다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string", "description": "여행지 이름. 예: 경주"},
                    "date": {"type": "string", "description": "YYYY-MM-DD"},
                },
                "required": ["destination", "date"],
                "additionalProperties": False,
            },
        },
    },
    signature=lambda a: f"get_weather:{str(a.get('destination', '')).strip()}:{str(a.get('date', '')).strip()}",
    log_input=lambda a: f"{str(a.get('destination', '')).strip()} {str(a.get('date', '')).strip()}",
    dup_message="같은 조회입니다.",
    run=_get_weather,
)

REGISTRY: dict[str, Tool] = {t.name: t for t in (SEARCH_PLACE, GET_WEATHER)}


def specs(names: list[str]) -> list[dict]:
    """모델에게 넘길 도구 설명 목록."""
    return [REGISTRY[n].schema for n in names]


@traceable(run_type="tool", name="tool")
def execute(name: str, raw_args: str | dict, ctx: ToolContext) -> dict:
    """도구 하나를 실행합니다. 중복이면 실행하지 않고 기록만 남기고, 오류면 ctx.stopped 를 켭니다."""
    tool = REGISTRY.get(name)
    if tool is None:
        ctx.log.append({"tool": name, "input": "", "status": "unknown_tool", "count": 0})
        return {"status": "error", "message": f"알 수 없는 도구입니다: {name}"}
    try:
        args = json.loads(raw_args or "{}") if isinstance(raw_args, str) else dict(raw_args)
    except ValueError:
        args = {}

    sig = tool.signature(args)
    if not sig or sig in ctx.seen:
        ctx.log.append({"tool": name, "input": tool.log_input(args), "status": "skipped(duplicate)", "count": 0})
        return {"status": "skipped", "message": tool.dup_message}
    ctx.seen.add(sig)

    payload = tool.run(args, ctx)
    # 오류가 나면 더 이상 도구를 부르지 않습니다. 같은 실패를 되풀이하지 않기 위해서입니다.
    if payload.get("status") == "error":
        ctx.stopped = True
    return payload


# ---------- 일정·추천용 조사 단계 (모델이 고르지 않고 정해진 순서로 쓰는 조사 도구) ----------
# plan_pipeline 의 함수를 '도구'로 감싸서, 추적 화면에 단계별로 나타나게 합니다.

@traceable(run_type="tool", name="research_places")
def research_places(cond: Conditions, log: list, kinds=None) -> dict:
    return collect_places(cond, log, kinds=kinds) if kinds else collect_places(cond, log)


@traceable(run_type="tool", name="research_lodging")
def research_lodging(cond: Conditions, log: list, near: list) -> dict:
    return collect_lodging(cond, log, near=near)


@traceable(run_type="tool", name="research_weather")
def research_weather(cond: Conditions, log: list) -> dict:
    return collect_weather(cond, log)
