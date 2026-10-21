"""앱 쪽 캘린더 연결: MCP 클라이언트, 미리보기 검사, 확인(내용 서명 + 한 번 쓰는 표), 등록과 재조회.

- 앱(호스트) → MCP 클라이언트 → calendar_server.py(stdio 자식 프로세스) → Google Calendar API 순서로 부릅니다.
- 확인과 결과 대조는 모델의 문장이 아니라 이 파일의 코드가 지킵니다.
- 이벤트 ID 는 일정 내용으로 정해서, 같은 일정을 다시 등록해도 중복으로 생기지 않습니다.
"""

import asyncio
import base64
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

SERVER = Path(__file__).resolve().parent / "calendar_server.py"
# 캘린더 설정(.env)을 앱이 직접 읽습니다. 자식 프로세스(MCP 서버)도 같은 값을 씁니다.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
DEFAULT_TZ = "Asia/Seoul"

# 일정 시간대(오전, 점심 ...)를 캘린더 시각으로 바꾸는 기본 표
SLOT_TIMES = {
    "오전": ("10:00", "11:30"),
    "점심": ("12:00", "13:00"),
    "오후": ("14:00", "16:00"),
    "저녁": ("18:00", "19:30"),
}

READY_LABELS = {
    "no_calendar_id": "캘린더 ID 없음",
    "no_credentials": "인증 정보 없음",
    "auth_expired": "인증 만료",
    "forbidden": "권한 없음",
    "connection_failed": "연결 실패",
}


class CalendarConnectionError(Exception):
    """MCP 서버를 실행하거나 연결하지 못했을 때."""


class ApprovalError(Exception):
    """확인(승인)이 없거나, 이미 쓰였거나, 확인 뒤 내용이 바뀌었을 때."""


# ---------------- MCP 호출 ----------------

async def _call(tool: str, args: dict):
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=dict(os.environ))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if tool == "__list_tools__":
                listed = await session.list_tools()
                return [t.name for t in listed.tools]
            res = await session.call_tool(tool, args)
            if res.isError:
                raise CalendarConnectionError("도구 실행 오류")
            data = res.structuredContent
            if data is None and res.content:
                data = json.loads(res.content[0].text)
            if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], dict):
                data = data["result"]
            return data


def call_tool(tool: str, args: dict | None = None):
    """MCP 서버를 자식 프로세스로 띄워 도구 하나를 부릅니다. 서버 실행 실패는 CalendarConnectionError."""
    try:
        return asyncio.run(_call(tool, args or {}))
    except CalendarConnectionError:
        raise
    except Exception:
        raise CalendarConnectionError("MCP 서버에 연결하지 못했습니다.") from None


# ---------------- 연결·준비 상태 ----------------

def check_connection() -> dict:
    """도구 연결 확인: MCP 서버를 실행해 도구 목록을 조회합니다. Google 인증 성공과는 다릅니다."""
    try:
        tools = call_tool("__list_tools__")
        return {"connected": True, "tools": tools}
    except CalendarConnectionError:
        return {"connected": False, "tools": []}


def check_ready() -> dict:
    """캘린더 준비 확인: ID → 인증 정보 → 읽기 전용 조회 순. 일정은 만들지 않습니다."""
    now = datetime.now(timezone.utc)
    try:
        res = call_tool(
            "list_events",
            {
                "time_min": now.isoformat(timespec="seconds"),
                "time_max": (now + timedelta(days=7)).isoformat(timespec="seconds"),
                "max_results": 5,
            },
        )
    except CalendarConnectionError:
        return {"ready": False, "label": "연결 실패(MCP)", "checks": {}}
    if res.get("status") == "ok":
        fake = os.getenv("CALENDAR_BACKEND", "google").strip() == "fake"
        return {
            "ready": True,
            "fake": fake,
            "label": "준비됨 — 시험용 가상 캘린더(Google 아님)" if fake else "준비됨 — Google Calendar 읽기 전용 조회 성공",
            "checks": {"캘린더 ID 있음": True, "인증 정보 있음": True, "읽기 조회 성공": True},
        }
    kind = res.get("error_kind", "connection_failed")
    return {"ready": False, "label": READY_LABELS.get(kind, "연결 실패"), "checks": {}, "message": res.get("message", "")}


