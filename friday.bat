@echo off
title FRIDAY
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo  Python is not installed or not on PATH.
  echo  Install: https://www.python.org/downloads/
  echo  IMPORTANT: tick "Add python.exe to PATH"
  echo.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)

python -m pip install -q python-dotenv groq pyautogui sounddevice scipy pyttsx3 Pillow
python start_friday.py
if errorlevel 1 pause