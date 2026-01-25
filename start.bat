@echo off
setlocal
cd /d "%~dp0"
git pull --autostash -X ours --no-edit
set UAT_AUTORESTART=1

pip install -r requirements.txt

REM Try python3 first
where python3 >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo Using system python3...
    python3 main.py
    if %ERRORLEVEL% EQU 0 goto end
)

REM Fallback to venv
echo python3 not found or failed, attempting venv...
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
    python main.py
) else (
    echo venv not found, trying system python...
    python main.py
)

:end