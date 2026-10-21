"""LangChain + OpenAI 로 여행 답변을 만드는 로직.

- ask(): 이전 대화(history)를 함께 보내 이어지는 질문에 답합니다.
- complete(): 시스템 프롬프트 하나와 요청 하나만 보냅니다. 인기 여행지, 비교처럼 구조화된 답에 씁니다.
- 외부 검색은 쓰지 않습니다. 모델이 알고 있는 지식으로 답합니다.
- 오류는 고정 문구의 ChatbotError 로만 바꿔서 던집니다.
  원본 예외 문자열(키가 섞일 수 있음)은 화면·로그 어디에도 내보내지 않습니다.
"""

import json

import openai
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from config import (
    MAX_HISTORY_MESSAGES,
    REQUEST_TIMEOUT_SECONDS,
    SYSTEM_PROMPT,
    TEMPERATURE,
    get_api_key,
    get_model_name,
)


class ChatbotError(Exception):
    """화면에 그대로 보여줘도 안전한 고정 문구만 담는 오류."""


MSG_NO_KEY = (
    "OPENAI_API_KEY 가 설정되지 않았습니다. "
    ".env 파일에 OPENAI_API_KEY=키값 형태로 입력한 뒤 다시 시도하세요."
)
MSG_AUTH = "API 키가 올바르지 않거나 권한이 없습니다. .env 의 OPENAI_API_KEY 를 확인하세요."
MSG_MODEL = "모델을 사용할 수 없습니다. .env 의 OPENAI_MODEL 이름을 확인하세요."
MSG_RATE = "요청이 너무 많거나 사용 한도를 넘었습니다. 잠시 뒤 다시 시도하거나 계정의 사용 한도를 확인하세요."
MSG_CONN = "OpenAI 서버에 연결하지 못했습니다. 인터넷 연결을 확인하고 다시 시도하세요."
MSG_BAD_REQUEST = "요청을 처리할 수 없습니다. 질문 내용을 바꿔 다시 시도하세요."
MSG_OTHER = "답변을 만드는 중 문제가 생겼습니다. 잠시 뒤 다시 시도하세요."
MSG_PARSE = "답변 형식을 읽지 못했습니다. 다시 시도해 주세요."


def _build_chain(api_key: str, model: str, system_prompt: str, with_history: bool, effort: str | None = None):
    # 시스템 프롬프트 안의 { } 는 템플릿 변수로 읽히므로 두 번 써서 글자 그대로 보내게 합니다.
    # (JSON 형식 예시를 프롬프트에 넣을 때 필요합니다.)
    escaped = system_prompt.replace("{", "{{").replace("}", "}}")
    parts = [("system", escaped)]
    if with_history:
        parts.append(MessagesPlaceholder("history"))
    parts.append(("human", "{question}"))
    prompt = ChatPromptTemplate.from_messages(parts)
    # TEMPERATURE 가 None 이면 보내지 않습니다. 일부 모델은 기본값(1)만 받습니다.
    extra = {} if TEMPERATURE is None else {"temperature": TEMPERATURE}
    if effort:
        extra["reasoning_effort"] = effort
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        **extra,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=1,
    )
    return prompt | llm | StrOutputParser()


def _to_messages(history: list[dict] | None) -> list:
    """화면 기록({"role", "content"} 목록)을 LangChain 메시지로 바꾸고, 최근 것만 남깁니다."""
    messages = []
    for item in (history or [])[-MAX_HISTORY_MESSAGES:]:
        if item["role"] == "user":
            messages.append(HumanMessage(content=item["content"]))
        else:
            messages.append(AIMessage(content=item["content"]))
    return messages


def _run(
    system_prompt: str,
    question: str,
    history: list[dict] | None,
    with_history: bool,
    effort: str | None = None,
) -> str:
    api_key = get_api_key()
    if not api_key:
        raise ChatbotError(MSG_NO_KEY)

    # 예외 메시지에 키가 섞여 있을 수 있으므로 내용은 읽지 않고 종류만 구분합니다.
    # `from None` 으로 원본 예외 연결도 끊어 트레이스백에도 남지 않게 합니다.
    try:
        chain = _build_chain(api_key, get_model_name(), system_prompt, with_history, effort)
        payload = {"question": question}
        if with_history:
            payload["history"] = _to_messages(history)
        return chain.invoke(payload)
    except (openai.AuthenticationError, openai.PermissionDeniedError):
        raise ChatbotError(MSG_AUTH) from None
    except openai.NotFoundError:
        raise ChatbotError(MSG_MODEL) from None
    except openai.RateLimitError:
        raise ChatbotError(MSG_RATE) from None
    except openai.APIConnectionError:  # APITimeoutError 포함
        raise ChatbotError(MSG_CONN) from None
    except openai.BadRequestError:
        raise ChatbotError(MSG_BAD_REQUEST) from None
    except Exception:
        raise ChatbotError(MSG_OTHER) from None


def ask(question: str, history: list[dict] | None = None, effort: str | None = None) -> str:
    """질문과 이전 대화(history)를 보내 답변 문자열을 돌려줍니다. 실패하면 ChatbotError.

    effort 는 추론 강도입니다. 비워 두면 모델 기본값을 씁니다.
    """
    question = (question or "").strip()
    if not question:
        # 방어용: 화면에서 먼저 걸러지지만, 여기서도 API 호출은 하지 않습니다.
        raise ChatbotError("질문이 비어 있습니다.")
    return _run(SYSTEM_PROMPT, question, history, with_history=True, effort=effort)


def complete(system_prompt: str, user_text: str, effort: str | None = None) -> str:
    """이전 대화 없이 시스템 프롬프트와 요청만 보냅니다. 실패하면 ChatbotError."""
    return _run(system_prompt, user_text, None, with_history=False, effort=effort)


def complete_json(system_prompt: str, user_text: str, effort: str | None = None):
    """JSON 으로 답을 받아 파이썬 값으로 돌려줍니다. 형식이 깨졌으면 ChatbotError."""
    raw = complete(system_prompt, user_text, effort=effort).strip()
    # 모델이 ```json 펜스를 붙이는 경우를 대비해 벗겨냅니다.
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw[raw.find("{") if "{" in raw else raw.find("["):]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ChatbotError(MSG_PARSE) from None
