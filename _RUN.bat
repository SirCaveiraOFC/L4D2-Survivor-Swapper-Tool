@echo off
cd /d "%~dp0"
if "%~1"=="" (
    where pythonw >nul 2>&1
    if %errorlevel%==0 (
        start "" pythonw "app.py"
        exit /b 0
    )
)
python "app.py" %*
if errorlevel 1 pause
