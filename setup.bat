@echo off
rem FRIDAY AI — double-click installer. Launches setup.ps1 (which self-elevates).
title FRIDAY AI Setup
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 pause