def mask_calendar_id() -> str:
    """대상 캘린더 ID 를 일부만 보여 줍니다."""
    cid = os.getenv("CALENDAR_ID", "").strip()
    if not cid:
        return "(설정 안 됨)"
    if len(cid) <= 10:
        return cid[:2] + "…"
    return cid[:4] + "…" + cid[-10:]


# ---------------- 미리보기 ----------------

def default_rows(results: list[dict], start: date) -> list[dict]:
    """검증된 일정 장소를 캘린더 일정 행(제목, 날짜, 시작/끝, 시간대, 장소)으로 바꿉니다."""
    rows = []
    for r in results:
        if r.get("kind") == "숙소" or not r.get("day") or r.get("slot") not in SLOT_TIMES:
            continue
        found = r.get("found") or {}
        s, e = SLOT_TIMES[r["slot"]]
        rows.append(
            {
                "title": found.get("name") or r.get("query", ""),
                "date": (start + timedelta(days=r["day"] - 1)).isoformat(),
                "start": s,
                "end": e,
                "timezone": DEFAULT_TZ,
                "location": found.get("address", "") if r.get("source") == "kakao" else "",
            }
        )
    return rows


def validate_row(row: dict) -> list[str]:
    """행 하나를 검사해 경고 문구 목록을 돌려줍니다. 비어 있으면 문제 없음."""
    warnings = []
    for key, label in (("title", "제목"), ("date", "날짜"), ("start", "시작"), ("end", "끝"), ("timezone", "시간대")):
        if not str(row.get(key, "")).strip():
            warnings.append(f"{label} 누락")
    if warnings:
        return warnings
    try:
        ZoneInfo(row["timezone"])
    except Exception:
        warnings.append("알 수 없는 시간대")
    try:
        start = datetime.fromisoformat(f"{row['date']}T{row['start']}")
        end = datetime.fromisoformat(f"{row['date']}T{row['end']}")
        if end <= start:
            warnings.append("끝이 시작보다 늦어야 함")
    except ValueError:
        warnings.append("날짜 또는 시각 형식 오류")
    return warnings


def rows_signature(rows: list[dict]) -> str:
    """미리보기 내용의 서명. 확인한 내용과 지금 내용이 같은지 대조하는 데 씁니다."""
    normalized = [
        {k: str(row.get(k, "")).strip() for k in ("title", "date", "start", "end", "timezone", "location")}
        for row in rows
    ]
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def make_event_id(row: dict) -> str:
    """일정 내용으로 이벤트 ID 를 만듭니다. 같은 내용이면 항상 같은 ID 라서 중복 생성이 막힙니다."""
    raw = "|".join(str(row.get(k, "")).strip() for k in ("title", "date", "start", "end", "timezone", "location"))
    digest = hashlib.sha1(raw.encode("utf-8")).digest()
    return "ramos" + base64.b32hexencode(digest).decode("ascii").lower().rstrip("=")


# ---------------- 확인(승인) ----------------

@dataclass
class Approval:
    """'이 내용으로 확인'의 결과. 내용 서명과 한 번만 쓸 수 있는 표로 이루어집니다."""

    signature: str
    used: bool = False

    def consume(self, current_signature: str) -> None:
        if self.used:
            raise ApprovalError("한 번 쓰는 확인이 이미 쓰였습니다. 다시 확인해 주세요.")
        if current_signature != self.signature:
            raise ApprovalError("확인한 뒤 내용이 바뀌었습니다. 다시 확인해 주세요.")
        self.used = True


# ---------------- 등록과 재조회 ----------------

def _row_to_event(row: dict) -> dict:
    return {
        "title": row["title"].strip(),
        "start": f"{row['date']}T{row['start']}",
        "end": f"{row['date']}T{row['end']}",
        "timezone": row["timezone"].strip(),
        "location": str(row.get("location", "")).strip(),
    }


