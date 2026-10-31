@echo off
rem Starts the CapsuleCreatures location editor. The first run sets up the toolkit's
rem Python environment (.venv in this folder); see toolkit\env.py.
where py >nul 2>nul
if %errorlevel%==0 (
   py -3 "%~dp0toolkit\env.py" run location-editor %*
) else (
   python "%~dp0toolkit\env.py" run location-editor %*
)
exit /b %errorlevel%
