"""대화 저장소: 여행 대화를 chats.json 파일에 저장하고 다시 불러옵니다.

- 대화 하나 = 여행지 한 묶음(예: 부산 상담, 인천 상담)입니다.
- 새 대화를 시작하면 이전 대화는 그대로 남아 있어서 나중에 다시 열 수 있습니다.
- 파일이 깨졌거나 없으면 빈 목록으로 시작합니다. 앱이 멈추지 않도록 예외를 삼킵니다.
"""

import json
import uuid
from datetime import datetime
from pathlib import Path

import storage

STORE_PATH = Path(__file__).resolve().parent / "chats.json"
TITLE_LEN = 24


def load_chats() -> list[dict]:
    if not storage.use_files():
        return storage.session_list("_saved_chats")
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        chats = data.get("chats", [])
        return chats if isinstance(chats, list) else []
    except (OSError, ValueError, AttributeError):
        return []


def _save_all(chats: list[dict]) -> None:
    if not storage.use_files():
        import streamlit as st

        st.session_state["_saved_chats"] = chats
        return
    try:
        STORE_PATH.write_text(
            json.dumps({"chats": chats}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        # 저장에 실패해도 대화 자체는 화면에서 계속 쓸 수 있어야 합니다.
        pass


def save_chat(chat_id: str | None, messages: list[dict]) -> str:
    """대화를 저장하고 그 id 를 돌려줍니다. chat_id 가 없으면 새로 만듭니다."""
    chats = load_chats()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if chat_id is None:
        chat_id = uuid.uuid4().hex
    first_question = next((m["content"] for m in messages if m["role"] == "user"), "새 대화")
    title = first_question if len(first_question) <= TITLE_LEN else first_question[:TITLE_LEN] + "…"

    entry = {"id": chat_id, "title": title, "updated": now, "messages": messages}
    replaced = False
    for i, chat in enumerate(chats):
        if chat.get("id") == chat_id:
            chats[i] = entry
            replaced = True
            break
    if not replaced:
        chats.insert(0, entry)
    _save_all(chats)
    return chat_id


def get_chat(chat_id: str) -> dict | None:
    return next((c for c in load_chats() if c.get("id") == chat_id), None)


def delete_chat(chat_id: str) -> None:
    _save_all([c for c in load_chats() if c.get("id") != chat_id])
