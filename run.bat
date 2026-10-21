@echo off
chcp 65001 >nul
rem 여행이 챗봇 실행기: 더블클릭하면 필요한 준비를 하고 앱을 켭니다.
cd /d "%~dp0"

rem 1) 가상환경이 없으면 Python 3.12 로 만듭니다.
if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 가상환경을 만드는 중입니다. Python 3.12 가 필요합니다...
    py -3.12 -m venv .venv
    if errorlevel 1 (
        echo.
        echo Python 3.12 를 찾지 못했습니다. https://www.python.org 에서 3.12 를 설치한 뒤 다시 실행하세요.
        pause
        exit /b 1
    )
)

rem 2) 필요한 패키지를 설치합니다(이미 설치돼 있으면 빠르게 넘어갑니다).
echo [2/3] 패키지를 확인하는 중입니다...
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo.
    echo 패키지 설치에 실패했습니다. 인터넷 연결을 확인한 뒤 다시 실행하세요.
    pause
    exit /b 1
)

rem 3) .env 파일이 없으면 만들고 안내한 뒤 멈춥니다.
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo.
    echo .env 파일을 만들었습니다. 메모장으로 열어 OPENAI_API_KEY 값을 채운 뒤 다시 실행하세요.
    echo 카카오 장소 검증을 쓰려면 KAKAO_REST_API_KEY 도 채우세요.
    pause
    exit /b 0
)

rem 4) 앱을 켜고 브라우저를 엽니다. 이 창을 닫으면 앱이 꺼집니다.
echo [3/3] 앱을 켜는 중입니다. 브라우저가 열리지 않으면 http://localhost:8501 로 들어가세요.
start "" "http://localhost:8501"
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless true --server.port 8501
