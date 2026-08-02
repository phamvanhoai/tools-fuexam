@echo off
cd /d "%~dp0"
python "%~dp0fuexam_gui.py"
if errorlevel 1 pause
