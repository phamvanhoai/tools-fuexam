@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
    py "%~dp0fuexam_gui.py"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Khong tim thay Python. Hay cai Python va bat tuy chon Add Python to PATH.
        pause
        exit /b 1
    )
    python "%~dp0fuexam_gui.py"
)

if errorlevel 1 pause
