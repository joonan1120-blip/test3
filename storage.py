"""저장 위치 선택: 내 PC 파일 또는 접속 중인 브라우저 세션.

- APP_STORAGE=file    : 대화와 일정을 앱 폴더의 json 파일에 저장합니다. 내 PC에서 혼자 쓸 때만 씁니다.
- APP_STORAGE=session : (기본) 접속한 사람의 세션 안에만 저장합니다. 새로고침하거나 창을 닫으면 사라집니다.
배포(Cloud)에서는 반드시 session 이어야 합니다. 파일에 저장하면 모든 방문자가 같은 파일을 공유해서
다른 사람의 대화가 목록에 보이기 때문입니다.
"""

import os


def use_files() -> bool:
    return (os.environ.get("APP_STORAGE") or "session").strip().lower() == "file"


def session_list(key: str) -> list:
    """세션에 저장된 목록(없으면 새로 만듭니다)."""
    import streamlit as st

    return st.session_state.setdefault(key, [])
