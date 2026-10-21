"""여행 계획 파이프라인: 장소(A)와 날씨(B)를 따로 조회하고, 같은 조건인지 검사한 뒤 계획을 씁니다.

- A 장소 조사: 여행지 + 장소 종류(관광지, 맛집, 카페)로 카카오 검색. 여행지 주소에 없는 곳은 뺍니다.
- B 날씨 조사: 여행지 + 여행 날짜로 Open-Meteo 예보 조회. 예보 범위 밖이면 날씨를 채우지 않고 '예보 없음'으로 둡니다.
- 두 결과의 원본과 실행 기록은 화면에 함께 보여 줍니다.
"""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta

from kakao_places import KakaoError, distance_m, search_places
from travel_data import TravelDataError, get_trip_weather

PLACE_KINDS = ["관광지", "맛집", "카페"]
# 추천만 할 때는 후보를 넓혀서 더 다양한 곳을 보여 줍니다.
WIDE_KINDS = ["관광지", "맛집", "카페", "공원", "시장", "박물관", "전망대", "해변"]


@dataclass
class Conditions:
    destination: str | None
    start: date | None
    days: int | None

    @property
    def ready(self) -> bool:
        return bool(self.destination and self.start and self.days)


def collect_places(cond: Conditions, log: list[dict], kinds: list[str] | None = None) -> dict:
    """A 장소 조사. 여행지 주소에 없는 장소는 근거에서 뺍니다. kinds 로 검색할 장소 종류를 정합니다."""
    queries = [f"{cond.destination} {kind}" for kind in (kinds or PLACE_KINDS)]

    def one(query: str):
        try:
            return query, search_places(query, size=5), None
        except KakaoError as e:
            return query, [], str(e)

    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        outcomes = list(pool.map(one, queries))

    places, seen, errors = [], set(), []
    for query, found, err in outcomes:
        log.append({"tool": "search_place", "input": query, "status": "error" if err else "ok", "count": len(found)})
        if err:
            errors.append(err)
            continue
        for p in found:
            if p["name"] in seen:
                continue
            if cond.destination not in p["address"]:
                log.append({"tool": "region_check", "input": p["name"], "status": "removed", "count": 1})
                continue
            seen.add(p["name"])
            places.append(p)

    if places:
        status, message = "ok", ""
    elif errors and len(errors) == len(queries):
        status, message = "error", errors[0]
    else:
        status, message = "empty", ""
    return {"status": status, "places": places, "message": message}


LODGING_QUERIES = ["호텔", "게스트하우스", "한옥 숙소"]


def collect_lodging(cond: Conditions, log: list[dict], near: list[dict] | None = None) -> dict:
    """숙소 조사. 카카오 숙박 카테고리(AD5)에서 찾고, 여행지 주소에 없는 곳은 뺍니다.

    near 에 방문지 목록을 주면, 방문지들의 중심에서 가까운 순으로 정렬합니다(동선 기준).
    """
    queries = [f"{cond.destination} {kind}" for kind in LODGING_QUERIES]

    def one(query: str):
        try:
            return query, search_places(query, size=5, category="AD5"), None
        except KakaoError as e:
            return query, [], str(e)

    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        outcomes = list(pool.map(one, queries))

    found, seen, errors = [], set(), []
    for query, places, err in outcomes:
        log.append({"tool": "search_lodging", "input": query, "status": "error" if err else "ok", "count": len(places)})
        if err:
            errors.append(err)
            continue
        for p in places:
            if p["name"] in seen or cond.destination not in p["address"]:
                continue
            seen.add(p["name"])
            found.append(p)

    if near:
        cx = sum(p["lat"] for p in near) / len(near)
        cy = sum(p["lon"] for p in near) / len(near)
        center = {"lat": cx, "lon": cy}
        found.sort(key=lambda p: distance_m(p, center))

    if found:
        return {"status": "ok", "places": found, "message": ""}
    if errors and len(errors) == len(queries):
        return {"status": "error", "places": [], "message": errors[0]}
    return {"status": "empty", "places": [], "message": ""}


