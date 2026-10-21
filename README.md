# 여행이 (여행 챗봇)

국내 여행을 추천하고 일정을 짜 주는 챗봇입니다. 장소는 카카오맵, 날씨는 Open-Meteo에서 조회한 사실만 근거로 답합니다.
(Python 3.12, Streamlit, OpenAI API, 카카오 로컬 API, Open-Meteo, LangSmith 추적)

## 기능

- **여행 질문**: 가볼 만한 곳 추천 → "이 장소들로 일정 짜기" → 일차별 카드 일정. 장소·날씨 조회 질문, 되물음 이어 답하기
- **인기 여행지 · 여행지 비교 · 날씨 보기**, 홈의 환율 띠와 지도(끌어서 이동, 확대·축소, 지역별 사진 카드)
- **캘린더 등록**: 일정 미리보기 확인 후 구글 캘린더에 등록(내 PC 전용, MCP 서버 사용)
- **저장된 대화**: 대화 다시 열기, 삭제

## 구조

| 파일 | 역할 |
| --- | --- |
| `app.py` | 화면 틀과 메뉴 |
| `views.py`, `ui_cards.py`, `map_widget.py`, `korea_map.py` | 메뉴별 화면, 카드 렌더링, 지도 위젯 |
| `agents.py` | 라우터 → 조회 에이전트 / 리서처 → 작성자로 나눈 오케스트레이터 |
| `tools.py` | 도구 등록(장소 검색, 날씨 조회)과 공통 실행(중복 건너뛰기, 실행 기록, 오류 시 중단) |
| `tracing.py` | LangSmith 추적 표시(켜져 있을 때만 기록) |
| `agent.py` | 기존 방식의 조회 에이전트(되돌리기용으로 보존) |
| `chatbot.py`, `config.py`, `prompts.py` | LLM 호출, 설정, 공용 문구 |
| `plan_pipeline.py`, `plan_dates.py`, `kakao_places.py`, `travel_data.py` | 조사 단계, 날짜 추출, 카카오 장소, 날씨·환율 |
| `chat_store.py`, `plan_store.py`, `storage.py` | 대화·일정 저장(파일 또는 세션) |
| `calendar_*.py` | 캘린더 등록(MCP 서버·클라이언트, 구글 로그인) |
| `region_data.json`, `static/photos/` | 홈 지도의 지역별 추천과 사진 |

## 내 PC에서 실행 (Windows)

`run.bat` 을 더블클릭하거나 아래처럼 실행합니다.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python -m streamlit run app.py
```

`.env` 를 열어 키를 채웁니다. `.env` 는 GitHub에 올리지 않습니다.

| 이름 | 설명 |
| --- | --- |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | 모델 호출 |
| `KAKAO_REST_API_KEY` | 장소 검색 |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | LangSmith 추적(선택) |
| `AGENT_MODE` | `modular`(기본) 또는 `legacy`(문제가 생길 때 기존 방식으로 되돌리기) |
| `APP_STORAGE` | `file`(내 PC, 파일에 저장) 또는 `session`(기본, 접속한 사람의 세션에만 저장) |

## 배포 (GitHub + Streamlit Community Cloud)

1. GitHub 저장소를 만들고 이 폴더의 파일을 올립니다. **`.env`, `chats.json`, `calendar_plans.json`, `.venv/` 는 올리지 않습니다.**
   웹 업로드는 `.gitignore` 를 따르지 않으므로 올리기 전에 파일 목록을 직접 확인합니다.
2. [share.streamlit.io](https://share.streamlit.io) 에서 저장소 · 브랜치(`main`) · 시작 파일(`app.py`)을 고릅니다.
3. Advanced settings 에서 Python version 을 **3.12** 로 고르고, Secrets 에 키를 TOML 형식으로 입력합니다.

```toml
OPENAI_API_KEY = "본인 키"
OPENAI_MODEL = "수업에서 안내한 모델 이름"
KAKAO_REST_API_KEY = "본인 키"
LANGSMITH_TRACING = "true"
LANGSMITH_API_KEY = "본인 키"
LANGSMITH_PROJECT = "travel-chatbot"
```

- `APP_STORAGE` 는 **넣지 않습니다**(기본값 `session`). 파일에 저장하면 모든 방문자가 같은 대화 목록을 보게 됩니다.
- 구글 캘린더 관련 값(`CALENDAR_*`, `GOOGLE_*`)도 넣지 않습니다. 배포 앱의 캘린더 등록은 "준비 안 됨"으로 표시됩니다.
- Cloud 에서는 저장한 대화가 새로고침하면 사라집니다(세션 저장). 정상입니다.
- 지역 사진(`static/photos/`)은 지도 카드에 쓰이므로 함께 올립니다. 제3자 사진이므로 저장소를 Public 으로 할지 Private 으로 할지 정하세요.

자세한 올릴 파일 목록은 업로드용 폴더의 `업로드_체크리스트.md` 를 봅니다.
