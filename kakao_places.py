"""카카오 로컬 API 로 장소를 검증합니다. 키는 .env 의 KAKAO_REST_API_KEY 를 씁니다.

- search_place(): 키워드로 장소를 찾습니다. 음식점은 category 를 'FD6' 로 좁힙니다.
- distance_m(): 두 좌표 사이 직선거리(m). 실제 이동 시간이 아니라 동선 점검용입니다.
- 키가 없거나 틀리면 KakaoError 를 던지고, 화면에는 고정 문구만 보여 줍니다.
"""

import math
import re
from concurrent.futures import ThreadPoolExecutor

import requests

from chatbot import ChatbotError, complete_json
from config import REASONING, get_kakao_key

SEARCH_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
WEB_SEARCH_URL = "https://dapi.kakao.com/v2/search/web"
TIMEOUT = 10
VERIFY_WORKERS = 6  # 동시에 보낼 카카오 요청 수. 너무 크면 카카오 호출 제한에 걸릴 수 있습니다.
CATEGORY_RESTAURANT = "FD6"

MSG_NO_KEY = "카카오 키가 설정되지 않아 장소를 검증하지 못했습니다. .env 의 KAKAO_REST_API_KEY 를 확인하세요."
MSG_AUTH = "카카오 키가 올바르지 않습니다. 카카오 개발자 콘솔의 REST API 키를 .env 에 다시 넣어 주세요."
MSG_FORBIDDEN = (
    "이 카카오 앱에 장소 검색 권한이 없습니다. 카카오 개발자 콘솔에서 해당 앱의 '카카오맵' 사용을 켜 주세요."
)
MSG_NET = "카카오 서버에 연결하지 못해 장소를 검증하지 못했습니다."


class KakaoError(Exception):
    """화면에 그대로 보여줘도 안전한 고정 문구만 담는 오류."""


def _to_place(doc: dict, query: str) -> dict:
    return {
        "name": doc.get("place_name", query),
        "address": doc.get("road_address_name") or doc.get("address_name", ""),
        "lat": float(doc["y"]),
        "lon": float(doc["x"]),
        "category": doc.get("category_name", ""),
        "link": doc.get("place_url", ""),
    }


