@echo off
rem Godot AI Agent Platform - Backend Launcher
rem Deployed by the installer to {app}\Start-Backend.cmd
rem Sets the data directory and SQLite connection so the backend works
rem out of the box, with no manual GODOT_AI_* environment setup required.
rem Data directory is separate from the install dir and is kept on uninstall.

setlocal EnableExtensions

set "DATA_ROOT=%LOCALAPPDATA%\GodotAIAgent"
if not exist "%DATA_ROOT%\data" mkdir "%DATA_ROOT%\data"
if not exist "%DATA_ROOT%\logs" mkdir "%DATA_ROOT%\logs"

set "GODOT_AI_DATA_DIR=%DATA_ROOT%\data"
set "GODOT_AI_LOG_DIR=%DATA_ROOT%\logs"

rem SQLite URL needs forward slashes; convert backslashes to forward slashes
set "DB_DIR_FWD=%DATA_ROOT:\=/%"
set "GODOT_AI_DATABASE_URL=sqlite+aiosqlite:///%DB_DIR_FWD%/data/godot_ai_agent.db"

rem Launch the backend (in backend\ next to this script); pass through args
"%~dp0backend\godot-ai-backend.exe" %*
endlocal
