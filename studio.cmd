@echo off
rem Starts the CapsuleCreatures Studio, every editor in one window. The first run
rem sets up the toolkit's Python environment (.venv in this folder); see toolkit\env.py.
where py >nul 2>nul
if %errorlevel%==0 (
   py -3 "%~dp0toolkit\env.py" run studio %*
) else (
   python "%~dp0toolkit\env.py" run studio %*
)
exit /b %errorlevel%
