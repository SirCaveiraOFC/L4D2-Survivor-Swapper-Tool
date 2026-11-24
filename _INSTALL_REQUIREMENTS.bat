@echo off
setlocal
cd /d "%~dp0"

set "PY_CMD="
if exist "%~dp0runtime\python.exe" (
    set "PYTHONPATH="
    set "PYTHONHOME="
    set "PYTHONNOUSERSITE=1"
    set "PYTHONUTF8=1"
    set "PY_CMD=""%~dp0runtime\python.exe"""
) else (
    where python >nul 2>&1
    if %errorlevel%==0 (
        set "PY_CMD=python"
    ) else (
        where py >nul 2>&1
        if %errorlevel%==0 (
            set "PY_CMD=py -3"
        )
    )
)

if "%PY_CMD%"=="" (
    echo [ERROR] Python 3.10+ was not found in PATH.
    echo Install Python from https://www.python.org/downloads/ and check "Add Python to PATH".
    if /i not "%~1"=="--no-pause" pause
    exit /b 1
)

if not exist "requirements.txt" (
    echo [ERROR] requirements.txt not found in "%~dp0".
    if /i not "%~1"=="--no-pause" pause
    exit /b 1
)

echo Installing dependencies from requirements.txt using %PY_CMD%...
%PY_CMD% -m pip install -r "requirements.txt"
set "INSTALL_EXIT=%errorlevel%"

if not "%INSTALL_EXIT%"=="0" (
    echo.
    echo [ERROR] Failed to install dependencies ^(exit code %INSTALL_EXIT%^).
    if /i not "%~1"=="--no-pause" pause
    exit /b %INSTALL_EXIT%
)

echo.
echo [OK] All dependencies are installed. You can now run _RUN.bat or L4D2 Survivor Swapper Tool.exe.
if /i not "%~1"=="--no-pause" pause
exit /b 0
