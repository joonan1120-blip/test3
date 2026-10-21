"""일정 저장소: 장소 검증까지 끝난 일정을 calendar_plans.json 에 저장하고 다시 불러옵니다.

- 캘린더 등록 메뉴에서 저장된 일정을 골라 열 수 있게 하기 위한 파일입니다.
- 같은 일정 답변은 같은 id 로 덮어쓰므로 화면이 다시 그려져도 중복 저장되지 않습니다.
- 파일이 깨졌거나 없으면 빈 목록으로 시작합니다. 앱이 멈추지 않도록 예외를 삼킵니다.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

import storage

STORE_PATH = Path(__file__).resolve().parent / "calendar_plans.json"
TITLE_LEN = 28


def load_plans() -> list[dict]:
    if not storage.use_files():
        return storage.session_list("_saved_plans")
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        plans = data.get("plans", [])
        return plans if isinstance(plans, list) else []
    except (OSError, ValueError, AttributeError):
        return []


def _save_all(plans: list[dict]) -> None:
    if not storage.use_files():
        import streamlit as st

        st.session_state["_saved_plans"] = plans
        return
    try:
        STORE_PATH.write_text(
            json.dumps({"plans": plans}, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        # 저장에 실패해도 화면의 미리보기는 계속 쓸 수 있어야 합니다.
        pass


def plan_id_for(answer: str) -> str:
    return hashlib.sha1(answer.encode("utf-8")).hexdigest()[:16]


def make_title(destination: str | None, days: int | None, answer: str) -> str:
    if destination:
        return f"{destination} {days}일 일정" if days else f"{destination} 일정"
    first = next((ln.strip(" #*") for ln in answer.splitlines() if ln.strip()), "여행 일정")
    return first if len(first) <= TITLE_LEN else first[:TITLE_LEN] + "…"


def save_plan(answer: str, results: list[dict], dists: list[dict], destination: str | None,
              start: str | None, days: int | None) -> str:
    """일정을 저장하고 id 를 돌려줍니다. 이미 있으면 내용을 갱신하되 목록 위치는 유지합니다."""
    plan_id = plan_id_for(answer)
    plans = load_plans()
    entry = {
        "id": plan_id,
        "title": make_title(destination, days, answer),
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "start": start,
        "answer": answer,
        "results": results,
        "dists": dists,
    }
    for i, plan in enumerate(plans):
        if plan.get("id") == plan_id:
            plans[i] = entry
            break
    else:
        plans.insert(0, entry)
    _save_all(plans)
    return plan_id


def get_plan(plan_id: str) -> dict | None:
    return next((p for p in load_plans() if p.get("id") == plan_id), None)


def delete_plan(plan_id: str) -> None:
    _save_all([p for p in load_plans() if p.get("id") != plan_id])
