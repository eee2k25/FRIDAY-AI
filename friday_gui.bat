@echo off
title FRIDAY GUI
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo Python not found. Install https://www.python.org/downloads/
  echo Tick "Add python.exe to PATH"
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
python -m pip install -q python-dotenv groq pyautogui sounddevice scipy pyttsx3 Pillow numpy
python start_friday.py --gui
if errorlevel 1 pause