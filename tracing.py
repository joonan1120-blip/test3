"""LangSmith 추적 도우미.

- LANGSMITH_TRACING=true 와 키가 .env 에 있을 때만 실제로 기록됩니다. 아니면 아무 일도 하지 않습니다.
- langsmith 패키지가 없어도 앱이 멈추지 않도록, 없으면 아무것도 하지 않는 대체 함수를 씁니다.
"""

try:
    from langsmith import traceable
except ImportError:  # pragma: no cover
    def traceable(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]

        def deco(fn):
            return fn

        return deco

try:
    from langsmith.wrappers import wrap_openai
except ImportError:  # pragma: no cover
    def wrap_openai(client):
        return client

__all__ = ["traceable", "wrap_openai"]
