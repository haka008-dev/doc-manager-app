@echo off
chcp 65001 > nul
cd /d "%~dp0"
title 챗봇 문서 관리기

echo.
echo ========================================
echo   📚 챗봇 문서 관리기
echo ========================================
echo.
echo 브라우저가 자동으로 열립니다.
echo 종료하려면 이 창에서 Ctrl+C 를 누르세요.
echo.

python -m streamlit run app.py
if errorlevel 1 (
    echo.
    echo ⚠️  실행 실패. 의존성이 빠졌을 수 있습니다.
    echo    아래 명령을 실행해보세요:
    echo.
    echo    pip install -r requirements.txt
    echo.
    pause
)
