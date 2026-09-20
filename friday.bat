@echo off
title FRIDAY AI
cd /d C:\MARVEL\FRIDAY
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)
python friday.py
pause
