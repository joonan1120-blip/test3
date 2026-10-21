"""여행이 Streamlit 화면. 실행: streamlit run app.py"""

import streamlit as st

import ui_cards
import views
from config import APP_VERSION, get_api_key, get_kakao_key

st.set_page_config(page_title="여행이", layout="centered")

# 토스 스타일 참고: 밝은 회색 바탕, 흰색 카드, 파란 강조색, 큰 글자, 넉넉한 여백.
# 토스의 로고나 이미지는 쓰지 않고 색과 배치 원칙만 가져왔습니다.
TOSS_CSS = """
<style>
  :root {
    --toss-blue: #3182F6;
    --toss-blue-soft: #E8F3FF;
    --toss-text: #191F28;
    --toss-sub: #8B95A1;
    --toss-bg: #F2F4F6;
    --toss-card: #FFFFFF;
    --toss-line: #E5E8EB;
    --toss-row: #FAFBFD;
    --toss-hover: #F0F6FF;
    --toss-soft-text: #1B64DA;
    --toss-shadow: 25, 31, 40;
  }
  /* 다크 모드: 사용 중인 기기의 설정을 따라갑니다 */
  @media (prefers-color-scheme: dark) {
    :root {
      --toss-blue: #4C93FF;
      --toss-blue-soft: #1B2B45;
      --toss-text: #F2F4F6;
      --toss-sub: #9AA3AF;
      --toss-bg: #0F1217;
      --toss-card: #1B1F27;
      --toss-line: #2C323C;
      --toss-row: #20252E;
      --toss-hover: #232C3B;
      --toss-soft-text: #8DBBFF;
      --toss-shadow: 0, 0, 0;
    }
  }
  .stApp { background: var(--toss-bg); }
  header[data-testid="stHeader"] { background: transparent; }
  #MainMenu, footer { visibility: hidden; }
  .block-container { max-width: 1000px; padding-top: 2.5rem; padding-bottom: 7rem; }

  /* 대화 속 표: 구분 칸(세 번째)은 줄바꿈하지 않아 글자가 세로로 깨지지 않게 합니다 */
  [data-testid="stChatMessage"] th:nth-child(3),
  [data-testid="stChatMessage"] td:nth-child(3) {
    white-space: nowrap;
    min-width: 4.8em;
  }

  h1 { color: var(--toss-text); font-weight: 800; letter-spacing: -0.5px; font-size: 2rem; }

  /* 대화 말풍선: 흰 카드 */
  [data-testid="stChatMessage"] {
    background: var(--toss-card);
    border-radius: 20px;
    padding: 1rem 1.25rem;
    margin-bottom: 0.75rem;
    box-shadow: 0 2px 8px rgba(var(--toss-shadow), 0.06);
    border: none;
  }
  [data-testid="stChatMessage"] p,
  [data-testid="stChatMessage"] li {
    color: var(--toss-text);
    font-size: 1rem;
    line-height: 1.65;
  }
  /* 사용자 질문은 파란 카드로 구분 */
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background: var(--toss-blue);
  }
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) p {
    color: #FFFFFF;
  }
  [data-testid="stChatMessageAvatarUser"],
  [data-testid="stChatMessageAvatarAssistant"] {
    display: none;
  }

  /* 입력창: 둥근 카드형, 포커스 때 파란 테두리 */
  [data-testid="stChatInput"] {
    border-radius: 18px;
    background: var(--toss-card);
    box-shadow: 0 4px 16px rgba(var(--toss-shadow), 0.10);
    border: none;
  }
  [data-testid="stChatInput"] textarea { font-size: 1rem; color: var(--toss-text); }
  [data-testid="stChatInput"] button { background: var(--toss-blue); border-radius: 12px; }
  [data-testid="stChatInput"]:focus-within,
  [data-testid="stChatInput"] div[data-baseweb="textarea"]:focus-within {
    border-color: var(--toss-blue) !important;
    box-shadow: 0 0 0 2px var(--toss-blue-soft), 0 4px 16px rgba(var(--toss-shadow), 0.10) !important;
  }
  [data-testid="stChatInputContainer"] { border-color: transparent !important; }

  /* 본문 버튼 */
  .stButton > button[kind="primary"] {
    background: var(--toss-blue);
    border: none;
    border-radius: 14px;
    font-weight: 700;
    color: #FFFFFF;
  }
  .stButton > button[kind="secondary"] {
    border-radius: 14px;
    border: none;
    background: var(--toss-card);
    color: var(--toss-blue);
    font-weight: 700;
    box-shadow: 0 2px 8px rgba(var(--toss-shadow), 0.06);
  }

  /* 사이드바 메뉴: 선택한 메뉴는 파란 배경 + 흰 글씨, 나머지는 흰 배경 + 검은 글씨 */
  [data-testid="stSidebar"] { background: var(--toss-card); }
  [data-testid="stSidebar"] h2 { color: var(--toss-text); font-weight: 800; }
  [data-testid="stSidebar"] .stButton > button {
    width: 100%;
    justify-content: flex-start;
    text-align: left;
    border-radius: 14px;
    padding: 0.7rem 1rem;
    font-size: 1rem;
    box-shadow: none;
  }
  [data-testid="stSidebar"] .stButton > button[kind="secondary"] {
    background: var(--toss-card);
    color: var(--toss-text);
    font-weight: 600;
  }
  [data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {
    background: var(--toss-bg);
    color: var(--toss-text);
  }
  [data-testid="stSidebar"] .stButton > button[kind="primary"] {
    background: var(--toss-blue);
    color: #FFFFFF;
    font-weight: 700;
  }
  /* 저장된 대화 목록: 메뉴 아래로 들여써서 하위 항목처럼 보이게 */
  .st-key-saved_sub {
    margin-left: 14px;
    padding-left: 12px;
    border-left: 2px solid var(--toss-line);
  }
  .st-key-saved_sub .stButton > button { font-size: 0.92rem; padding: 0.55rem 0.8rem; }

  /* 대화 삭제 버튼(×): 빨간 버튼에 흰 아이콘. 마우스를 올리면 더 진해지고 빛이 납니다.
     버튼이 .stButton 안쪽 요소 아래에 있어서 자식 선택자(>) 대신 하위 선택자를 씁니다. */
  [class*="st-key-subdel_"] .stButton button {
    font-size: 1.7rem;
    line-height: 1;
    font-weight: 400;
    width: 44px;
    min-height: 44px;
    padding: 0;
    color: #FFFFFF;
    background: #F04452;
    border: none;
    border-radius: 12px;
    box-shadow: 0 4px 12px rgba(240, 68, 82, 0.30);
    transition: background 0.2s ease, box-shadow 0.25s ease, transform 0.15s ease;
  }
  [class*="st-key-subdel_"] .stButton button:hover {
    color: #FFFFFF;
    background: #D93A47;
    box-shadow: 0 0 0 3px rgba(240, 68, 82, 0.20), 0 0 20px rgba(240, 68, 82, 0.55);
    transform: none;
  }

  /* 대화 속 마크다운 표: 카드처럼 둥글게, 헤더는 파란 바탕 */
  [data-testid="stChatMessage"] table {
    width: 100%;
    display: table;
    border-collapse: separate;
    border-spacing: 0;
    border: 1px solid var(--toss-line);
    border-radius: 14px;
    overflow: hidden;
    font-size: 0.93rem;
    margin: 0.5rem 0 0.75rem;
    background: var(--toss-card);
  }
  [data-testid="stChatMessage"] th {
    background: var(--toss-blue-soft);
    color: var(--toss-soft-text);
    font-weight: 700;
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid var(--toss-line);
  }
  [data-testid="stChatMessage"] td {
    padding: 10px 12px;
    border-top: 1px solid var(--toss-line);
    vertical-align: top;
    color: var(--toss-text);
  }
  [data-testid="stChatMessage"] tbody tr:nth-child(even) td { background: var(--toss-row); }
  [data-testid="stChatMessage"] tbody tr:hover td { background: var(--toss-hover); }
  [data-testid="stChatMessage"] th:first-child,
  [data-testid="stChatMessage"] td:first-child { white-space: nowrap; font-weight: 700; color: var(--toss-blue); }

  /* ===== 입체감과 모션 ===== */
  /* 배경: 옅은 빛이 번지는 그라데이션으로 깊이감을 줍니다 */
  .stApp {
    background:
      radial-gradient(1200px 500px at 0% -10%, rgba(49, 130, 246, 0.10), transparent 60%),
      radial-gradient(900px 400px at 100% 0%, rgba(124, 58, 237, 0.07), transparent 55%),
      var(--toss-bg);
    background-attachment: fixed;
  }

  /* 제목: 파란 그라데이션 글자와 짧은 밑줄 */
  h1 {
    background: linear-gradient(90deg, var(--toss-text) 0%, var(--toss-blue) 120%);
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent !important;
    animation: fade-up 0.6s ease-out both;
    padding-bottom: 0.25rem;
  }

  @keyframes fade-up {
    from { opacity: 0; transform: translateY(14px); }
    to { opacity: 1; transform: translateY(0); }
  }
  @keyframes pop-in {
    from { opacity: 0; transform: scale(0.97); }
    to { opacity: 1; transform: scale(1); }
  }

  /* 대화 말풍선: 등장 모션 + 여러 겹 그림자로 떠 있는 느낌 */
  [data-testid="stChatMessage"] {
    box-shadow: 0 1px 2px rgba(var(--toss-shadow), 0.05), 0 10px 28px rgba(var(--toss-shadow), 0.08);
    animation: fade-up 0.45s cubic-bezier(0.2, 0.8, 0.2, 1) both;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
  }
  [data-testid="stChatMessage"]:hover {
    transform: translateY(-2px);
    box-shadow: 0 2px 4px rgba(var(--toss-shadow), 0.06), 0 16px 36px rgba(var(--toss-shadow), 0.12);
  }
  [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    box-shadow: 0 6px 18px rgba(49, 130, 246, 0.35);
  }

  /* 테두리 카드(인기 여행지, 날씨, 저장된 대화 등): 등장 + 호버 리프트 */
  [data-testid="stVerticalBlockBorderWrapper"] > div {
    background: var(--toss-card);
    border-radius: 18px !important;
    box-shadow: 0 1px 2px rgba(var(--toss-shadow), 0.04), 0 8px 24px rgba(var(--toss-shadow), 0.07);
    animation: pop-in 0.4s ease-out both;
    transition: transform 0.22s ease, box-shadow 0.22s ease;
  }
  [data-testid="stVerticalBlockBorderWrapper"] > div:hover {
    transform: translateY(-3px);
    box-shadow: 0 2px 6px rgba(var(--toss-shadow), 0.06), 0 18px 40px rgba(var(--toss-shadow), 0.14);
  }

  /* 지표 카드(환율 등) */
  [data-testid="stMetric"] {
    background: var(--toss-card);
    border-radius: 18px;
    padding: 14px 18px;
    box-shadow: 0 8px 24px rgba(var(--toss-shadow), 0.07);
    animation: pop-in 0.4s ease-out both;
    transition: transform 0.22s ease;
  }
  [data-testid="stMetric"]:hover { transform: translateY(-3px); }

  /* 버튼: 누르면 눌리고, 주 버튼은 파란 그림자로 떠 있게 */
  .stButton > button {
    transition: transform 0.15s ease, box-shadow 0.2s ease, background 0.2s ease;
  }
  .stButton > button:hover { transform: translateY(-1px); }
  .stButton > button:active { transform: scale(0.97); }
  .stButton > button[kind="primary"] {
    box-shadow: 0 8px 18px rgba(49, 130, 246, 0.32);
  }
  .stButton > button[kind="primary"]:hover {
    box-shadow: 0 12px 24px rgba(49, 130, 246, 0.42);
  }

  /* 사이드바 메뉴: 선택 메뉴에 빛 번짐, 호버 시 살짝 밀림 */
  [data-testid="stSidebar"] {
    box-shadow: 8px 0 30px rgba(var(--toss-shadow), 0.05);
  }
  [data-testid="stSidebar"] .stButton > button[kind="primary"] {
    box-shadow: 0 10px 24px rgba(49, 130, 246, 0.38);
  }
  [data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {
    transform: translateX(4px);
  }

  /* 탭 */
  [data-testid="stTabs"] button[role="tab"] {
    font-weight: 700;
    transition: color 0.2s ease;
  }

  /* 입력창: 떠 있는 느낌 강화 */
  [data-testid="stChatInput"] {
    transition: box-shadow 0.25s ease, transform 0.25s ease;
  }
  [data-testid="stChatInput"]:focus-within {
    transform: translateY(-2px);
  }

  /* 움직임 줄이기 설정을 켠 사용자에게는 모션을 끕니다 */
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
      animation: none !important;
      transition: none !important;
    }
  }

  /* 다크 모드에서 흐릿해지는 보조 글자 */
  .stApp [data-testid="stCaptionContainer"], .stApp small { color: var(--toss-sub); }
  .stApp h2, .stApp h3, .stApp h4 { color: var(--toss-text); }

  /* 토스트 */
  [data-testid="stToast"] { border-radius: 14px; }
</style>
"""
st.markdown(TOSS_CSS, unsafe_allow_html=True)
st.markdown(ui_cards.CSS, unsafe_allow_html=True)

