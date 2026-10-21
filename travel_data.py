"""키 없이 쓰는 공개 데이터: 환율(Frankfurter), 지명 좌표(Open-Meteo), 날씨(Open-Meteo).

- 네트워크가 안 되면 모두 TravelDataError 를 던집니다. 화면에는 고정 문구만 보여줍니다.
- 날씨 예보는 약 15일 뒤까지만 제공됩니다. 그 이후 날짜는 '작년 같은 날짜' 기록으로 대신합니다.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

TIMEOUT = 10
FX_URL = "https://api.frankfurter.app/latest"
GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# 홈 화면에 보여 줄 주요 여행지 통화 10개 (ECB 기준 환율로 조회)
MAJOR_CURRENCIES = [
    ("일본", "JPY"),
    ("미국", "USD"),
    ("유럽(EU)", "EUR"),
    ("영국", "GBP"),
    ("중국", "CNY"),
    ("홍콩", "HKD"),
    ("태국", "THB"),
    ("싱가포르", "SGD"),
    ("호주", "AUD"),
    ("필리핀", "PHP"),
]

FORECAST_LIMIT_DAYS = 15


class TravelDataError(Exception):
    """화면에 그대로 보여줘도 안전한 고정 문구만 담는 오류."""


MSG_NET = "외부 정보를 불러오지 못했습니다. 인터넷 연결을 확인하고 다시 시도하세요."
MSG_NOT_FOUND = "해당 지명을 찾지 못했습니다. 도시 이름을 다르게 입력해 보세요."


def _get_json(url: str, params: dict) -> dict:
    try:
        res = requests.get(url, params=params, timeout=TIMEOUT)
        res.raise_for_status()
        return res.json()
    except (requests.RequestException, ValueError):
        raise TravelDataError(MSG_NET) from None


def fetch_krw_rates() -> list[dict]:
    """1 외화당 원화 금액을 돌려줍니다. [{"country", "code", "krw", "date"}, ...]"""
    codes = [code for _, code in MAJOR_CURRENCIES]
    data = _get_json(FX_URL, {"from": "KRW", "to": ",".join(codes)})
    rates = data.get("rates", {})
    rows = []
    for country, code in MAJOR_CURRENCIES:
        if code not in rates or not rates[code]:
            continue
        rows.append(
            {
                "country": country,
                "code": code,
                "krw": 1 / rates[code],
                "date": data.get("date", ""),
            }
        )
    if not rows:
        raise TravelDataError(MSG_NET)
    return rows


# 지오코딩은 한글 이름을 못 찾는 경우가 있어서, 자주 쓰는 국내 여행지는 영문 표기로 바꿔 찾습니다.
GEO_ALIASES = {
    "제주": "Jejudo",
    "제주도": "Jejudo",
    "제주시": "Jeju City",
    "서귀포": "Seogwipo",
    "서울": "Seoul",
    "부산": "Busan",
    "인천": "Incheon",
    "대구": "Daegu",
    "대전": "Daejeon",
    "광주": "Gwangju",
    "울산": "Ulsan",
    "경주": "Gyeongju",
    "강릉": "Gangneung",
    "속초": "Sokcho",
    "전주": "Jeonju",
    "여수": "Yeosu",
    "통영": "Tongyeong",
}


def geocode(name: str) -> dict:
    """지명을 좌표로 바꿉니다. {"name", "country", "lat", "lon", "timezone"}"""
    query = GEO_ALIASES.get(name.strip(), name.strip())
    data = _get_json(GEO_URL, {"name": query, "count": 1, "language": "ko"})
    results = data.get("results") or []
    if not results:
        raise TravelDataError(MSG_NOT_FOUND)
    top = results[0]
    return {
        "name": name.strip(),
        "country": top.get("country", ""),
        "lat": top["latitude"],
        "lon": top["longitude"],
        "timezone": top.get("timezone", "auto"),
    }


# ---------- 국내 인기 여행지 랭킹 (축제모아 인기 여행지 페이지 본문 참고) ----------

TREND_URL = "https://chukjemoa.co.kr/trend/"
TREND_SOURCE = "출처: 축제모아 인기 여행지 랭킹 (한국관광공사 관광 빅데이터 기반)"

_RANK_PAT = re.compile(r"(?:🥇|🥈|🥉|\b\d{1,2})\s+(\S+)\s+(\S+)\s+([\d,]+)만명")
_PEAK_PAT = re.compile(r"(?:🥇|🥈|🥉|\b\d{1,2})\s+(\S+)\s+(\S+)\s+([\d.]+)배")


def _page_text(html: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", html)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text)


def _between(text: str, start: str, end: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = text.find(end, i)
    return text[i:j] if j > i else text[i : i + 6000]


def fetch_domestic_rankings() -> dict:
    """국내 방문 랭킹과 10월 성수기 랭킹을 읽습니다.

    반환: {"korean": [{"sido", "sigungu", "visitors"}], "peak": [{"sido", "sigungu", "ratio"}], "source": str}
    """
    try:
        res = requests.get(TREND_URL, timeout=TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        res.raise_for_status()
    except requests.RequestException:
        raise TravelDataError(MSG_NET) from None

    text = _page_text(res.text)
    korean_block = _between(text, "해당 지역 주민이 아닌", "외국인 방문자 수 기준")
    peak_block = _between(text, "계절을 타는 곳이 올라옵니다.", "해당 지역 주민이 아닌")

    korean = [
        {"sido": s, "sigungu": g, "visitors": v}
        for s, g, v in _RANK_PAT.findall(korean_block)
    ]
    peak = [
        {"sido": s, "sigungu": g, "ratio": r}
        for s, g, r in _PEAK_PAT.findall(peak_block)
    ]
    if not korean and not peak:
        raise TravelDataError("랭킹 정보를 읽지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
    return {"korean": korean, "peak": peak, "source": TREND_SOURCE}


def _shift_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 2월 29일 같은 날짜
        return day.replace(year=day.year + years, day=28)


def get_daily_weather(lat: float, lon: float, start: date, end: date) -> dict:
    """날짜별 최고·최저 기온과 강수량을 돌려줍니다.

    반환: {"source": "forecast" | "history", "note": str, "days": [...]}
    days 항목: {"date", "tmax", "tmin", "rain_mm"}
    """
    today = date.today()
    params = {
        "latitude": lat,
        "longitude": lon,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
        "timezone": "auto",
    }

    if end <= today + timedelta(days=FORECAST_LIMIT_DAYS):
        params.update({"start_date": start.isoformat(), "end_date": end.isoformat()})
        data = _get_json(FORECAST_URL, params)
        source = "forecast"
        note = "기상 예보입니다. 여행 날짜에 가까울수록 정확해집니다."
    else:
        # 예보 범위 밖: 작년 같은 날짜의 실제 기록을 참고치로 보여 줍니다.
        past_start = _shift_years(start, -1)
        past_end = _shift_years(end, -1)
        params.update({"start_date": past_start.isoformat(), "end_date": past_end.isoformat()})
        data = _get_json(ARCHIVE_URL, params)
        source = "history"
        note = (
            f"여행일이 예보 범위({FORECAST_LIMIT_DAYS}일) 밖이라 작년 같은 기간의 기록을 참고용으로 보여 드립니다. "
            "실제 날씨는 출발 직전 예보를 확인해 주세요."
        )

    daily = data.get("daily", {})
    times = daily.get("time", [])
    tmax = daily.get("temperature_2m_max", [])
    tmin = daily.get("temperature_2m_min", [])
    rain = daily.get("precipitation_sum", [])
    codes = daily.get("weather_code", [])

    days = []
    for i, t in enumerate(times):
        # 기록(history)은 날짜를 작년 기준으로 가져왔으므로, 화면에는 여행 날짜로 되돌려 표시합니다.
        shown = date.fromisoformat(t)
        if source == "history":
            shown = _shift_years(shown, 1)
        days.append(
            {
                "date": shown,
                "tmax": tmax[i],
                "tmin": tmin[i],
                "rain_mm": rain[i],
                "code": codes[i] if i < len(codes) else None,
            }
        )
    return {"source": source, "note": note, "days": days}


def get_trip_weather(destination: str, start: date, days: int) -> dict:
    """여행지 이름과 기간으로 예보를 가져옵니다(지오코딩 1회 + 예보 1회).

    예보 범위(15일) 밖이면 API를 부르지 않고 status 를 out_of_range 로 돌려줍니다.
    다른 기간의 기록으로 채우지 않습니다.
    반환: {"status": "ok" | "out_of_range", "destination", "days": [...]}
    """
    end = start + timedelta(days=days - 1)
    if end > date.today() + timedelta(days=FORECAST_LIMIT_DAYS):
        return {"status": "out_of_range", "destination": destination, "days": []}
    place = geocode(destination)
    w = get_daily_weather(place["lat"], place["lon"], start, end)
    return {"status": "ok", "destination": destination, "place": place, "days": w["days"]}


def get_plan_weather(points: dict, start: date) -> dict:
    """일차별 대표 좌표의 날씨를 동시에 가져옵니다.

    points: {일차: (위도, 경도)}. 날짜는 여행 시작일 + (일차 - 1) 로 정합니다.
    반환: {일차: {"date", "tmax", "tmin", "rain_mm", "code", "source"} 또는 None(실패)}
    """

    def one(item):
        day, (lat, lon) = item
        d = start + timedelta(days=day - 1)
        # 예보 범위 밖 날짜는 다른 기간의 기록으로 채우지 않습니다.
        if d > date.today() + timedelta(days=FORECAST_LIMIT_DAYS):
            return day, None
        try:
            w = get_daily_weather(lat, lon, d, d)
            return day, {**w["days"][0], "source": w["source"]}
        except TravelDataError:
            return day, None

    if not points:
        return {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(pool.map(one, points.items()))
