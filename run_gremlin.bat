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

python -c "import win32gui" >nul 2>&1
if errorlevel 1 (
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
)

python desktop_gremlin.py %*
pause