MENU = {
    "홈": views.home_view,
    "여행 질문": views.chat_view,
    "인기 여행지": views.popular_view,
    "여행지 비교": views.compare_view,
    "날씨 보기": views.weather_view,
    "캘린더 등록": views.calendar_view,
    "저장된 대화": views.saved_view,
}

if "menu" not in st.session_state:
    st.session_state.menu = "홈"


def _set_menu(name: str):
    st.session_state.menu = name


with st.sidebar:
    st.header("여행이")
    st.caption(f"v{APP_VERSION}")
    current = st.session_state.menu
    for name in MENU:
        st.button(
            name,
            key=f"menu_{name}",
            type="primary" if current == name else "secondary",
            on_click=_set_menu,
            args=(name,),
        )
    views.saved_sidebar(current)
    views.calendar_sidebar(current)

    # 키가 비어 있으면 이유를 바로 알 수 있게 안내합니다(값은 보여 주지 않습니다).
    _missing = [name for name, value in (("OPENAI_API_KEY", get_api_key()), ("KAKAO_REST_API_KEY", get_kakao_key())) if not value]
    if _missing:
        st.warning(
            "설정이 비어 있습니다: " + ", ".join(_missing)
            + "\n\n내 PC에서는 .env, 배포한 앱에서는 Cloud 의 Secrets 에 같은 이름으로 입력하세요."
        )

MENU[st.session_state.menu]()
