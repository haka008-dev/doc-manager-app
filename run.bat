@echo off
cd /d "%~dp0"
title Chatbot Doc Manager
echo.
echo  Chatbot Doc Manager - starting...
echo  A browser window will open automatically.
echo  To stop the app, just close this window.
echo.
python -m streamlit run app.py
if errorlevel 1 (
    echo.
    echo  [ERROR] Failed to start.
    echo  Try running this command first:
    echo     pip install -r requirements.txt
    echo.
    pause
)
