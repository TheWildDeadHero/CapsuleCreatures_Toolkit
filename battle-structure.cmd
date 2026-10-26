@echo off
rem Starts the CapsuleCreatures battle editor on its structure pages. The first run sets up the toolkit's
rem Python environment (.venv in this folder); see toolkit\env.py.
where py >nul 2>nul
if %errorlevel%==0 (
   py -3 "%~dp0toolkit\env.py" run battle-structure %*
) else (
   python "%~dp0toolkit\env.py" run battle-structure %*
)
exit /b %errorlevel%