def search_places(query: str, size: int = 5, category: str | None = None) -> list[dict]:
    """키워드로 장소 여러 개를 찾습니다. 각 항목은 name, address, lat, lon, category, link 를 가집니다."""
    key = get_kakao_key()
    if not key:
        raise KakaoError(MSG_NO_KEY)

    params = {"query": query, "size": size}
    if category:
        params["category_group_code"] = category
    try:
        res = requests.get(
            SEARCH_URL,
            params=params,
            headers={"Authorization": f"KakaoAK {key}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        raise KakaoError(MSG_NET) from None

    if res.status_code == 401:
        raise KakaoError(MSG_AUTH)
    if res.status_code == 403:
        raise KakaoError(MSG_FORBIDDEN)
    if res.status_code != 200:
        raise KakaoError(MSG_NET)

    return [_to_place(doc, query) for doc in res.json().get("documents", [])]


def search_place(query: str, category: str | None = None) -> dict | None:
    """장소 하나를 찾아 {"name", "address", "lat", "lon", "category", "link"} 를 돌려줍니다. 없으면 None."""
    found = search_places(query, size=1, category=category)
    return found[0] if found else None


EXTRACT_PROMPT = (
    "당신은 여행 일정 글에서 장소를 뽑는 도우미입니다. 아래 일정 글에 나온 장소를 JSON 객체 하나로만 답하세요. "
    "설명 문장이나 코드 펜스는 붙이지 마세요. 형식: "
    '{"places": [{"day": 1, "slot": "오전", "kind": "관광지", "query": "지역 이름을 포함한 검색어"}]} '
    "kind 는 관광지, 식당, 숙소 중 하나입니다. slot 은 오전, 점심, 오후, 저녁, 숙박 중 하나이고 모르면 빈 문자열입니다. "
    "식당과 숙소에는 실제 상호명만 넣고, '점심 식당'처럼 이름이 없는 항목은 빼세요. "
    "날짜를 알 수 없으면 day 는 null 로 씁니다."
)


def extract_places(answer: str) -> list[dict]:
    """답변 글에서 장소 목록을 뽑습니다. 실패하면 ChatbotError."""
    data = complete_json(EXTRACT_PROMPT, answer, effort=REASONING["extract"])
    items = data.get("places") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ChatbotError("장소 목록을 읽지 못했습니다.")
    cleaned = []
    for item in items:
        if not isinstance(item, dict) or not item.get("query"):
            continue
        cleaned.append(
            {
                "day": item.get("day"),
                "slot": str(item.get("slot") or "").strip(),
                "kind": item.get("kind") if item.get("kind") in ("관광지", "식당", "숙소") else "관광지",
                "query": str(item["query"]).strip(),
            }
        )
    return cleaned


# 종류별로 카카오 카테고리 그룹을 제한합니다. 도로 이름을 검색하면 은행 같은 엉뚱한 곳이 걸리는 것을 막습니다.
# AT4: 관광명소, CT1: 문화시설, FD6: 음식점, AD5: 숙박
CATEGORIES_BY_KIND = {
    "관광지": ["AT4", "CT1"],
    "식당": [CATEGORY_RESTAURANT, "CE7"],  # FD6: 음식점, CE7: 카페
    "숙소": ["AD5"],
}

# 관광지를 카테고리 없이 찾았을 때 걸러낼 분류(은행, 병원 등 관광과 무관한 곳)
BLOCKED_TOURIST_PREFIXES = ("금융,보험", "음식점", "의료", "교육,학문", "부동산", "공공기관", "생활,편의")


def _is_tourist_like(found: dict) -> bool:
    return not found["category"].startswith(BLOCKED_TOURIST_PREFIXES)


def search_web(query: str) -> dict | None:
    """카카오맵에 없을 때 웹 문서에서 한 번 더 찾습니다. 제목이나 요약에 장소 이름이 있으면 확인된 것으로 봅니다."""
    key = get_kakao_key()
    if not key:
        return None
    try:
        res = requests.get(
            WEB_SEARCH_URL,
            params={"query": query, "size": 3},
            headers={"Authorization": f"KakaoAK {key}"},
            timeout=TIMEOUT,
        )
    except requests.RequestException:
        return None
    if res.status_code != 200:
        return None
    # 지역 이름을 뺀 마지막 단어(예: '아우내장터')가 제목이나 요약에 있어야 같은 곳으로 봅니다.
    name = query.split()[-1].replace(" ", "")
    for doc in res.json().get("documents", []):
        # 검색 결과에는 <b> 태그가 섞여 있고 띄어쓰기도 다를 수 있어서, 태그와 띄어쓰기를 지우고 비교합니다.
        raw = f"{doc.get('title', '')} {doc.get('contents', '')}"
        text = re.sub(r"<[^>]+>", "", raw).replace(" ", "")
        if name in text:
            return {
                "name": query,
                "url": doc.get("url", ""),
                "title": re.sub(r"<[^>]+>", "", doc.get("title", "")),
            }
    return None


def verify_places(items: list[dict]) -> list[dict]:
    """각 장소를 찾습니다. 순서는 카카오맵 종류별 카테고리 → (관광지만) 카테고리 없이 → 웹 검색 순입니다.

    엉뚱한 곳(은행 등)은 관광지로 채택하지 않습니다. KakaoError 는 그대로 던집니다.
    """
    # 장소마다 독립적이라 동시에 찾습니다. 결과는 입력 순서대로 돌려줍니다.
    with ThreadPoolExecutor(max_workers=VERIFY_WORKERS) as pool:
        futures = [pool.submit(_verify_one, item) for item in items]
        return [f.result() for f in futures]


def _verify_one(item: dict) -> dict:
    found = None
    source = None
    for category in CATEGORIES_BY_KIND.get(item["kind"], [None]):
        found = search_place(item["query"], category=category)
        if found:
            source = "kakao"
            break
    if not found and item["kind"] == "관광지":
        candidate = search_place(item["query"])
        if candidate and _is_tourist_like(candidate):
            found, source = candidate, "kakao"
    if not found:
        web = search_web(item["query"])
        if web:
            found, source = web, "web"
    return {**item, "found": found, "source": source}


def day_distances(results: list[dict]) -> list[dict]:
    """같은 날의 관광지끼리 이어지는 직선거리를 계산합니다. 동선 점검용입니다."""
    out = []
    by_day: dict = {}
    for r in results:
        # 좌표가 있는 카카오맵 결과만 거리를 잽니다. 웹에서만 확인된 곳은 좌표가 없습니다.
        if r["kind"] == "관광지" and r["found"] is not None and r.get("source") == "kakao":
            by_day.setdefault(r.get("day"), []).append(r)
    for day, places in by_day.items():
        for a, b in zip(places, places[1:]):
            out.append(
                {
                    "day": day,
                    "from": a["found"]["name"],
                    "to": b["found"]["name"],
                    "meters": round(distance_m(a["found"], b["found"])),
                }
            )
    return out


def distance_m(a: dict, b: dict) -> float:
    """두 장소의 직선거리(m). 하버사인 공식을 씁니다."""
    r = 6371000
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp = p2 - p1
    dl = math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
