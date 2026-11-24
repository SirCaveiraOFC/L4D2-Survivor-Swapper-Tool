@echo off
setlocal
cd /d "%~dp0"

if exist "%~dp0runtime\pythonw.exe" (
    set "PYTHONPATH="
    set "PYTHONHOME="
    set "PYTHONNOUSERSITE=1"
    set "PYTHONUTF8=1"
    if "%~1"=="" (
        start "" "%~dp0runtime\pythonw.exe" "app.py"
        exit /b 0
    )
    "%~dp0runtime\python.exe" "app.py" %*
    if errorlevel 1 pause
    exit /b %errorlevel%
)

if "%~1"=="" (
    where pythonw >nul 2>&1
    if %errorlevel%==0 (
        start "" pythonw "app.py"
        exit /b 0
    )
)
python "app.py" %*
if errorlevel 1 pause
