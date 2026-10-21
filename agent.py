"""장소·날씨 질문을 처리하는 에이전트(ReAct 방식)와 질문 종류 판단.

- 장소 질문이면 장소 검색 도구, 날씨 질문이면 날씨 도구를 부르고, 도구 결과를 보고 다시 찾을지 답할지 정합니다.
- 도구 호출은 추론 없음(none)에서만 가능하므로 이 호출은 추론을 끕니다.
- 오류가 나면 같은 도구를 다시 부르지 않고 멈춥니다.
- 모든 호출은 실행 기록(도구, 인자, 상태, 결과 수)으로 남깁니다.
"""

import json
from datetime import date

import openai

from config import get_api_key, get_model_name
from kakao_places import KakaoError, search_places
from travel_data import TravelDataError, get_trip_weather

MAX_TOOL_CALLS = 4
MAX_HISTORY = 10

SEARCH_TOOL = {
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
}

WEATHER_TOOL = {
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
}


def _lookup_system(today: date) -> str:
    return (
        "당신은 여행 장소와 날씨 조회 도우미입니다. "
        f"오늘은 {today.isoformat()}입니다. "
        "장소를 말하기 전에는 반드시 search_place 로 확인합니다. "
        "검색어는 '지역 + 장소 종류 단어 하나'로 짧게 씁니다(예: 경주 박물관, 경주 카페). '실내', '부모님과' 같은 수식어를 넣으면 0건이 나오기 쉽습니다. "
        "조회 결과에 없는 장소는 만들어 내지 않습니다. "
        "결과가 3곳 미만이거나 0건이면 지역은 그대로 두고 검색어를 바꿔 다시 찾습니다. 같은 검색어는 반복하지 않습니다. "
        "결과가 충분하면 조회된 장소명, 주소, 지도 링크만 안내합니다. "
        "지역이 없으면 지역부터 묻고 도구를 부르지 않습니다. "
        "날씨 질문이면 get_weather 를 씁니다. 날짜가 없으면 도구를 부르지 말고 날짜를 묻습니다. "
        "'이번 주 토요일'처럼 말하면 오늘 기준으로 YYYY-MM-DD 날짜를 계산해 넣습니다. "
        "예보 없음이면 숫자를 지어내지 말고 예보 범위 밖이라고 말합니다. "
        "도구 결과가 error 이면 같은 도구를 다시 부르지 말고, 원인을 알린 뒤 멈춥니다. 장소나 날씨를 지어내지 않습니다. "
        "장소나 날씨 질문이 아니면 도구 없이 짧게 답합니다."
    )


ROUTE_SCHEMA = {
    "type": "object",
    "properties": {"route": {"type": "string", "enum": ["장소조회", "날씨", "일정", "대화"]}},
    "required": ["route"],
    "additionalProperties": False,
}

ROUTE_SYSTEM = (
    "질문을 네 가지 중 하나로 나눈다. 특정 지역이나 장소의 위치, 주소, 이름을 찾는 질문은 장소조회. "
    "날씨, 기온, 비 오는지 묻는 질문은 날씨. "
    "여행 일정이나 코스를 짜달라는 질문은 일정. 인사나 그 밖의 말은 대화."
)


def route_question(text: str) -> str:
    """질문 종류를 장소조회, 날씨, 일정, 대화 중 하나로 돌려줍니다. 실패하면 대화로 봅니다."""
    key = get_api_key()
    if not key or not text.strip():
        return "대화"
    try:
        client = openai.OpenAI(api_key=key, timeout=30)
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


def _run_search(query: str, log: list[dict]) -> dict:
    """장소 검색 도구 실행. 결과를 모델에게 줄 값으로 돌려주고, 실행 기록에 남깁니다."""
    try:
        places = search_places(query, size=5)
        payload = {
            "status": "ok",
            "count": len(places),
            "places": [{"name": p["name"], "address": p["address"], "link": p["link"]} for p in places],
        }
    except KakaoError as e:
        payload = {"status": "error", "count": 0, "message": str(e), "places": []}
    log.append({"tool": "search_place", "input": query, "status": payload["status"], "count": payload["count"]})
    return payload


