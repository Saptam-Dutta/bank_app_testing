@echo off
REM Smoke test: a few seconds. Run this first after any change.
cd /d "%~dp0"
python -m pytest -m smoke
pause
