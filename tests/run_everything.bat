@echo off
REM Runs ALL 618 tests in one go (database, API, schema, smoke, accessibility, UI, load, stress).
REM Takes about 5 minutes. One HTML report: reports\everything_report.html
cd /d "%~dp0"
python -m pip install -r requirements.txt
if not exist reports mkdir reports
python -m pytest -m "" --html=reports\everything_report.html --self-contained-html --junitxml=reports\junit_everything.xml
echo.
echo Report: %~dp0reports\everything_report.html
pause
