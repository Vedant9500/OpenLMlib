@echo off
setlocal enabledelayedexpansion

:: OpenLMlib — Windows entry point (cmd)
:: Finds the vendored Python venv and delegates to the openlmlib module.

if not defined OPENLMLIB_HOME (
  set "OPENLMLIB_HOME=%USERPROFILE%\.openlmlib"
)

set "VENV_PYTHON=%OPENLMLIB_HOME%\venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
  echo error: OpenLMlib is not installed. 1>&2
  echo Run: npm install -g openlmlib 1>&2
  exit /b 1
)

"%VENV_PYTHON%" -m openlmlib %*
