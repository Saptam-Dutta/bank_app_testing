@echo off
REM Load, performance, stress and spike tests (about 4 minutes). Numbers are saved in reports\perf\
cd /d "%~dp0"
if not exist reports mkdir reports
python -m pytest -m "performance or stress" --html=reports\load_stress_report.html --self-contained-html
echo.
echo Report: %~dp0reports\load_stress_report.html
pause
