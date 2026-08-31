@echo off
title Desktop Gremlin
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Python isn't on your PATH.
  echo   Get it from https://www.python.org/downloads/ and tick
  echo   "Add python.exe to PATH" during setup, then run this again.
  echo.
  pause
  exit /b 1
)

rem --debug prints to a console, so that mode keeps this window.
echo %* | find /i "--debug" >nul
if not errorlevel 1 (
  python desktop_gremlin.py %*
  pause
  exit /b
)

rem One interpreter start does both jobs: proves pywin32 imports, and hands
rem back the pythonw.exe sitting beside it. No output means the import failed.
set "PYW="
for /f "delims=" %%p in ('python -c "import sys, win32gui; print(sys.executable.replace('python.exe','pythonw.exe'))" 2^>nul') do set "PYW=%%p"

if not defined PYW (
  echo.
  echo   First run - installing pywin32...
  echo.
  python -m pip install --disable-pip-version-check pywin32
  if errorlevel 1 (
    echo.
    echo   That failed. Try:  python -m pip install --user pywin32
    echo.
    pause
    exit /b 1
  )
  for /f "delims=" %%p in ('python -c "import sys, win32gui; print(sys.executable.replace('python.exe','pythonw.exe'))" 2^>nul') do set "PYW=%%p"
)

if not defined PYW set "PYW=pythonw"
if not exist "%PYW%" set "PYW=pythonw"

rem pythonw has no console, so this window closing can't take the gremlins
rem with it. Quit them from the tray icon instead.
start "" "%PYW%" desktop_gremlin.py %*
exit /b