def _compare(row: dict, event: dict) -> dict:
    want = _row_to_event(row)
    return {k: want[k] == str(event.get(k, "")).strip() for k in ("title", "start", "end", "timezone", "location")}


def _reread(event_id: str, row: dict) -> dict:
    """이벤트 ID 로 다시 조회해 5개 항목(제목, 시작, 끝, 시간대, 장소)을 대조합니다."""
    try:
        res = call_tool("get_event", {"event_id": event_id})
    except CalendarConnectionError:
        return {"state": "unconfirmed"}
    if res.get("status") == "found":
        checks = _compare(row, res["event"])
        return {"state": "found", "checks": checks, "match": all(checks.values()), "link": res["event"].get("html_link", "")}
    if res.get("status") == "not_found":
        return {"state": "not_found"}
    return {"state": "unconfirmed", "error_kind": res.get("error_kind")}


def register(rows: list[dict], approval: Approval) -> list[dict]:
    """확인한 일정만 MCP 로 등록하고, 등록마다 다시 조회해 대조합니다.

    확인(approval)은 여기서 먼저 소비합니다. 내용이 바뀌었거나 이미 쓰였으면 ApprovalError 로 막습니다.
    """
    approval.consume(rows_signature(rows))
    results = []
    for row in rows:
        event_id = make_event_id(row)
        ev = _row_to_event(row)
        try:
            res = call_tool("create_event", {"event_id": event_id, **ev})
        except CalendarConnectionError:
            res = {"status": "error", "error_kind": "connection_failed"}

        status, kind = res.get("status"), res.get("error_kind")
        out = {"row": row, "event_id": event_id}
        if status in ("created", "already_exists"):
            re = _reread(event_id, row)
            if re["state"] == "found":
                label = "created" if status == "created" else "already_exists"
                out.update(outcome=f"{label}_{'match' if re['match'] else 'mismatch'}", checks=re["checks"], link=re.get("link", ""))
            elif re["state"] == "not_found":
                out.update(outcome="not_registered")
            else:
                out.update(outcome="unconfirmed")
        elif kind == "auth_expired":
            out.update(outcome="failed", message="등록 실패: 다시 인증")
        elif kind == "connection_failed":
            # 응답이 유실됐을 수 있습니다. 같은 이벤트 ID 로 다시 조회해서 판단합니다.
            re = _reread(event_id, row)
            if re["state"] == "found":
                out.update(outcome="exists_no_recreate", checks=re["checks"], link=re.get("link", ""))
            elif re["state"] == "not_found":
                out.update(outcome="not_registered")
            else:
                out.update(outcome="unconfirmed")
        else:
            out.update(outcome="failed", message=res.get("message", "등록하지 못했습니다."))
        results.append(out)
    return results


def requery(results: list[dict]) -> list[dict]:
    """결과 미확정인 항목을 같은 이벤트 ID 로 다시 조회합니다. 새로 등록하지 않습니다."""
    updated = []
    for out in results:
        if out["outcome"] != "unconfirmed":
            updated.append(out)
            continue
        re = _reread(out["event_id"], out["row"])
        if re["state"] == "found":
            updated.append({**out, "outcome": "exists_no_recreate", "checks": re["checks"], "link": re.get("link", "")})
        elif re["state"] == "not_found":
            updated.append({**out, "outcome": "not_registered"})
        else:
            updated.append(out)
    return updated


OUTCOME_TEXT = {
    "created_match": "새로 등록 · 재조회 일치",
    "already_exists_match": "이미 있음(중복 생성 안 함) · 재조회 일치",
    "created_mismatch": "등록됨 · 재조회 내용이 다름",
    "already_exists_mismatch": "이미 있음 · 재조회 내용이 다름",
    "exists_no_recreate": "일정 있음(다시 만들지 않음)",
    "not_registered": "등록되지 않음 확인 — 미리보기를 다시 확인한 뒤 등록하세요",
    "unconfirmed": "결과 미확정 — 같은 이벤트 ID 로 다시 조회하세요",
    "failed": "등록 실패",
}
