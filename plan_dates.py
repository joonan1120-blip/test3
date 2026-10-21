"""대화 내용에서 여행 정보(시작일, 여행지, 박 수)를 찾습니다.

'내일', '모레', '다음 주 월요일' 같은 말도 오늘 기준으로 계산합니다.
추론 없이(none) 짧은 JSON 하나만 받습니다. 실패하면 빈 값을 돌려줍니다.
"""

import json
from dataclasses import dataclass
from datetime import date

import openai

from config import get_api_key, get_model_name

SCHEMA = {
    "type": "object",
    "properties": {
        "start_date": {"type": ["string", "null"]},
        "destination": {"type": ["string", "null"]},
        "nights": {"type": ["integer", "null"]},
    },
    "required": ["start_date", "destination", "nights"],
    "additionalProperties": False,
}


@dataclass
class TripInfo:
    start_date: date | None = None
    destination: str | None = None
    nights: int | None = None

    @property
    def days(self) -> int | None:
        # N박이면 N+1일. 박 수를 말하지 않았으면 None 입니다. 추측하지 않고 모델이 되묻게 합니다.
        return self.nights + 1 if self.nights else None


def extract_trip(user_text: str, today: date) -> TripInfo:
    key = get_api_key()
    if not key or not user_text.strip():
        return TripInfo()
    system = (
        f"오늘은 {today.isoformat()} 이다. 사용자의 말에서 세 가지를 찾는다. "
        "1) 여행 시작일을 YYYY-MM-DD 로. '내일', '모레', '다음 주 월요일' 같은 말은 오늘 기준으로 계산한다. "
        "2) 여행지 이름 하나(시·도나 도시 이름). 여러 번 나오면 가장 마지막 말을 따른다. "
        "3) 박 수(예: 2박이면 2). 없으면 null 로 답한다."
    )
    try:
        client = openai.OpenAI(api_key=key, timeout=30)
        res = client.chat.completions.create(
            model=get_model_name(),
            reasoning_effort="none",
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_text}],
            response_format={"type": "json_schema", "json_schema": {"name": "trip", "schema": SCHEMA, "strict": True}},
            max_completion_tokens=120,
        )
        data = json.loads(res.choices[0].message.content)
        start = data.get("start_date")
        nights = data.get("nights")
        return TripInfo(
            start_date=date.fromisoformat(start) if start else None,
            destination=(data.get("destination") or None),
            nights=int(nights) if nights else None,
        )
    except (openai.OpenAIError, ValueError, KeyError, TypeError):
        return TripInfo()