def _run_weather(destination: str, date_text: str, labels: dict, log: list[dict]) -> dict:
    """날씨 도구 실행. 예보 범위 밖이면 예보 없음으로 돌려주고, 다른 날짜로 채우지 않습니다."""
    try:
        day = date.fromisoformat(date_text)
    except ValueError:
        log.append({"tool": "get_weather", "input": f"{destination} {date_text}", "status": "bad_date", "count": 0})
        return {"status": "bad_date", "message": "날짜 형식이 YYYY-MM-DD 가 아닙니다."}

    try:
        w = get_trip_weather(destination, day, 1)
    except TravelDataError as e:
        log.append({"tool": "get_weather", "input": f"{destination} {date_text}", "status": "error", "count": 0})
        return {"status": "error", "message": str(e)}

    log.append({"tool": "get_weather", "input": f"{destination} {date_text}", "status": w["status"], "count": len(w["days"])})
    if w["status"] != "ok":
        return {"status": "out_of_range", "message": "예보 범위 밖이라 날씨를 알 수 없습니다."}
    d = w["days"][0]
    return {
        "status": "ok",
        "date": d["date"].isoformat(),
        "weather": labels.get(d.get("code"), "정보 없음"),
        "tmax": round(d["tmax"]),
        "tmin": round(d["tmin"]),
        "rain_mm": round(d["rain_mm"], 1),
    }


def run_lookup(question: str, history: list[dict] | None, labels: dict | None = None) -> dict:
    """장소·날씨 질문을 에이전트로 처리합니다. 반환: {"answer": str, "log": [...]}"""
    key = get_api_key()
    if not key:
        return {"answer": "OpenAI 키가 설정되지 않아 조회하지 못했습니다.", "log": []}

    labels = labels or {}
    client = openai.OpenAI(api_key=key, timeout=90)
    messages = [{"role": "system", "content": _lookup_system(date.today())}]
    for item in (history or [])[-MAX_HISTORY:]:
        messages.append({"role": item["role"], "content": item["content"]})
    messages.append({"role": "user", "content": question})

    log: list[dict] = []
    seen: set[str] = set()
    calls = 0
    stopped = False
    while True:
        tools = [SEARCH_TOOL, WEATHER_TOOL] if (calls < MAX_TOOL_CALLS and not stopped) else None
        kwargs = {"tools": tools} if tools else {}
        res = client.chat.completions.create(
            model=get_model_name(),
            messages=messages,
            reasoning_effort="none",
            max_completion_tokens=1200,
            **kwargs,
        )
        msg = res.choices[0].message
        if not msg.tool_calls:
            return {"answer": (msg.content or "").strip(), "log": log}

        messages.append({"role": "assistant", "content": msg.content, "tool_calls": [t.model_dump() for t in msg.tool_calls]})
        for t in msg.tool_calls:
            args = json.loads(t.function.arguments or "{}")
            calls += 1
            if t.function.name == "get_weather":
                destination = str(args.get("destination", "")).strip()
                date_text = str(args.get("date", "")).strip()
                sig = f"get_weather:{destination}:{date_text}"
                if sig in seen:
                    log.append({"tool": "get_weather", "input": f"{destination} {date_text}", "status": "skipped(duplicate)", "count": 0})
                    payload = {"status": "skipped", "message": "같은 조회입니다."}
                else:
                    seen.add(sig)
                    payload = _run_weather(destination, date_text, labels, log)
            else:
                query = str(args.get("query", "")).strip()
                sig = f"search_place:{query}"
                if not query or sig in seen:
                    # 같은 검색어를 다시 부르면 실행하지 않고 기록만 남깁니다.
                    log.append({"tool": "search_place", "input": query, "status": "skipped(duplicate)", "count": 0})
                    payload = {"status": "skipped", "message": "같은 검색어입니다. 다른 검색어를 쓰세요."}
                else:
                    seen.add(sig)
                    payload = _run_search(query, log)

            # 오류가 나면 더 이상 도구를 부르지 않습니다. 같은 실패를 되풀이하지 않기 위해서입니다.
            if payload.get("status") == "error":
                stopped = True
            messages.append({"role": "tool", "tool_call_id": t.id, "content": json.dumps(payload, ensure_ascii=False)})
        if stopped:
            log.append({"tool": "stop", "input": "", "status": "error 이후 도구 호출 중단", "count": 0})