def collect_weather(cond: Conditions, log: list[dict]) -> dict:
    """B 날씨 조사. 날짜가 맞지 않으면 근거로 쓰지 않습니다."""
    if not cond.ready:
        return {"status": "missing", "days": [], "message": ""}
    end = cond.start + timedelta(days=cond.days - 1)
    try:
        w = get_trip_weather(cond.destination, cond.start, cond.days)
    except TravelDataError as e:
        log.append({"tool": "weather", "input": f"{cond.destination} {cond.start}~{end}", "status": "error", "count": 0})
        return {"status": "error", "days": [], "message": str(e)}

    log.append({"tool": "weather", "input": f"{cond.destination} {cond.start}~{end}", "status": w["status"], "count": len(w["days"])})
    if w["status"] != "ok":
        return {"status": w["status"], "days": [], "message": ""}

    expected = [cond.start + timedelta(days=i) for i in range(cond.days)]
    got = [d["date"] for d in w["days"]]
    if got != expected:
        log.append({"tool": "date_check", "input": f"{cond.destination}", "status": "mismatch", "count": len(got)})
        return {"status": "mismatch", "days": [], "message": ""}
    return {"status": "ok", "days": w["days"], "message": ""}


def build_context(cond: Conditions, places: dict, weather: dict, labels: dict, lodging: dict | None = None) -> str:
    """모델에게 줄 조회 사실 블록. 장소와 날씨를 구분해서 적고, 작성 규칙을 함께 씁니다."""
    lines = ["[조회 사실 · 장소]"]
    if places["status"] == "ok":
        for p in places["places"]:
            lines.append(f"- {p['name']} | {p['address']} | {p['link']}")
    elif places["status"] == "error":
        lines.append(f"- 장소 조회 실패: {places['message']} (장소 일정을 만들지 말고 실패를 알립니다)")
    else:
        lines.append(
            "- 조회된 장소 없음 (장소를 지어내지 않습니다. 사용자에게 장소 목록을 보내 달라고 하지 않습니다. "
            "이 앱은 국내 장소만 조회하므로, 해외이거나 조회가 안 된 경우에는 그렇게 알리고 일반적인 동선 가이드만 짧게 제안합니다)"
        )

    if lodging is not None:
        lines.append("[조회 사실 · 숙소] (방문지 중심에서 가까운 순)")
        if lodging["status"] == "ok":
            for p in lodging["places"][:8]:
                lines.append(f"- {p['name']} | {p['address']} | {p['link']}")
        elif lodging["status"] == "error":
            lines.append(f"- 숙소 조회 실패: {lodging['message']} (숙소 이름을 지어내지 않습니다)")
        else:
            lines.append("- 조회된 숙소 없음 (숙소 이름을 지어내지 않습니다)")

    lines.append("[조회 사실 · 날씨]")
    if weather["status"] == "ok":
        for i, d in enumerate(weather["days"], 1):
            label = labels.get(d.get("code"), "정보 없음")
            lines.append(
                f"- {i}일차 {d['date'].month}/{d['date'].day}: {label}, "
                f"최고 {d['tmax']:.0f}도 최저 {d['tmin']:.0f}도, 강수 {d['rain_mm']:.1f}mm"
            )
    elif weather["status"] == "out_of_range":
        lines.append("- 예보 없음 — 확인 필요 (날씨 값을 쓰지 않습니다)")
    elif weather["status"] == "error":
        lines.append(f"- 날씨 조회 실패 — 확인 필요 ({weather['message']})")
    elif weather["status"] == "mismatch":
        lines.append("- 날씨 날짜가 요청과 달라 근거로 쓰지 않습니다 — 확인 필요")
    else:
        lines.append("- 여행 날짜 없음 — 날씨는 생략합니다")

    lines.append(
        "[작성 규칙] 장소와 날씨는 위 조회 사실에서만 씁니다. 순서, 시간대, 준비물은 제안입니다. "
        "영업시간, 휴무일, 요금, 이동 시간은 조회하지 않았으므로 쓰지 않습니다. "
        "비 오는 날은 실내와 카페 위주로, 맑은 날은 해변과 산책 위주로 짭니다. "
        "숙소는 [조회 사실 · 숙소]에서 골라 1일차 체크인과 마지막 날 체크아웃에 실제 이름으로 씁니다. "
        "'예약할 숙소' 같은 표현은 쓰지 않습니다. 요금과 예약 가능 여부는 조회하지 않았으므로 쓰지 않습니다."
    )
    return "\n".join(lines)
