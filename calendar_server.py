"""여행 캘린더 MCP 서버(stdio). 앱이 자식 프로세스로 실행해서 도구를 부릅니다.

- 도구 3개: list_events(조회), get_event(다시 조회), create_event(생성)
- 이 서버가 쓸 수 있는 캘린더는 .env 의 CALENDAR_ID 하나로 고정됩니다.
- Google Calendar API 호출은 이 서버 안에서만 합니다.
- 등록(create_event)은 CALENDAR_LOCAL_OWNER=true 일 때만 허용합니다(본인 PC에서 본인만 쓰는 설정).
- 백엔드: CALENDAR_BACKEND=google(기본) 또는 fake(시험용 가상 캘린더, 파일에 저장).
- 시험용 실패 만들기: FAKE_CALENDAR_FAIL=insert=lost_response,get=auth 처럼 씁니다(fake 에서만).
- stdout 은 MCP 통신에 쓰이므로 print 를 쓰지 않습니다. 토큰 원문도 출력하지 않습니다.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

SCOPES = ["https://www.googleapis.com/auth/calendar.events.owned"]
mcp = FastMCP("travel-calendar")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _fail_modes() -> dict[str, str]:
    modes = {}
    for part in _env("FAKE_CALENDAR_FAIL").split(","):
        if "=" in part:
            key, value = part.split("=", 1)
            modes[key.strip()] = value.strip()
    return modes


def _error(kind: str, message: str) -> dict:
    return {"status": "error", "error_kind": kind, "message": message}


def _normalize(ev: dict, tz_name: str | None = None) -> dict:
    """Google 이벤트를 앱이 쓰는 모양으로 바꿉니다. 시간은 이벤트 시간대 기준 'YYYY-MM-DDTHH:MM' 입니다."""
    start = ev.get("start", {})
    end = ev.get("end", {})
    tz = start.get("timeZone") or tz_name or "Asia/Seoul"

    def local(info: dict) -> str:
        raw = info.get("dateTime") or info.get("date") or ""
        try:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is not None:
                dt = dt.astimezone(ZoneInfo(tz))
            return dt.strftime("%Y-%m-%dT%H:%M")
        except (ValueError, KeyError):
            return raw

    return {
        "id": ev.get("id", ""),
        "title": ev.get("summary", ""),
        "start": local(start),
        "end": local(end),
        "timezone": tz,
        "location": ev.get("location", ""),
        "html_link": ev.get("htmlLink", ""),
    }


# ---------------- Google 백엔드 ----------------

def _google_service():
    """토큰 파일로 Calendar 서비스를 만듭니다. 문제가 있으면 (None, 오류 dict)를 돌려줍니다."""
    token_file = _env("GOOGLE_TOKEN_FILE")
    if not token_file or not Path(token_file).exists():
        return None, _error("no_credentials", "인증 정보(토큰 파일)가 없습니다. calendar_auth.py 로 로그인하세요.")
    try:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                Path(token_file).write_text(creds.to_json(), encoding="utf-8")
            else:
                return None, _error("auth_expired", "인증이 만료되었습니다. calendar_auth.py 로 다시 로그인하세요.")
        return build("calendar", "v3", credentials=creds, cache_discovery=False), None
    except RefreshError:
        return None, _error("auth_expired", "인증이 만료되었거나 동의가 취소되었습니다. 다시 로그인하세요.")
    except (ValueError, OSError, KeyError):
        return None, _error("no_credentials", "토큰 파일을 읽지 못했습니다. calendar_auth.py 로 다시 로그인하세요.")


def _http_error(exc) -> dict:
    status = getattr(getattr(exc, "resp", None), "status", 0)
    if status in (401,):
        return _error("auth_expired", "인증이 만료되었습니다. 다시 로그인하세요.")
    if status in (403, 404):
        return _error("forbidden", "캘린더를 찾을 수 없거나 권한이 없습니다. 캘린더 ID와 로그인 계정을 확인하세요.")
    return _error("connection_failed", "캘린더 서버에 연결하지 못했습니다.")


# ---------------- 가상(시험용) 백엔드 ----------------

def _fake_path() -> Path:
    return Path(_env("FAKE_CALENDAR_FILE") or str(Path(tempfile.gettempdir()) / "fake_calendar.json"))


def _fake_load() -> dict:
    try:
        return json.loads(_fake_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _fake_save(data: dict) -> None:
    _fake_path().write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ---------------- 도구 ----------------

def _precheck() -> dict | None:
    if not _env("CALENDAR_ID"):
        return _error("no_calendar_id", "캘린더 ID가 없습니다. .env 의 CALENDAR_ID 를 설정하세요.")
    return None


@mcp.tool()
def list_events(time_min: str, time_max: str, max_results: int = 20) -> dict:
    """연습용 캘린더의 일정을 읽기 전용으로 조회한다. time_min, time_max 는 ISO 시각(예: 2026-10-24T00:00:00+09:00)."""
    bad = _precheck()
    if bad:
        return bad
    if _env("CALENDAR_BACKEND", "google") == "fake":
        if _fake_modes_list_auth():
            return _error("auth_expired", "인증이 만료되었습니다.")
        events = [_normalize_fake(v) for v in _fake_load().values()]
        return {"status": "ok", "events": events[:max_results]}
    service, err = _google_service()
    if err:
        return err
    try:
        res = service.events().list(
            calendarId=_env("CALENDAR_ID"), timeMin=time_min, timeMax=time_max,
            maxResults=max_results, singleEvents=True, orderBy="startTime",
        ).execute()
        return {"status": "ok", "events": [_normalize(e) for e in res.get("items", [])]}
    except Exception as exc:  # googleapiclient.errors.HttpError 등
        return _http_error(exc)


@mcp.tool()
def get_event(event_id: str) -> dict:
    """이벤트 ID로 일정 하나를 다시 조회한다."""
    bad = _precheck()
    if bad:
        return bad
    if _env("CALENDAR_BACKEND", "google") == "fake":
        if _fail_modes().get("get") == "auth":
            return _error("auth_expired", "인증이 만료되었습니다.")
        found = _fake_load().get(event_id)
        if not found:
            return {"status": "not_found"}
        return {"status": "found", "event": _normalize_fake(found)}
    service, err = _google_service()
    if err:
        return err
    try:
        ev = service.events().get(calendarId=_env("CALENDAR_ID"), eventId=event_id).execute()
        return {"status": "found", "event": _normalize(ev)}
    except Exception as exc:
        if getattr(getattr(exc, "resp", None), "status", 0) == 404:
            return {"status": "not_found"}
        return _http_error(exc)


@mcp.tool()
def create_event(event_id: str, title: str, start: str, end: str, timezone: str, location: str = "", description: str = "") -> dict:
    """연습용 캘린더에 일정을 만든다. 같은 event_id 가 이미 있으면 새로 만들지 않고 already_exists 를 돌려준다.
    start, end 는 'YYYY-MM-DDTHH:MM' 형식의 현지 시각이고 timezone 은 IANA 이름(예: Asia/Seoul)이다."""
    if _env("CALENDAR_LOCAL_OWNER").lower() != "true":
        return _error("not_owner", "소유자가 아닌 세션에서는 일정을 등록할 수 없습니다(CALENDAR_LOCAL_OWNER=true 필요).")
    bad = _precheck()
    if bad:
        return bad
    try:
        ZoneInfo(timezone)
        datetime.fromisoformat(start)
        datetime.fromisoformat(end)
    except Exception:
        return _error("bad_input", "시간대나 시각 형식이 올바르지 않습니다.")

    event = {"id": event_id, "title": title, "start": start, "end": end, "timezone": timezone, "location": location}
    if _env("CALENDAR_BACKEND", "google") == "fake":
        data = _fake_load()
        if event_id in data:
            return {"status": "already_exists", "event": _normalize_fake(data[event_id])}
        data[event_id] = event
        _fake_save(data)
        if _fail_modes().get("insert") == "lost_response":
            # 등록은 됐지만 응답이 유실된 상황을 흉내 냅니다.
            return _error("connection_failed", "응답을 받지 못했습니다.")
        return {"status": "created", "event": _normalize_fake(event)}

    service, err = _google_service()
    if err:
        return err
    body = {
        "id": event_id,
        "summary": title,
        "location": location,
        "description": description,
        "start": {"dateTime": start + ":00", "timeZone": timezone},
        "end": {"dateTime": end + ":00", "timeZone": timezone},
    }
    try:
        created = service.events().insert(calendarId=_env("CALENDAR_ID"), body=body).execute()
        return {"status": "created", "event": _normalize(created, timezone)}
    except Exception as exc:
        if getattr(getattr(exc, "resp", None), "status", 0) == 409:
            try:
                existing = service.events().get(calendarId=_env("CALENDAR_ID"), eventId=event_id).execute()
                return {"status": "already_exists", "event": _normalize(existing, timezone)}
            except Exception as exc2:
                return _http_error(exc2)
        return _http_error(exc)


def _fake_modes_list_auth() -> bool:
    return _fail_modes().get("list") == "auth"


def _normalize_fake(ev: dict) -> dict:
    return {
        "id": ev["id"], "title": ev["title"], "start": ev["start"], "end": ev["end"],
        "timezone": ev["timezone"], "location": ev.get("location", ""), "html_link": "",
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
