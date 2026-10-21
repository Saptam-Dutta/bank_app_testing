@echo off
REM Runs the WHOLE suite (database + API) and writes an HTML report to tests\reports\
cd /d "%~dp0"
if not exist reports mkdir reports
python -m pytest --html=reports\full_report.html --self-contained-html
echo.
echo Report: %~dp0reports\full_report.html
pause
