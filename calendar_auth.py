"""구글 캘린더 로그인(OAuth)과 토큰 저장.

실행:
    .venv\\Scripts\\python.exe calendar_auth.py            # 브라우저로 로그인하고 토큰 저장
    .venv\\Scripts\\python.exe calendar_auth.py --check    # 토큰 갱신과 연습용 캘린더 읽기 조회 확인

필요한 .env 변수(값은 .env 에만 쓰고, 채팅이나 문서에 붙여넣지 않습니다):
    GOOGLE_CLIENT_SECRET_FILE  Desktop OAuth 클라이언트 JSON 경로(프로젝트 밖 비공개 위치)
    GOOGLE_TOKEN_FILE          로그인 뒤 만들어질 토큰 파일 경로(프로젝트 밖 비공개 위치)
    CALENDAR_ID                연습용 캘린더 ID

- 토큰 원문은 출력하지 않습니다. 사용자가 브라우저에서 직접 동의해야 합니다.
- 권한: calendar.events.owned (본인 소유 캘린더의 일정)
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env", override=True)
SCOPES = ["https://www.googleapis.com/auth/calendar.events.owned"]


def _inside_project(path: Path) -> bool:
    try:
        path.resolve().relative_to(ROOT)
        return True
    except ValueError:
        return False


def login() -> int:
    secret = os.getenv("GOOGLE_CLIENT_SECRET_FILE", "").strip()
    token = os.getenv("GOOGLE_TOKEN_FILE", "").strip()
    if not secret or not Path(secret).exists():
        print("GOOGLE_CLIENT_SECRET_FILE 이 없거나 파일을 찾을 수 없습니다. .env 를 확인하세요.")
        return 1
    if not token:
        print("GOOGLE_TOKEN_FILE 경로가 비어 있습니다. .env 를 확인하세요.")
        return 1
    if _inside_project(Path(secret)) or _inside_project(Path(token)):
        print("클라이언트 JSON 과 토큰 파일은 프로젝트 폴더 밖 비공개 위치에 두어야 합니다. 경로를 바꿔 주세요.")
        return 1

    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
    print("브라우저가 열립니다. 테스트 사용자로 등록한 본인 계정을 고르고, 앱 이름과 권한을 확인한 뒤 허용하세요.")
    creds = flow.run_local_server(port=0)
    Path(token).parent.mkdir(parents=True, exist_ok=True)
    Path(token).write_text(creds.to_json(), encoding="utf-8")
    print(f"로그인 완료. 토큰을 저장했습니다: {token}")
    return 0


def check() -> int:
    """토큰 갱신과 지정 캘린더 읽기 조회를 확인합니다. 일정은 만들지 않습니다."""
    from calendar_server import list_events

    now = datetime.now(timezone.utc)
    result = list_events(
        now.isoformat(timespec="seconds"),
        (now + timedelta(days=7)).isoformat(timespec="seconds"),
        5,
    )
    if result.get("status") == "ok":
        print(f"읽기 조회 성공: 앞으로 7일 일정 {len(result['events'])}건")
        return 0
    print(f"실패({result.get('error_kind')}): {result.get('message')}")
    return 1


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else login())
